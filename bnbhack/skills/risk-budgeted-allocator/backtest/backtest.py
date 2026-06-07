#!/usr/bin/env python3
"""Risk-Budgeted Allocator · budget-invariant verification.

Proves the core safety property across an equity x drawdown grid for several
markets: worst_case_loss is always <= DD_BUDGET_K * R * equity, and the size
collapses to zero as drawdown approaches the internal cap. Read-only and
deterministic. Emits a JSON report to output/report.json next to this file.
"""

from __future__ import annotations

import json
import os
import sys

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from sizing import (  # noqa: E402
    DD_BUDGET_K, INTERNAL_CAP_RATIO, SizingInput, size_position,
)

MARKETS = [("BTCUSDT", "1h"), ("ETHUSDT", "4h"), ("BNBUSDT", "15m")]
EQUITY = 10_000.0
JURY_CAP = 0.20
DRAWDOWNS = [0.0, 0.02, 0.05, 0.08, 0.11, 0.135, 0.14, 0.18]
EPS = 1e-6


def run() -> dict:
    internal_cap = INTERNAL_CAP_RATIO * JURY_CAP
    rows = []
    invariant_ok = True
    monotonic_ok = True

    for symbol, tf in MARKETS:
        prev_notional = None
        for dd in DRAWDOWNS:
            r = size_position(SizingInput(
                symbol=symbol, timeframe=tf, equity=EQUITY,
                current_drawdown=dd, jury_cap=JURY_CAP,
            ))
            R = max(0.0, internal_cap - dd)
            budget = DD_BUDGET_K * R * EQUITY
            within = r.worst_case_loss <= budget + EPS
            invariant_ok = invariant_ok and within
            # As drawdown rises, notional must never increase for the same market.
            if prev_notional is not None and r.notional > prev_notional + EPS:
                monotonic_ok = False
            prev_notional = r.notional
            rows.append({
                "symbol": symbol, "timeframe": tf, "drawdown": dd,
                "R": round(R, 5), "approved": r.approved,
                "leverage": round(r.leverage, 3),
                "notional": round(r.notional, 2),
                "worst_case_loss": round(r.worst_case_loss, 4),
                "budget_ceiling": round(budget, 4),
                "within_budget": within,
                "win_rate": round(r.win_rate, 4),
                "payoff": round(r.payoff, 3),
            })

    # Size must be zero at or past the internal cap.
    blocked_past_cap = all(
        row["notional"] == 0.0 for row in rows
        if row["drawdown"] >= internal_cap
    )

    return {
        "skill": "risk-budgeted-allocator",
        "equity": EQUITY, "jury_cap": JURY_CAP,
        "internal_cap": round(internal_cap, 4),
        "dd_budget_k": DD_BUDGET_K,
        "invariant_worst_loss_within_budget": invariant_ok,
        "monotone_size_decreasing_in_drawdown": monotonic_ok,
        "size_zero_at_or_past_cap": blocked_past_cap,
        "n_scenarios": len(rows),
        "grid": rows,
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    ok = (report["invariant_worst_loss_within_budget"]
          and report["monotone_size_decreasing_in_drawdown"]
          and report["size_zero_at_or_past_cap"])
    print(f"budget invariant held : {report['invariant_worst_loss_within_budget']}")
    print(f"size monotone in dd   : {report['monotone_size_decreasing_in_drawdown']}")
    print(f"size zero past cap    : {report['size_zero_at_or_past_cap']}")
    print(f"scenarios checked     : {report['n_scenarios']}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
