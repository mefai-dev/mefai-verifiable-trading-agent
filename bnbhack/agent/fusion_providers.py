"""
MEFAI BNB HACK · Omni-Signal Fusion Providers (I/O adapters)

This module turns every live MEFAI capability into a `SourceReading` that the
pure `fusion_core.fuse()` math can combine. Each provider:

  * reads ONE source for a single (symbol, timeframe),
  * reports a direction (+1 long / -1 short / 0 neutral) and a [0,1] strength,
  * reports its OWN historical hit-rate so the core can skill-weight it, and
  * NEVER raises: any failure yields an unavailable reading with a reason, so a
    dead source can only shrink coverage, never crash the fusion.

Directional sources whose track record is unknown default to hit_rate 0.5 so the
core gives them zero weight (they cannot drown out proven sources). Gate-type
sources (CMC regime / derivatives) carry hit_rate=None and are weighted by prior
only, as documented in fusion_core.SourceReading.

Sources wired:
  MEFAI Signal     signal.db signals + signal_performance edge (primary)
  MEFAI Score      mefai_skills.db score_history verdict + outcome
  Deep Composite   mefai_skills.db deep_signals (whale/flow/ai)
  Brain            mefai_skills.db brain_predictions
  Kronos           kronos-engine predictions.db forecast + dir_hit
  Cross Signals    mefai_skills.db cross_reliability (market technical)
  CMC Regime       CMC MCP global_metrics (gate)
  CMC Technicals   CMC MCP per-asset technical_analysis (gate)
  CMC Derivatives  CMC MCP global derivatives (risk gate)
  Perp Funding     per-asset perpetual funding, contrarian crowding tilt (gate)
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from fusion_core import SourceReading

_log = logging.getLogger("mefai.fusion")

# --- DB locations (read-only; env-overridable, same convention as leaderboard.py) ---
SIGNAL_DB = os.getenv("MEFAI_SIGNAL_DB", "data/signal.db")
SKILLS_DB = os.getenv("MEFAI_SKILLS_DB", "data/mefai_skills.db")
KRONOS_DB = os.getenv("MEFAI_KRONOS_DB", "data/predictions.db")

# A source must have at least this many graded outcomes before we trust its
# measured hit-rate; below it we fall back to 0.5 (no skill -> ignored).
MIN_HITRATE_SAMPLES = 20

# How many bars old a TradingView signal may be before its strength decays to
# the floor, and the hard age past which we drop it entirely.
SIGNAL_STALE_BARS = 4
SIGNAL_DROP_BARS = 8

# Per-asset perpetual funding contrarian thresholds (8h funding as a fraction).
# Resting funding sits near +0.01%; only crowding beyond the deadzone tilts the
# vote, reaching full strength at 0.06%. Keyless public endpoint, read-only.
FUNDING_DEADZONE = 0.0001
FUNDING_FULL = 0.0006
# Note: the Binance perp endpoint is geo-restricted from some datacenters, so
# this provider can read unavailable in those regions; the funding gate then
# degrades to neutral (no tilt) rather than blocking, and CMC derivatives is
# the primary funding read in production.
FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FUNDING_TTL = 60.0
_FUNDING_CACHE: Dict[str, Tuple[float, SourceReading]] = {}

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "1w": 604800,
}

# CMC numeric ids for common bases (avoids a search round-trip; falls back to
# search_cryptos for anything not listed).
_CMC_IDS = {
    "BTC": 1, "ETH": 1027, "BNB": 1839, "SOL": 5426, "XRP": 52, "ADA": 2010,
    "DOGE": 74, "AVAX": 5805, "DOT": 6636, "LINK": 1975, "MATIC": 3890,
    "TRX": 1958, "LTC": 2, "ATOM": 3794, "UNI": 7083, "ETC": 1321,
    "FIL": 2280, "APT": 21794, "ARB": 11841, "OP": 11840, "SUI": 20947,
    "NEAR": 6535, "INJ": 7226, "SEI": 23149, "TIA": 22861, "PEPE": 24478,
    "WLD": 13502, "FET": 3773, "RENDER": 5690, "RNDR": 5690, "AAVE": 7278,
    "SHIB": 5994, "BCH": 1831, "XLM": 512, "ICP": 8916, "HBAR": 4642,
}


def _now() -> float:
    return time.time()


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _ro_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _norm_base(symbol: str) -> str:
    """Strip venue/quote decoration down to the bare base asset (BTCUSDT.P -> BTC)."""
    s = (symbol or "").upper().strip()
    s = s.replace(".P", "")
    s = s.split("/")[0].split(":")[0]
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def _norm_tf(timeframe: str) -> str:
    return (timeframe or "").lower().strip()


def _horizon_for_tf(tf: str) -> str:
    if tf in ("1m", "3m", "5m", "15m", "30m", "1h"):
        return "1h"
    if tf in ("2h", "4h", "6h"):
        return "4h"
    return "24h"


def _kronos_interval_for_tf(tf: str) -> str:
    if tf in ("1d", "1w"):
        return "1d"
    if tf in ("2h", "4h", "6h", "12h"):
        return "4h"
    return "1h"


def _dir_from_text(text: Any) -> int:
    t = str(text or "").upper()
    if "STRONG SELL" in t or "SELL" in t or "BEAR" in t or "SHORT" in t:
        return -1
    if "STRONG BUY" in t or "BUY" in t or "BULL" in t or "LONG" in t:
        return 1
    return 0


def _hit_rate(wins: float, losses: float) -> Optional[float]:
    """Measured hit-rate, or None when there is not enough signal to trust it."""
    total = wins + losses
    if total < MIN_HITRATE_SAMPLES:
        return None
    return _clamp(wins / total, 0.0, 1.0)


def _err_reading(name: str, prior: float, hit_rate: Optional[float],
                 exc: BaseException) -> SourceReading:
    """Non-raising failure: log the detail server-side, return a generic,
    non-reflective reason so internal paths never leak into the transcript."""
    _log.warning("fusion source %s unavailable: %s", name, exc)
    return SourceReading(name, 0, 0.0, hit_rate=hit_rate, prior=prior,
                         available=False, detail="source error")


# --- DB providers ------------------------------------------------------------

def _read_mefai_signal(base: str, tf: str) -> SourceReading:
    name = "MEFAI Signal"
    prior = 2.0
    sym = f"{base}USDT.P"
    try:
        conn = _ro_connect(SIGNAL_DB)
        try:
            row = conn.execute(
                "SELECT signal, timestamp, price FROM signals "
                "WHERE symbol = ? AND timeframe = ? "
                "ORDER BY id DESC LIMIT 1",
                (sym, tf),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"no {sym} {tf} signal")
        direction = _dir_from_text(row["signal"])
        # Recency: strength decays as the signal ages past its bar window.
        try:
            ts = float(row["timestamp"])
        except (TypeError, ValueError):
            ts = _now()
        bar = _TF_SECONDS.get(tf, 3600)
        age = max(0.0, _now() - ts)
        if age > SIGNAL_DROP_BARS * bar:
            return SourceReading(name, direction, 0.0, hit_rate=0.5, prior=prior,
                                 available=False,
                                 detail=f"stale {age / bar:.1f} bars old")
        strength = _clamp(1.0 - age / (SIGNAL_STALE_BARS * bar), 0.05, 1.0)
        # Empirical edge from the labelled performance table (Beta-shrunk).
        hr = 0.5
        n = 0
        try:
            from sizing import compute_stats  # local import: avoid cycle
            st = compute_stats(sym, tf, _horizon_for_tf(tf))
            n = int(getattr(st, "n", 0) or 0)
            hr = float(getattr(st, "win_rate", 0.5) or 0.5)
        except Exception:
            hr = 0.5
        hit = hr if n >= MIN_HITRATE_SAMPLES else 0.5
        side = "buy" if direction > 0 else "sell" if direction < 0 else "flat"
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"{side} {tf}, age {age / bar:.1f} bars, edge n={n}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def _read_mefai_score(base: str, tf: str) -> SourceReading:
    name = "MEFAI Score"
    prior = 1.2
    try:
        conn = _ro_connect(SKILLS_DB)
        try:
            row = conn.execute(
                "SELECT verdict, mefai_score FROM score_history "
                "WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                (base,),
            ).fetchone()
            # outcome_24h is the realized move bucket UP / DOWN / NEUTRAL.
            # Grade each row against its own verdict direction: bullish verdicts
            # win on UP, the bearish AVOID verdict wins on DOWN; NEUTRAL/WEAK
            # verdicts and NEUTRAL outcomes express no directional claim.
            agg = conn.execute(
                "SELECT "
                " SUM(CASE "
                "   WHEN verdict IN ('BUY','STRONG BUY') AND outcome_24h = 'UP' THEN 1 "
                "   WHEN verdict = 'AVOID' AND outcome_24h = 'DOWN' THEN 1 "
                "   ELSE 0 END) AS w, "
                " SUM(CASE "
                "   WHEN verdict IN ('BUY','STRONG BUY') AND outcome_24h = 'DOWN' THEN 1 "
                "   WHEN verdict = 'AVOID' AND outcome_24h = 'UP' THEN 1 "
                "   ELSE 0 END) AS l "
                "FROM score_history WHERE symbol = ? AND verified_24h = 1",
                (base,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"no {base} score")
        verdict = str(row["verdict"] or "")
        # AVOID is the bearish verdict; BUY / STRONG BUY are bullish.
        direction = -1 if verdict.upper() == "AVOID" else _dir_from_text(verdict)
        score = float(row["mefai_score"] or 50.0)
        strength = _clamp(abs(score - 50.0) / 50.0, 0.0, 1.0)
        wins = int((agg["w"] if agg else 0) or 0)
        losses = int((agg["l"] if agg else 0) or 0)
        measured = _hit_rate(wins, losses)
        hit = measured if measured is not None else 0.5
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"verdict {verdict} score {score:.0f}, w/l {wins}/{losses}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def _read_deep_composite(base: str, tf: str) -> SourceReading:
    name = "Deep Composite"
    prior = 1.3
    try:
        conn = _ro_connect(SKILLS_DB)
        try:
            row = conn.execute(
                "SELECT signal, composite_score FROM deep_signals "
                "WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                (base,),
            ).fetchone()
            agg = conn.execute(
                "SELECT "
                " SUM(CASE WHEN UPPER(outcome) = 'CORRECT' THEN 1 ELSE 0 END) AS w, "
                " SUM(CASE WHEN UPPER(outcome) = 'WRONG' THEN 1 ELSE 0 END) AS l "
                "FROM deep_signals WHERE symbol = ?",
                (base,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"no {base} deep signal")
        direction = _dir_from_text(row["signal"])
        score = float(row["composite_score"] or 50.0)
        strength = _clamp(abs(score - 50.0) / 50.0, 0.0, 1.0)
        wins = int((agg["w"] if agg else 0) or 0)
        losses = int((agg["l"] if agg else 0) or 0)
        measured = _hit_rate(wins, losses)
        hit = measured if measured is not None else 0.5
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"{row['signal']} comp {score:.0f}, w/l {wins}/{losses}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def _read_brain(base: str, tf: str) -> SourceReading:
    name = "Brain"
    prior = 0.8
    sym = f"{base}/USDT"
    try:
        conn = _ro_connect(SKILLS_DB)
        try:
            row = conn.execute(
                "SELECT signal, confidence FROM brain_predictions "
                "WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                (sym,),
            ).fetchone()
            agg = conn.execute(
                "SELECT "
                " SUM(CASE WHEN outcome = 'correct' THEN 1 ELSE 0 END) AS w, "
                " SUM(CASE WHEN outcome = 'wrong' THEN 1 ELSE 0 END) AS l, "
                " SUM(CASE WHEN outcome = 'partial' THEN 1 ELSE 0 END) AS p "
                "FROM brain_predictions WHERE symbol = ? AND verified = 1",
                (sym,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"no {sym} brain pred")
        direction = _dir_from_text(row["signal"])
        strength = _clamp(float(row["confidence"] or 0.0), 0.0, 1.0)
        w = int((agg["w"] if agg else 0) or 0)
        l = int((agg["l"] if agg else 0) or 0)
        p = int((agg["p"] if agg else 0) or 0)
        # Partial outcomes count as half a win on both sides of the ratio. Keep
        # the split fractional (no rounding) so a single partial cannot flip the
        # MIN_HITRATE_SAMPLES gate for a thin bucket.
        wins = w + 0.5 * p
        losses = l + 0.5 * p
        measured = _hit_rate(wins, losses)
        hit = measured if measured is not None else 0.5
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"{row['signal']} conf {strength:.2f}, w/l/p {w}/{l}/{p}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def _read_kronos(base: str, tf: str) -> SourceReading:
    name = "Kronos"
    prior = 1.0
    sym = f"{base}USDT"
    interval = _kronos_interval_for_tf(tf)
    try:
        conn = _ro_connect(KRONOS_DB)
        try:
            row = conn.execute(
                "SELECT direction, confidence FROM predictions "
                "WHERE symbol = ? AND interval = ? ORDER BY id DESC LIMIT 1",
                (sym, interval),
            ).fetchone()
            agg = conn.execute(
                "SELECT "
                " SUM(CASE WHEN dir_hit = 1 THEN 1 ELSE 0 END) AS w, "
                " SUM(CASE WHEN dir_hit = -1 THEN 1 ELSE 0 END) AS l "
                "FROM predictions WHERE symbol = ? AND interval = ?",
                (sym, interval),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False,
                                 detail=f"no {sym} {interval} forecast")
        direction = _dir_from_text(row["direction"])
        strength = _clamp(float(row["confidence"] or 0.0) / 100.0, 0.0, 1.0)
        wins = int((agg["w"] if agg else 0) or 0)
        losses = int((agg["l"] if agg else 0) or 0)
        measured = _hit_rate(wins, losses)
        hit = measured if measured is not None else 0.5
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"{row['direction']} conf {strength:.2f} {interval}, "
                   f"dir w/l {wins}/{losses}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def _read_cross(base: str, tf: str) -> SourceReading:
    name = "Cross Signals"
    prior = 0.6
    try:
        conn = _ro_connect(SKILLS_DB)
        try:
            rows = conn.execute(
                "SELECT direction, total_count, reliability_score "
                "FROM cross_reliability WHERE timeframe = ?",
                (tf,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"no cross rows {tf}")
        # Each cross row is a (direction, reliability) pair. Weight the
        # directional pull by reliability itself (NOT reliability-0.5): a more
        # reliable bullish cross pulls long, a reliable bearish cross pulls
        # short. The count-weighted reliability becomes this source's hit-rate,
        # so if every cross sits below a coin flip the core gives it zero skill
        # weight and it is ignored, rather than being silently inverted.
        net = 0.0          # reliability-weighted directional pull
        denom = 0.0        # total evidence weight
        rel_sum = 0.0      # count-weighted reliability (-> hit-rate)
        for r in rows:
            cnt = float(r["total_count"] or 0.0)
            rel = _clamp(float(r["reliability_score"] or 0.0), 0.0, 1.0)
            dsign = _dir_from_text(r["direction"])
            if cnt <= 0 or dsign == 0:
                continue
            net += cnt * rel * dsign
            denom += cnt
            rel_sum += cnt * rel
        if denom <= 0:
            return SourceReading(name, 0, 0.0, hit_rate=0.5, prior=prior,
                                 available=False, detail=f"empty cross {tf}")
        direction = 1 if net > 1e-9 else -1 if net < -1e-9 else 0
        # Max |net| is denom (all rows reliability 1 and same sign).
        strength = _clamp(abs(net) / denom, 0.0, 1.0)
        hit = _clamp(rel_sum / denom, 0.0, 1.0)
        return SourceReading(
            name, direction, strength, hit_rate=hit, prior=prior, available=True,
            detail=f"{len(rows)} crosses {tf}, net {net:+.0f}, rel {hit:.2f}",
        )
    except Exception as exc:
        return _err_reading(name, prior, 0.5, exc)


def gather_db_readings(symbol: str, timeframe: str) -> List[SourceReading]:
    """All DB-backed readings (no network). Each provider is self-contained and
    cannot raise out of this function."""
    base = _norm_base(symbol)
    tf = _norm_tf(timeframe)
    return [
        _read_mefai_signal(base, tf),
        _read_mefai_score(base, tf),
        _read_deep_composite(base, tf),
        _read_brain(base, tf),
        _read_kronos(base, tf),
        _read_cross(base, tf),
    ]


# --- CMC providers (async, best-effort) --------------------------------------

def _find_number(obj: Any, keys: Tuple[str, ...]) -> Optional[float]:
    """Depth-first search for the first numeric value under any of `keys`."""
    stack: List[Any] = [obj]
    seen = 0
    while stack and seen < 5000:
        cur = stack.pop()
        seen += 1
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(k, str) and k.lower() in keys:
                    try:
                        if isinstance(v, (int, float)):
                            return float(v)
                        if isinstance(v, str):
                            return float(v.strip().rstrip("%"))
                    except (TypeError, ValueError):
                        pass
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _to_float(v: Any) -> Optional[float]:
    """Parse CMC's human-formatted values: ints, floats, and strings like
    "70,897.34", "-2.04%", "2.21 T", "436.94 B"."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace(",", "")
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    mult = 1.0
    units = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    if s and s[-1] in units:
        mult = units[s[-1]]
        s = s[:-1].strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


async def _read_cmc_regime(client: Any) -> SourceReading:
    name = "CMC Regime"
    prior = 1.0
    try:
        data = await client.global_metrics_latest()
        fg = _to_float(_dig(data, "sentiment", "fear_greed", "current", "index"))
        alt = _to_float(_dig(data, "rotation", "altcoin_season", "current", "index"))
        if fg is None:
            return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                                 available=False, detail="no F&G index")
        # CMC's Fear & Greed is an explicitly CONTRARIAN gauge: extreme fear
        # (low) flags undervaluation (buy bias), extreme greed (high) flags
        # overvaluation (sell bias).
        direction = 1 if fg <= 45.0 else -1 if fg >= 55.0 else 0
        strength = _clamp(abs(fg - 50.0) / 50.0, 0.0, 1.0)
        alt_s = f", altseason {alt:.0f}" if alt is not None else ""
        return SourceReading(
            name, direction, strength, hit_rate=None, prior=prior, available=True,
            detail=f"F&G {fg:.0f} contrarian{alt_s}",
        )
    except Exception as exc:
        return _err_reading(name, prior, None, exc)


async def _resolve_cmc_id(client: Any, base: str) -> Optional[int]:
    cid = _CMC_IDS.get(base)
    if cid is not None:
        return cid
    try:
        res = await client.search_cryptos(base, limit=1)
        found = _find_number(res, ("id", "crypto_id"))
        return int(found) if found is not None else None
    except Exception:
        return None


async def _read_cmc_technicals(client: Any, base: str) -> SourceReading:
    name = "CMC Technicals"
    prior = 0.9
    try:
        cid = await _resolve_cmc_id(client, base)
        if cid is None:
            return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                                 available=False, detail=f"no CMC id for {base}")
        data = await client.technical_analysis(str(cid))
        # No single recommendation field; compose a vote from three classic
        # signals: RSI14 mean-reversion extremes, MACD histogram momentum, and
        # the short/long EMA alignment.
        votes: List[int] = []
        parts: List[str] = []
        rsi = _to_float(_dig(data, "rsi", "rsi14"))
        if rsi is not None:
            votes.append(1 if rsi <= 30 else -1 if rsi >= 70 else 0)
            parts.append(f"RSI14 {rsi:.0f}")
        hist = _to_float(_dig(data, "macd", "histogram"))
        if hist is not None:
            votes.append(1 if hist > 0 else -1 if hist < 0 else 0)
            parts.append(f"MACDh {hist:+.0f}")
        ema_s = _to_float(_dig(data, "moving_averages",
                               "exponential_moving_average_7_day"))
        ema_l = _to_float(_dig(data, "moving_averages",
                               "exponential_moving_average_30_day"))
        if ema_s is not None and ema_l is not None:
            votes.append(1 if ema_s > ema_l else -1 if ema_s < ema_l else 0)
            parts.append("EMA7>30" if ema_s > ema_l else "EMA7<30")
        if not votes:
            return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                                 available=False, detail="no TA fields")
        agg = sum(votes)
        direction = 1 if agg > 0 else -1 if agg < 0 else 0
        strength = _clamp(abs(agg) / len(votes), 0.0, 1.0)
        return SourceReading(
            name, direction, strength, hit_rate=None, prior=prior, available=True,
            detail=", ".join(parts),
        )
    except Exception as exc:
        return _err_reading(name, prior, None, exc)


async def _read_cmc_derivatives(client: Any) -> SourceReading:
    name = "CMC Derivatives"
    prior = 0.7
    try:
        data = await client.derivatives_metrics()
        funding = _to_float(_dig(data, "fundingRate", "current"))
        if funding is None:
            return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                                 available=False, detail="no funding field")
        # CMC reports the aggregate funding rate as a percent value. Contrarian
        # risk gate: crowded longs (positive funding) lean short.
        direction = -1 if funding > 0.0 else 1 if funding < 0.0 else 0
        strength = _clamp(abs(funding) / 0.05, 0.0, 1.0)  # 0.05% = full
        return SourceReading(
            name, direction, strength, hit_rate=None, prior=prior, available=True,
            detail=f"funding {funding:+.4f}% contrarian",
        )
    except Exception as exc:
        return _err_reading(name, prior, None, exc)


async def gather_cmc_readings(symbol: str) -> List[SourceReading]:
    """All CMC MCP readings (network). Returns unavailable readings if CMC keys
    are absent or the endpoint is unreachable; never raises."""
    base = _norm_base(symbol)
    try:
        from cmc_mcp import get_client
        client = await get_client()
    except Exception as exc:
        _log.warning("CMC client unavailable: %s", exc)
        return [
            SourceReading("CMC Regime", 0, 0.0, hit_rate=None, prior=1.0,
                          available=False, detail="client unavailable"),
            SourceReading("CMC Technicals", 0, 0.0, hit_rate=None, prior=0.9,
                          available=False, detail="client unavailable"),
            SourceReading("CMC Derivatives", 0, 0.0, hit_rate=None, prior=0.7,
                          available=False, detail="client unavailable"),
        ]
    regime, tech, deriv = await asyncio.gather(
        _read_cmc_regime(client),
        _read_cmc_technicals(client, base),
        _read_cmc_derivatives(client),
        return_exceptions=False,
    )
    return [regime, tech, deriv]


# --- Perpetual funding (per-asset, contrarian) -------------------------------

def funding_contrarian(funding: float, prior: float = 0.6) -> SourceReading:
    """Per-asset perpetual funding as a CONTRARIAN crowding tilt.

    When longs pay shorts (positive funding, a crowded-long book) lean SHORT;
    when shorts pay longs (negative funding, a crowded-short book) lean LONG.
    A small deadzone around the resting rate abstains so ordinary funding adds
    no noise. Gate-type source (no win/loss record): weighted by prior only.

    Pure: takes the funding fraction (8h rate, e.g. 0.0005 = 0.05%) so the
    contrarian math can be unit-tested without any network."""
    name = "Perp Funding"
    try:
        f = float(funding)
    except (TypeError, ValueError):
        return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                             available=False, detail="bad funding value")
    if not math.isfinite(f):
        return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                             available=False, detail="non-finite funding")
    mag = abs(f)
    if mag <= FUNDING_DEADZONE:
        return SourceReading(name, 0, 0.0, hit_rate=None, prior=prior,
                             available=True,
                             detail=f"funding {f * 100:+.4f}% neutral")
    direction = -1 if f > 0 else 1
    strength = _clamp((mag - FUNDING_DEADZONE) / (FUNDING_FULL - FUNDING_DEADZONE),
                      0.0, 1.0)
    side = "crowded long" if f > 0 else "crowded short"
    return SourceReading(
        name, direction, strength, hit_rate=None, prior=prior, available=True,
        detail=f"funding {f * 100:+.4f}% {side} contrarian",
    )


async def _read_perp_funding(base: str) -> SourceReading:
    """Read the per-asset perpetual funding rate from a keyless public endpoint
    and turn it into a contrarian reading. Cached briefly; never raises."""
    name = "Perp Funding"
    prior = 0.6
    sym = f"{base}USDT"
    now = _now()
    cached = _FUNDING_CACHE.get(sym)
    if cached is not None and now - cached[0] < FUNDING_TTL:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(FUNDING_URL, params={"symbol": sym})
            resp.raise_for_status()
            data = resp.json()
        reading = funding_contrarian(data.get("lastFundingRate"), prior=prior)
        _FUNDING_CACHE[sym] = (now, reading)
        return reading
    except Exception as exc:
        return _err_reading(name, prior, None, exc)


async def gather_readings(symbol: str, timeframe: str,
                          include_cmc: bool = True) -> List[SourceReading]:
    """Full fusion input: every DB source, the per-asset funding tilt, plus
    (optionally) the CMC gates.

    DB reads run in a thread so they never block the event loop; the funding
    and CMC reads run concurrently. Pass the result straight to
    fusion_core.fuse()."""
    base = _norm_base(symbol)
    db_task = asyncio.to_thread(gather_db_readings, symbol, timeframe)
    funding_task = _read_perp_funding(base)
    if include_cmc:
        db_readings, cmc_readings, funding = await asyncio.gather(
            db_task, gather_cmc_readings(symbol), funding_task
        )
        return list(db_readings) + list(cmc_readings) + [funding]
    db_readings, funding = await asyncio.gather(db_task, funding_task)
    return list(db_readings) + [funding]
