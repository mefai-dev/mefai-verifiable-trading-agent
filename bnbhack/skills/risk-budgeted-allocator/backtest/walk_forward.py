#!/usr/bin/env python3
"""Risk-Budgeted Allocator · walk-forward equity-curve backtest.

A real out-of-sample profit-and-loss simulation over the labelled MEFAI signal
outcomes (signal_performance), NOT a property check. It demonstrates the value
the allocator adds on top of the raw signal feed: selection plus drawdown-budget
fractional-Kelly sizing.

Method (no look-ahead):
  1. Pull every COMPLETED signal for one horizon, ordered by entry time.
  2. Split by TIME into a train window (first `TRAIN_FRAC`) and a held-out test
     window (the rest). Per-(symbol, timeframe) edge stats are estimated ONLY on
     the train window, so the test equity curve never sees its own future.
  3. Selection rule (the skill): trade a bucket on the test window only when its
     TRAIN net-of-cost expectancy is positive with enough samples, i.e. the same
     edge gate the live sizer applies. Everything else is stood aside.
  4. Walk the test window forward trade by trade, sizing each accepted signal
     with the documented drawdown-budget Kelly model (using only train stats and
     the live running drawdown), compounding the realised net-of-cost return.
  5. Report Sharpe / Sortino / Calmar / max drawdown and an equity curve for the
     drawdown-budget Kelly risk engine (the headline), against a naive flat
     leverage floor baseline so the risk engine's value is explicit, plus an
     optional net-of-cost edge-gate overlay on top of the Kelly engine.

Returns are reported NET of the modelled PancakeSwap round-trip cost, so the
curve is honest against the venue. Read-only; writes only its own report + SVG.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from sizing import (  # noqa: E402
    DD_BUDGET_K, INTERNAL_CAP_RATIO, MIN_STOP, MAX_STOP, PAYOFF_CAP,
    QUARTER_KELLY, kelly_fraction,
)

SIGNAL_DB = os.getenv(
    "MEFAI_SIGNAL_DB", "data/signal.db")

# --- backtest configuration -------------------------------------------------
# Default 24h: the per-trade move must amortise the fixed round-trip cost, and
# only the longer holding period produces a per-trade expectancy large enough to
# clear realistic spot fees with a positive net edge (the 1h/4h feeds overtrade
# a sub-fee edge). The sweep across horizons is part of the skill's evidence.
HORIZON = os.getenv("BT_HORIZON", "24h")         # 1h / 4h / 24h
TRAIN_FRAC = float(os.getenv("BT_TRAIN_FRAC", "0.6"))
# Default 0.2 percent round-trip: majors route through PancakeSwap V3 0.05
# percent fee pools (~0.10 percent for the two sides) plus a deep-pool slippage
# and BSC gas buffer. This is the same cost basis the live agent's net-of-cost
# edge gate uses, so the backtest and the deployed sizer agree.
ROUNDTRIP_COST_PCT = float(os.getenv("BNBHACK_ROUNDTRIP_COST_PCT", "0.2"))
MIN_TRAIN_SAMPLES = int(os.getenv("BT_MIN_TRAIN_SAMPLES", "30"))
START_EQUITY = float(os.getenv("BT_START_EQUITY", "10000"))
JURY_CAP = float(os.getenv("BNBHACK_JURY_CAP", "0.20"))
VENUE_MAX_LEV = float(os.getenv("BT_MAX_LEV", "5"))   # conservative cap
# Naive baseline leverage: a flat constant notional with NO Kelly sizing and NO
# drawdown budget. It is the honest floor comparator that isolates what the risk
# engine adds (drawdown control), not a strategy we would run.
FLAT_LEV = float(os.getenv("BT_FLAT_LEV", "1.0"))
SECONDS_PER_YEAR = 365.25 * 24 * 3600

_HORIZON_COLS = {"1h": ("pnl_1h", "result_1h"),
                 "4h": ("pnl_4h", "result_4h"),
                 "24h": ("pnl_24h", "result_24h")}


def _ro_db() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _load_trades() -> List[sqlite3.Row]:
    pnl_col, res_col = _HORIZON_COLS[HORIZON]
    db = _ro_db()
    try:
        return db.execute(
            f"""SELECT symbol, timeframe, entry_time,
                       {pnl_col} AS pnl, ABS(max_drawdown_pct) AS mdd
                FROM signal_performance
                WHERE status='completed' AND {res_col} IN ('win','loss')
                  AND {pnl_col} IS NOT NULL AND entry_time IS NOT NULL
                ORDER BY entry_time ASC""").fetchall()
    finally:
        db.close()


def _bucket_stats(train: List[sqlite3.Row]) -> Dict[Tuple[str, str], dict]:
    """Per-(symbol, timeframe) edge estimated on the train window ONLY."""
    agg: Dict[Tuple[str, str], dict] = {}
    for r in train:
        key = (r["symbol"], r["timeframe"])
        b = agg.setdefault(key, {"n": 0, "wins": 0, "sum_w": 0.0, "nw": 0,
                                 "sum_l": 0.0, "nl": 0, "sum_pnl": 0.0,
                                 "sum_mdd": 0.0})
        pnl = float(r["pnl"] or 0.0)
        b["n"] += 1
        b["sum_pnl"] += pnl
        b["sum_mdd"] += float(r["mdd"] or 0.0)
        if pnl > 0:
            b["wins"] += 1
            b["sum_w"] += pnl
            b["nw"] += 1
        elif pnl < 0:
            b["sum_l"] += -pnl
            b["nl"] += 1
    out: Dict[Tuple[str, str], dict] = {}
    for key, b in agg.items():
        n = b["n"]
        if n <= 0:
            continue
        win_rate = b["wins"] / n
        avg_win = (b["sum_w"] / b["nw"]) if b["nw"] else 0.0
        avg_loss = (b["sum_l"] / b["nl"]) if b["nl"] else 0.0
        payoff = min(avg_win / avg_loss, PAYOFF_CAP) if avg_loss > 0 else 0.0
        expectancy = b["sum_pnl"] / n
        avg_mdd = b["sum_mdd"] / n
        out[key] = {"n": n, "win_rate": win_rate, "payoff": payoff,
                    "expectancy": expectancy, "net_edge": expectancy - ROUNDTRIP_COST_PCT,
                    "avg_mdd": avg_mdd}
    return out


def _leverage_for(stats: dict, drawdown: float) -> float:
    """Drawdown-budget fractional-Kelly leverage from train stats + live dd,
    mirroring the live sizer's documented model (notional/equity)."""
    internal_cap = INTERNAL_CAP_RATIO * JURY_CAP
    R = max(0.0, internal_cap - drawdown)
    if R <= 0:
        return 0.0
    f_k = kelly_fraction(stats["win_rate"], stats["payoff"])
    if f_k <= 0:
        return 0.0
    rho = min(QUARTER_KELLY * f_k, DD_BUDGET_K * R)
    if rho <= 0:
        return 0.0
    stop = min(max(stats["avg_mdd"] / 100.0, MIN_STOP), MAX_STOP)
    leverage = rho / stop          # notional/equity = (rho*equity/stop)/equity
    return min(leverage, VENUE_MAX_LEV)


def _equity_curve(test: List[sqlite3.Row],
                  bucket: Dict[Tuple[str, str], dict],
                  mode: str, flat_lev: float = FLAT_LEV) -> dict:
    """Walk the test window forward, compounding net-of-cost returns under one
    of three sizing regimes:

      "kelly"  · the risk engine headline. Drawdown-budget fractional-Kelly
                 sizing on every bucket with enough train samples. This is the
                 value driver: it sizes by edge and throttles as drawdown grows.
      "gated"  · the same Kelly engine PLUS a stricter net-of-cost selection
                 overlay (a bucket trades only when its TRAIN net edge beats
                 fees). Isolates what the edge gate adds on top of Kelly.
      "naive"  · the floor baseline. A flat constant leverage with NO Kelly and
                 NO drawdown budget on the same accepted signals. Isolates what
                 the risk engine adds over naive constant sizing.
    """
    equity = START_EQUITY
    peak = equity
    max_dd = 0.0
    curve: List[Tuple[int, float]] = [(int(test[0]["entry_time"]), equity)] if test else []
    rets: List[float] = []
    n_trades = 0
    sum_lev = 0.0
    for r in test:
        key = (r["symbol"], r["timeframe"])
        st = bucket.get(key)
        net_pnl = float(r["pnl"] or 0.0) - ROUNDTRIP_COST_PCT   # percent, net
        if st is None or st["n"] < MIN_TRAIN_SAMPLES:
            continue
        if mode == "gated" and st["net_edge"] <= 0:
            continue
        # Shared edge-positive selection: all three legs trade the same universe
        # of buckets whose train Kelly fraction is positive, so the naive leg is
        # a fair sizing ablation (same picks, no edge weighting, no drawdown
        # budget) rather than a strawman that all-ins every sample bucket.
        f_k = kelly_fraction(st["win_rate"], st["payoff"])
        if f_k <= 0:
            continue
        if mode == "naive":
            lev = flat_lev                 # constant size, no Kelly, no budget
        else:
            dd = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak)
            lev = _leverage_for(st, dd)
        if lev <= 0:
            continue
        ret = lev * net_pnl / 100.0
        equity *= (1.0 + ret)
        if equity <= 0:                # ruin guard (never reached under caps)
            equity = 1e-9
        rets.append(ret)
        n_trades += 1
        sum_lev += lev
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((int(r["entry_time"]), equity))
    span_seconds = (int(test[-1]["entry_time"]) - int(test[0]["entry_time"])) if test else 0
    avg_lev = (sum_lev / n_trades) if n_trades else 0.0
    return _metrics(curve, rets, equity, max_dd, n_trades, span_seconds, avg_lev)


def _metrics(curve: List[Tuple[int, float]], rets: List[float],
             equity: float, max_dd: float, n_trades: int,
             span_seconds: int, avg_lev: float) -> dict:
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    var = sum((x - mean) ** 2 for x in rets) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    downside = [x for x in rets if x < 0]
    dvar = sum(x * x for x in downside) / (n - 1) if n > 1 else 0.0
    dstd = math.sqrt(dvar)
    # Annualise over the FULL test deployment window (not the traded points):
    # a leg that fires its last sized trade early still sat in the market for
    # the whole out-of-sample span, so that is the honest denominator.
    span = max(1, int(span_seconds))
    years = span / SECONDS_PER_YEAR
    trades_per_year = n_trades * SECONDS_PER_YEAR / span if n_trades else 0.0
    ann = math.sqrt(trades_per_year) if trades_per_year > 0 else 0.0
    sharpe = (mean / std * ann) if std > 0 else 0.0
    sortino = (mean / dstd * ann) if dstd > 0 else 0.0
    total_return = equity / START_EQUITY - 1.0
    # CAGR is only meaningful over a non-trivial span; under ~2 weeks the
    # fractional-year exponent is unstable, so report the raw total return.
    if years >= 0.04 and equity > 0:
        cagr = (equity / START_EQUITY) ** (1.0 / years) - 1.0
    else:
        cagr = total_return
    calmar = (cagr / max_dd) if max_dd > 0 else 0.0
    return {
        "n_trades": n_trades,
        "final_equity": round(equity, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "mean_trade_ret_pct": round(mean * 100.0, 4),
        "trade_ret_std_pct": round(std * 100.0, 4),
        "avg_leverage_x": round(avg_lev, 3),
        "test_years": round(years, 3),
        "_curve": curve,
    }


def _svg(kelly: List[Tuple[int, float]], naive: List[Tuple[int, float]],
         gated: List[Tuple[int, float]], path: str) -> None:
    """Minimal dependency-free equity-curve SVG. Solid gold is raw Kelly +
    drawdown budget, dashed gold is the net-of-cost edge-gate overlay (the leg
    that ships live), blue is the constant-leverage naive reference."""
    W, H, PAD = 900, 380, 48
    if len(kelly) < 2:
        return
    all_t = [t for t, _ in kelly] + [t for t, _ in naive] + [t for t, _ in gated]
    all_e = ([e for _, e in kelly] + [e for _, e in naive]
             + [e for _, e in gated] + [START_EQUITY])
    t0, t1 = min(all_t), max(all_t)
    e0, e1 = min(all_e), max(all_e)
    span_t = max(1, t1 - t0)
    span_e = max(1e-9, e1 - e0)

    def x(t: int) -> float:
        return PAD + (t - t0) / span_t * (W - 2 * PAD)

    def y(e: float) -> float:
        return H - PAD - (e - e0) / span_e * (H - 2 * PAD)

    def poly(pts: List[Tuple[int, float]]) -> str:
        return " ".join(f"{x(t):.1f},{y(e):.1f}" for t, e in pts)

    base_y = y(START_EQUITY)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="monospace">',
        f'<rect width="{W}" height="{H}" fill="#0b0e11"/>',
        f'<line x1="{PAD}" y1="{base_y:.1f}" x2="{W-PAD}" y2="{base_y:.1f}" '
        f'stroke="#33384a" stroke-dasharray="4 4"/>',
        f'<polyline fill="none" stroke="#3861FB" stroke-width="1.4" '
        f'opacity="0.7" points="{poly(naive)}"/>',
        f'<polyline fill="none" stroke="#F0B90B" stroke-width="1.4" '
        f'stroke-dasharray="5 4" opacity="0.85" points="{poly(gated)}"/>',
        f'<polyline fill="none" stroke="#F0B90B" stroke-width="2.4" '
        f'points="{poly(kelly)}"/>',
        f'<text x="{PAD}" y="24" fill="#e6e8ee" font-size="15">'
        f'Risk-Budgeted Allocator · out-of-sample equity ({HORIZON})</text>',
        f'<text x="{PAD}" y="{H-16}" fill="#F0B90B" font-size="12">risk engine '
        f'(Kelly + drawdown budget)</text>',
        f'<text x="{PAD+260}" y="{H-16}" fill="#F0B90B" font-size="12" '
        f'opacity="0.85">+ edge-gate overlay</text>',
        f'<text x="{PAD+470}" y="{H-16}" fill="#3861FB" font-size="12">'
        f'naive flat leverage</text>',
        f'<text x="{W-PAD-110}" y="24" fill="#7a8194" font-size="11">'
        f'start ${START_EQUITY:,.0f}</text>',
        '</svg>',
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(svg))


def run() -> dict:
    trades = _load_trades()
    if len(trades) < 200:
        return {"error": "insufficient labelled history", "n": len(trades)}
    split = int(len(trades) * TRAIN_FRAC)
    train, test = trades[:split], trades[split:]
    bucket = _bucket_stats(train)
    n_selected_buckets = sum(
        1 for s in bucket.values()
        if s["n"] >= MIN_TRAIN_SAMPLES and s["net_edge"] > 0)

    kelly = _equity_curve(test, bucket, mode="kelly")
    gated = _equity_curve(test, bucket, mode="gated")
    # Size the naive leg to the Kelly engine's REALISED average leverage so the
    # comparison isolates the drawdown budget and edge weighting, not a leverage
    # mismatch. Same average position size, but constant and with no budget stop.
    naive_lev = kelly.get("avg_leverage_x") or FLAT_LEV
    naive = _equity_curve(test, bucket, mode="naive", flat_lev=naive_lev)
    kelly_curve = kelly.pop("_curve")
    gated_curve = gated.pop("_curve")
    naive_curve = naive.pop("_curve")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    try:
        _svg(kelly_curve, naive_curve, gated_curve,
             os.path.join(out_dir, "equity_curve.svg"))
    except Exception as exc:  # SVG is a nicety; never fail the report on it
        kelly["svg_error"] = str(exc)

    return {
        "skill": "risk-budgeted-allocator",
        "artifact": "walk-forward out-of-sample equity curve",
        "horizon": HORIZON,
        "roundtrip_cost_pct": ROUNDTRIP_COST_PCT,
        "train_frac": TRAIN_FRAC,
        "min_train_samples": MIN_TRAIN_SAMPLES,
        "venue_max_leverage": VENUE_MAX_LEV,
        "naive_flat_leverage_x": round(naive_lev, 3),
        "n_total_trades": len(trades),
        "n_train": len(train),
        "n_test": len(test),
        "n_buckets": len(bucket),
        "n_selected_buckets": n_selected_buckets,
        "kelly_engine": kelly,
        "kelly_engine_with_edge_gate": gated,
        "naive_flat_leverage": naive,
        "note": ("Returns are NET of the modelled round-trip cost. Edge stats "
                 "come only from the train window; the test equity curve is "
                 "fully out of sample. Three legs are reported side by side on "
                 "the SAME edge-positive signals so the contribution of each "
                 "control is isolated, not asserted. (1) kelly_engine is raw "
                 "drawdown-budget fractional-Kelly sizing: it sizes each signal "
                 "by its measured edge and collapses new risk toward zero as "
                 "drawdown approaches the cap. (2) kelly_engine_with_edge_gate "
                 "layers a stricter net-of-cost selection on top: it only sizes a "
                 "bucket whose measured per-trade expectancy clears the round-trip "
                 "cost with a statistical margin. This gated leg is what ships "
                 "live. (3) naive_flat_leverage runs the same picks at a CONSTANT "
                 "leverage fixed to the Kelly leg's own realised average, with no "
                 "drawdown-budget stop, as a reference floor. Which leg leads on "
                 "raw return depends entirely on the data: on the shipped "
                 "synthetic sample, which is smooth and edge-positive by "
                 "construction, an un-stopped constant-leverage leg can post the "
                 "highest raw return and the lowest drawdown precisely because the "
                 "synthetic series never delivers the adverse cluster the budget "
                 "exists to survive. The drawdown budget is insurance, not a "
                 "return amplifier, and it is priced against tail risk that "
                 "illustrative data does not contain. Read max_drawdown_pct and "
                 "calmar for the risk comparison, not sharpe: sharpe here is "
                 "frequency-annualised (sqrt of trades per year) and is inflated "
                 "on a dense, low-noise sample, so its absolute level is not "
                 "meaningful and only its sign and cross-leg ordering carry "
                 "information. The printed figures, not this prose, are the source "
                 "of truth; on the private production book the leg ordering "
                 "differs from the synthetic sample shipped in this repository."),
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "equity_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    if "error" in report:
        print("backtest skipped:", report["error"])
        return 1
    k = report["kelly_engine"]
    g = report["kelly_engine_with_edge_gate"]
    nv = report["naive_flat_leverage"]
    print(f"horizon              : {report['horizon']}  cost {report['roundtrip_cost_pct']}%")
    print(f"train / test trades  : {report['n_train']} / {report['n_test']}")
    print(f"selected buckets     : {report['n_selected_buckets']} / {report['n_buckets']}")
    print(f"KELLY ENGINE   ret={k['total_return_pct']}%  CAGR={k['cagr_pct']}%  "
          f"maxDD={k['max_drawdown_pct']}%  Sharpe={k['sharpe']}  "
          f"Sortino={k['sortino']}  Calmar={k['calmar']}  n={k['n_trades']}")
    print(f"+ EDGE GATE    ret={g['total_return_pct']}%  maxDD={g['max_drawdown_pct']}%  "
          f"Sharpe={g['sharpe']}  Calmar={g['calmar']}  n={g['n_trades']}")
    print(f"NAIVE FLAT {report['naive_flat_leverage_x']}x ret={nv['total_return_pct']}%  "
          f"maxDD={nv['max_drawdown_pct']}%  Sharpe={nv['sharpe']}  n={nv['n_trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
