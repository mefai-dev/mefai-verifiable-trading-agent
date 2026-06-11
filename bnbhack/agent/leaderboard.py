"""
MEFAI BNB HACK · Verifiable Leaderboard + Unified Verifiable Intelligence Index

This is the Track 3 verifiable-protocol layer. It ranks MEFAI signal entities by
their VERIFIED realized outcomes (the 195k+ labeled rows in signal_performance,
each a real signal whose result was recorded after the fact) and folds every
ranked entity into one trust-scored headline number: the Unified Verifiable
Intelligence Index (UVII).

The leaderboard is the union of all skills expressed as a single trustless
ranking: each entity (a symbol, a timeframe, a signal direction, or the whole
MEFAI engine) is scored on realized PnL, directional skill, drawdown discipline,
record integrity, and liveness, then normalized to 0-100. The global UVII is the
n-weighted blend of the whole population: one number that summarizes the entire
verifiable record and updates as new outcomes are recorded.

This module is read-only and deterministic: it reads signal.db over a read-only
URI and computes pure statistics. The on-chain commit-reveal integrity and the
live uptime feed are accepted as optional inputs so the index can be tightened
once the Arena registry (A6) and the live loop (B4) are wired; until then it
falls back to data-derived proxies that are documented at each call site.

PnL and drawdown are PERCENT (a pnl of 1.0 means +1.0%). max_drawdown_pct is
recorded as a non-positive percent, so its magnitude is abs().
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

# Default verified-record database (the same store the signal pipeline writes).
DEFAULT_DB_PATH = os.getenv(
    "MEFAI_SIGNAL_DB", "data/signal.db")

# Outcome horizon per timeframe, used when horizon="auto": short frames resolve on
# the 1h mark, mid on 4h, high on 24h (the convention the TP/SL optimizer uses for
# matching a holding period to a timeframe).
_HORIZON_BY_TF = {
    "1m": ("pnl_1h", "result_1h", "1h"),
    "5m": ("pnl_1h", "result_1h", "1h"),
    "15m": ("pnl_1h", "result_1h", "1h"),
    "30m": ("pnl_1h", "result_1h", "1h"),
    "1h": ("pnl_4h", "result_4h", "4h"),
    "4h": ("pnl_24h", "result_24h", "24h"),
    "1d": ("pnl_24h", "result_24h", "24h"),
}
_DEFAULT_HORIZON = ("pnl_24h", "result_24h", "24h")

# Fixed-horizon columns. The 24h label is the canonical, near-fully-resolved
# outcome (only ~1% pending), so it is the DEFAULT for the verifiable record: the
# shorter labels mark a barrier hit WITHIN that window, leaving the majority
# "pending", which would otherwise drop most of the record from the leaderboard.
_FIXED_HORIZON = {
    "1h": ("pnl_1h", "result_1h", "1h"),
    "4h": ("pnl_4h", "result_4h", "4h"),
    "24h": ("pnl_24h", "result_24h", "24h"),
}
HORIZON_CHOICES = ("24h", "4h", "1h", "auto")
DEFAULT_HORIZON_MODE = "24h"

MIN_SAMPLES = 30

# Normalization references (the score is advisory and tunable; the underlying
# verified counts are the authoritative record).
EXP_REF_PCT = 0.5      # expectancy of +0.5% per trade maps to a full PnL score
DD_REF_PCT = 5.0       # average drawdown of 5% maps to zero discipline score
UPTIME_REF_DAYS = 3.0  # last verified outcome older than this decays uptime to 0

# Default UVII component weights (sum to 1.0).
UVII_WEIGHTS = {
    "pnl": 0.30,
    "skill": 0.25,
    "discipline": 0.20,
    "integrity": 0.15,
    "uptime": 0.10,
}
_COMPONENT_KEYS = ("pnl", "skill", "discipline", "integrity", "uptime")

_GROUP_COLS = {
    "symbol": "symbol",
    "timeframe": "timeframe",
    "signal_type": "signal_type",
}

_WIN_WORDS = {"win"}
_LOSS_WORDS = {"loss"}


def _now() -> float:
    return time.time()


def _finite(x, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(x: float, lo: float, hi: float) -> float:
    if x != x:  # NaN
        return lo
    return lo if x < lo else hi if x > hi else x


def _horizon_for_tf(tf) -> Tuple[str, str, str]:
    return _HORIZON_BY_TF.get(str(tf or "").strip().lower(), _DEFAULT_HORIZON)


def _ro_connect(db_path: str) -> sqlite3.Connection:
    # Build the read-only SQLite URI without letting the path inject query
    # parameters: a path like "...db?mode=rwc" would otherwise win the parse and
    # defeat read-only. The path is percent-encoded (slashes kept) and any URI
    # control char or explicit scheme is rejected before use.
    p = str(db_path)
    if "?" in p or "#" in p or "\n" in p or "\r" in p or p[:5].lower() == "file:":
        raise ValueError("invalid db_path")
    uri = "file:" + quote(p, safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


# --- entity statistics -----------------------------------------------------

@dataclass
class EntityStats:
    key: str                  # group value (e.g. "BTCUSDT.P", "5m", "buy", "MEFAI")
    kind: str                 # symbol / timeframe / signal_type / global
    n_total: int              # all rows for this entity
    n_resolved: int           # rows with a win/loss outcome at their horizon
    n_pending: int            # rows still pending / unlabeled
    wins: int
    losses: int
    win_rate: float           # wins / n_resolved
    expectancy: float         # mean realized pnl over resolved (percent)
    realized_pnl: float       # sum realized pnl over resolved (percent points)
    avg_drawdown: float       # mean |max_drawdown_pct| over resolved (percent)
    worst_drawdown: float     # max |max_drawdown_pct| over resolved (percent)
    brier: float              # mean (p - outcome)^2 with p = win_rate
    brier_skill: float        # directional skill vs coin-flip climatology [-1,1]
    last_entry_ts: int        # most recent entry_time seen (unix sec)


class _Acc:
    """Single-pass accumulator for one entity."""

    __slots__ = ("n_total", "n_resolved", "n_pending", "wins", "losses",
                 "sum_pnl", "sum_dd", "worst_dd", "last_ts")

    def __init__(self) -> None:
        self.n_total = 0
        self.n_resolved = 0
        self.n_pending = 0
        self.wins = 0
        self.losses = 0
        self.sum_pnl = 0.0
        self.sum_dd = 0.0
        self.worst_dd = 0.0
        self.last_ts = 0

    def add(self, pnl, result, drawdown, entry_ts) -> None:
        self.n_total += 1
        ts = int(_finite(entry_ts, 0.0))
        if ts > self.last_ts:
            self.last_ts = ts
        res = str(result or "").strip().lower()
        if res in _WIN_WORDS:
            self.wins += 1
        elif res in _LOSS_WORDS:
            self.losses += 1
        else:
            self.n_pending += 1
            return
        # resolved row
        self.n_resolved += 1
        self.sum_pnl += _finite(pnl, 0.0)
        dd = abs(_finite(drawdown, 0.0))
        self.sum_dd += dd
        if dd > self.worst_dd:
            self.worst_dd = dd

    def finalize(self, key: str, kind: str) -> EntityStats:
        n = self.n_resolved
        win_rate = (self.wins / n) if n > 0 else 0.0
        expectancy = (self.sum_pnl / n) if n > 0 else 0.0
        avg_dd = (self.sum_dd / n) if n > 0 else 0.0
        # Brier with the entity's win-rate as the (best constant) forecast. With a
        # constant forecast this reduces to win_rate*(1-win_rate); it is written
        # per-trade so it generalizes if per-signal probabilities are added later.
        p = win_rate
        brier = p * (1.0 - p)
        # Directional skill vs a coin-flip climatology (Brier reference 0.25):
        # 1 - brier/0.25 = (2p-1)^2, signed by which side of the flip we land on.
        edge = 2.0 * p - 1.0
        brier_skill = math.copysign(edge * edge, edge) if n > 0 else 0.0
        return EntityStats(
            key=key, kind=kind, n_total=self.n_total, n_resolved=n,
            n_pending=self.n_pending, wins=self.wins, losses=self.losses,
            win_rate=win_rate, expectancy=expectancy, realized_pnl=self.sum_pnl,
            avg_drawdown=avg_dd, worst_drawdown=self.worst_dd,
            brier=brier, brier_skill=_clamp(brier_skill, -1.0, 1.0),
            last_entry_ts=self.last_ts,
        )


def _fetch_rows(conn: sqlite3.Connection, since_ts: Optional[int],
                group_col: Optional[str], until_ts: Optional[int] = None):
    """Yield (group_value, timeframe, pnl_1h, pnl_4h, pnl_24h, result_1h,
    result_4h, result_24h, max_drawdown_pct, entry_time) for completed rows.

    since_ts is an inclusive entry_time floor; until_ts is an exclusive ceiling.
    Together they bound a half-open [since_ts, until_ts) window, which lets a
    caller rank on a train window and measure on a disjoint holdout window.
    """
    cols = ["timeframe", "pnl_1h", "pnl_4h", "pnl_24h",
            "result_1h", "result_4h", "result_24h",
            "max_drawdown_pct", "entry_time"]
    select_cols = ([group_col] if group_col else []) + cols
    sql = f"SELECT {', '.join(select_cols)} FROM signal_performance"
    params: List = []
    where: List[str] = []
    if since_ts is not None:
        where.append("entry_time >= ?")
        params.append(int(since_ts))
    if until_ts is not None:
        where.append("entry_time < ?")
        params.append(int(until_ts))
    if where:
        sql += " WHERE " + " AND ".join(where)
    return conn.execute(sql, params)


def _row_outcome(row, base: int, horizon_mode: str) -> Tuple[float, str, float, int, str]:
    """Pull the horizon pnl + result for one row. base is the index of the
    timeframe column in the row tuple. horizon_mode is one of HORIZON_CHOICES:
    a fixed window ("24h"/"4h"/"1h") or "auto" (per-timeframe)."""
    tf = row[base]
    if horizon_mode == "auto":
        pnl_col, result_col, _label = _horizon_for_tf(tf)
    else:
        pnl_col, result_col, _label = _FIXED_HORIZON.get(
            horizon_mode, _DEFAULT_HORIZON)
    idx = {"pnl_1h": base + 1, "pnl_4h": base + 2, "pnl_24h": base + 3,
           "result_1h": base + 4, "result_4h": base + 5, "result_24h": base + 6}
    pnl = row[idx[pnl_col]]
    result = row[idx[result_col]]
    drawdown = row[base + 7]
    entry_ts = row[base + 8]
    return pnl, result, drawdown, entry_ts, str(tf)


@dataclass
class Leaderboard:
    group_by: str
    horizon: str                    # outcome window used (24h / 4h / 1h / auto)
    since_ts: Optional[int]
    until_ts: Optional[int]         # exclusive entry_time ceiling (None = open)
    min_samples: int
    entries: List[EntityStats]      # ranked, only those meeting min_samples
    below_threshold: int            # entities dropped for too few samples
    overall: EntityStats            # the single global entity over the whole set
    ts: float = field(default_factory=_now)


_RANK_KEYS = {
    "pnl": lambda e: e.realized_pnl,
    "expectancy": lambda e: e.expectancy,
    "win_rate": lambda e: e.win_rate,
    "skill": lambda e: e.brier_skill,
}


def build_leaderboard(group_by: str = "symbol", since_ts: Optional[int] = None,
                      min_samples: int = MIN_SAMPLES, rank_by: str = "expectancy",
                      horizon: str = DEFAULT_HORIZON_MODE,
                      db_path: str = DEFAULT_DB_PATH,
                      until_ts: Optional[int] = None) -> Leaderboard:
    """Rank entities of one kind by their verified outcomes.

    group_by: symbol | timeframe | signal_type
    rank_by:  expectancy | pnl | win_rate | skill
    horizon:  24h | 4h | 1h | auto (per-timeframe). Default 24h is the canonical
              near-fully-resolved outcome window.
    since_ts: only count signals entered at or after this unix second (the live
              forward window the judges watch); None = whole record.
    until_ts: exclusive entry_time ceiling; with since_ts it bounds a half-open
              [since_ts, until_ts) window so a caller can rank on a train window
              and score on a disjoint holdout. None = no ceiling.
    """
    group_col = _GROUP_COLS.get(group_by)
    if group_col is None:
        raise ValueError(f"unsupported group_by: {group_by!r}")
    if horizon not in HORIZON_CHOICES:
        raise ValueError(f"unsupported horizon: {horizon!r}")
    rank_fn = _RANK_KEYS.get(rank_by)
    if rank_fn is None:
        raise ValueError(f"unsupported rank_by: {rank_by!r}")
    try:
        min_samples = max(1, int(min_samples))
    except (TypeError, ValueError, OverflowError):
        min_samples = MIN_SAMPLES

    accs: Dict[str, _Acc] = {}
    overall = _Acc()
    conn = _ro_connect(db_path)
    try:
        for row in _fetch_rows(conn, since_ts, group_col, until_ts):
            gval = str(row[0])
            pnl, result, drawdown, entry_ts, _tf = _row_outcome(row, 1, horizon)
            acc = accs.get(gval)
            if acc is None:
                acc = accs[gval] = _Acc()
            acc.add(pnl, result, drawdown, entry_ts)
            overall.add(pnl, result, drawdown, entry_ts)
    finally:
        conn.close()

    stats = [acc.finalize(k, group_by) for k, acc in accs.items()]
    qualified = [s for s in stats if s.n_resolved >= min_samples]
    below = len(stats) - len(qualified)
    # Deterministic order: primary rank metric, then sample count, then key, so
    # ties resolve identically regardless of DB row order or rewrites.
    qualified.sort(key=lambda e: (rank_fn(e), e.n_resolved, e.key), reverse=True)
    return Leaderboard(
        group_by=group_by, horizon=horizon, since_ts=since_ts, until_ts=until_ts,
        min_samples=min_samples, entries=qualified, below_threshold=below,
        overall=overall.finalize("MEFAI", "global"),
    )


# --- recent verified signals (cockpit "entered trades + results") ----------

@dataclass
class ResolvedSignal:
    symbol: str           # e.g. "BTCUSDT.P"
    timeframe: str
    direction: str        # long / short (normalized from buy / sell)
    entry_price: float
    entry_time: int       # unix sec
    pnl: float            # realized pnl at the horizon, percent (1.0 = +1.0%)
    result: str           # win / loss
    drawdown: float       # |max_drawdown_pct|, percent
    max_profit: float     # max_profit_pct reached, percent
    horizon: str          # outcome window the result was read at (e.g. "24h")


_DIRECTION = {"buy": "long", "sell": "short", "long": "long", "short": "short"}


def recent_resolved(limit: int = 20, symbols: Optional[List[str]] = None,
                    timeframe: Optional[str] = None,
                    horizon: str = DEFAULT_HORIZON_MODE,
                    db_path: str = DEFAULT_DB_PATH) -> List[ResolvedSignal]:
    """Most recent VERIFIED MEFAI signals paired with their realized outcome.

    Each row is a real signal whose win/loss was recorded after the fact (the
    same signal_performance record the leaderboard ranks). It powers the cockpit
    view of "the trades the agent would enter, and how they resolved". Read-only
    and deterministic: newest entries first, only rows resolved at the horizon.
    """
    if horizon not in HORIZON_CHOICES:
        raise ValueError(f"unsupported horizon: {horizon!r}")
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError, OverflowError):
        limit = 20

    # Normalize the optional symbol filter into the canonical "<SYM>.P" form the
    # record stores, accepting either the bare or suffixed shape from callers.
    sym_set: Optional[set] = None
    if symbols:
        sym_set = set()
        for s in symbols:
            u = str(s or "").strip().upper()
            if not u:
                continue
            sym_set.add(u)
            sym_set.add(u if u.endswith(".P") else u + ".P")
    tf_norm = str(timeframe).strip().lower() if timeframe else None

    # Layout matches _row_outcome (symbol at 0, timeframe at base=1, then the
    # fixed pnl/result/drawdown/entry block); the extra fields are appended so
    # _row_outcome's positional reads stay valid.
    cols = ["symbol", "timeframe", "pnl_1h", "pnl_4h", "pnl_24h",
            "result_1h", "result_4h", "result_24h",
            "max_drawdown_pct", "entry_time",
            "signal_type", "entry_price", "max_profit_pct"]
    sql = (f"SELECT {', '.join(cols)} FROM signal_performance "
           "WHERE entry_time IS NOT NULL ORDER BY entry_time DESC")
    # Bound the scan so a sparse filter can never walk the whole 195k+ record.
    scan_cap = limit * 200 + 2000

    out: List[ResolvedSignal] = []
    conn = _ro_connect(db_path)
    try:
        cur = conn.execute(sql)
        scanned = 0
        for row in cur:
            scanned += 1
            if scanned > scan_cap:
                break
            symbol = str(row[0])
            if sym_set is not None and symbol.upper() not in sym_set:
                continue
            tf = str(row[1] or "")
            if tf_norm is not None and tf.lower() != tf_norm:
                continue
            # _row_outcome expects the timeframe at `base` then the pnl/result
            # columns in fixed order; here base = 1 (symbol at 0). Its 5th value
            # is the row's timeframe, so derive the outcome window separately.
            pnl, result, drawdown, entry_ts, _tf = _row_outcome(row, 1, horizon)
            res = str(result or "").strip().lower()
            if res not in _WIN_WORDS and res not in _LOSS_WORDS:
                continue
            label = (_horizon_for_tf(tf)[2] if horizon == "auto"
                     else _FIXED_HORIZON.get(horizon, _DEFAULT_HORIZON)[2])
            out.append(ResolvedSignal(
                symbol=symbol, timeframe=tf,
                direction=_DIRECTION.get(str(row[10] or "").strip().lower(), "long"),
                entry_price=_finite(row[11], 0.0), entry_time=int(_finite(entry_ts, 0.0)),
                pnl=_finite(pnl, 0.0), result=res,
                drawdown=abs(_finite(drawdown, 0.0)),
                max_profit=abs(_finite(row[12], 0.0)), horizon=label,
            ))
            if len(out) >= limit:
                break
    finally:
        conn.close()
    return out


# --- Unified Verifiable Intelligence Index ---------------------------------

@dataclass
class UVII:
    key: str
    kind: str
    score: float              # composite 0-100
    pnl_score: float
    skill_score: float
    discipline_score: float
    integrity_score: float
    uptime_score: float
    weights: Dict[str, float]
    n_resolved: int
    lineage: Dict[str, float] = field(default_factory=dict)


def _pnl_score(expectancy: float) -> float:
    # +EXP_REF_PCT -> 100, 0 -> 50, -EXP_REF_PCT -> 0.
    return 50.0 + 50.0 * _clamp(expectancy / EXP_REF_PCT, -1.0, 1.0)


def _skill_score(win_rate: float) -> float:
    # Linear in the directional edge: win_rate 0.5 -> 50, 1.0 -> 100, 0 -> 0.
    return _clamp(win_rate * 100.0, 0.0, 100.0)


def _discipline_score(avg_drawdown: float) -> float:
    # 0% average drawdown -> 100, DD_REF_PCT -> 0.
    return 100.0 * _clamp(1.0 - avg_drawdown / DD_REF_PCT, 0.0, 1.0)


def _integrity_default(stats: EntityStats) -> float:
    # Until the Arena commit-reveal proof is wired (A6), integrity is proxied by
    # the share of claimed signals that carry a verified, recorded outcome: a
    # record that resolves its own claims is harder to backfill or cherry-pick.
    if stats.n_total <= 0:
        return 0.0
    return 100.0 * _clamp(stats.n_resolved / stats.n_total, 0.0, 1.0)


def _uptime_default(stats: EntityStats, now: Optional[float]) -> float:
    # Liveness proxy: how recent the latest verified outcome is. The live loop
    # (B4) can supply a measured uptime instead.
    if stats.last_entry_ts <= 0:
        return 0.0
    now_s = _now() if now is None else now
    days = (now_s - stats.last_entry_ts) / 86400.0
    return 100.0 * _clamp(1.0 - days / UPTIME_REF_DAYS, 0.0, 1.0)


def compute_uvii(stats: EntityStats,
                 integrity: Optional[float] = None,
                 uptime: Optional[float] = None,
                 weights: Optional[Dict[str, float]] = None,
                 now: Optional[float] = None) -> UVII:
    """Fold one entity's verified statistics into a single 0-100 trust score.

    integrity / uptime override the data-derived defaults (used once on-chain
    proofs and a live uptime feed exist). weights override UVII_WEIGHTS; they are
    renormalized so the score stays on a 0-100 scale even if they do not sum to 1.
    """
    # Restrict to the known component keys so unknown/typo keys neither inflate
    # the normalizer (deflating the score) nor get echoed back. Negative or
    # non-finite weights are floored to 0; an all-zero set falls back to the
    # defaults rather than producing a misleading 0 score.
    raw = UVII_WEIGHTS if weights is None else weights
    w = {k: max(0.0, _finite(raw.get(k, 0.0), 0.0)) for k in _COMPONENT_KEYS}
    total_w = sum(w.values())
    if total_w <= 0.0:
        w = dict(UVII_WEIGHTS)
        total_w = sum(w.values())

    pnl_s = _pnl_score(stats.expectancy)
    skill_s = _skill_score(stats.win_rate)
    disc_s = _discipline_score(stats.avg_drawdown)
    integ_s = _integrity_default(stats) if integrity is None \
        else _clamp(_finite(integrity, 0.0), 0.0, 100.0)
    up_s = _uptime_default(stats, now) if uptime is None \
        else _clamp(_finite(uptime, 0.0), 0.0, 100.0)

    parts = {"pnl": pnl_s, "skill": skill_s, "discipline": disc_s,
             "integrity": integ_s, "uptime": up_s}
    score = sum(parts[k] * w[k] for k in _COMPONENT_KEYS) / total_w
    return UVII(
        key=stats.key, kind=stats.kind, score=_clamp(score, 0.0, 100.0),
        pnl_score=pnl_s, skill_score=skill_s, discipline_score=disc_s,
        integrity_score=integ_s, uptime_score=up_s,
        weights={k: w[k] / total_w for k in _COMPONENT_KEYS},
        n_resolved=stats.n_resolved,
        lineage={
            "win_rate": stats.win_rate, "expectancy": stats.expectancy,
            "realized_pnl": stats.realized_pnl, "avg_drawdown": stats.avg_drawdown,
            "brier": stats.brier, "brier_skill": stats.brier_skill,
        },
    )


@dataclass
class UVIIIndex:
    """The leaderboard of entity UVII scores plus the single global MEFAI index."""
    group_by: str
    horizon: str
    since_ts: Optional[int]
    entities: List[UVII]      # ranked by composite score desc
    global_index: UVII        # the one headline number over the whole record
    ts: float = field(default_factory=_now)


def build_uvii_index(group_by: str = "symbol", since_ts: Optional[int] = None,
                     min_samples: int = MIN_SAMPLES,
                     horizon: str = DEFAULT_HORIZON_MODE,
                     weights: Optional[Dict[str, float]] = None,
                     integrity: Optional[float] = None,
                     uptime: Optional[float] = None,
                     db_path: str = DEFAULT_DB_PATH) -> UVIIIndex:
    """The union of all skills as one verifiable index: a UVII per entity plus a
    single global MEFAI UVII over the entire verified record.

    integrity / uptime, when given, are applied to the GLOBAL index (the on-chain
    proof and live-feed inputs describe the protocol as a whole); per-entity
    scores use the data-derived defaults.
    """
    lb = build_leaderboard(group_by=group_by, since_ts=since_ts,
                           min_samples=min_samples, horizon=horizon,
                           db_path=db_path)
    # Pin one timestamp so the wall-clock uptime proxy (and thus every score) is
    # identical across the whole index and reproducible for a given DB snapshot.
    now = _now()
    entities = [compute_uvii(s, weights=weights, now=now) for s in lb.entries]
    entities.sort(key=lambda u: (u.score, u.n_resolved, u.key), reverse=True)
    global_index = compute_uvii(lb.overall, integrity=integrity, uptime=uptime,
                                weights=weights, now=now)
    return UVIIIndex(group_by=group_by, horizon=horizon, since_ts=since_ts,
                     entities=entities, global_index=global_index)
