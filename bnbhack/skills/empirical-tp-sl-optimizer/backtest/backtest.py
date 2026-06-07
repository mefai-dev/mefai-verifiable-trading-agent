#!/usr/bin/env python3
"""Empirical TP/SL Optimizer · slice optimization and gate verification.

Runs the optimizer over several strategy slices, records the recommended bracket
and grid head, and verifies the recommendation logic is self-consistent: a
recommended cell must have positive expectancy above one standard error and meet
min_samples. Read-only and deterministic. Emits output/report.json.
"""

from __future__ import annotations

import json
import os
import sys

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from tp_sl_optimizer import optimize  # noqa: E402

SLICES = [
    {"symbol": "BTCUSDT", "timeframe": "1h", "signal_type": "buy"},
    {"symbol": "ETHUSDT", "timeframe": "1h", "signal_type": "sell"},
    {"symbol": None, "timeframe": "15m", "signal_type": "buy"},
    {"symbol": "BNBUSDT", "timeframe": "4h", "signal_type": None},
]


def _cell(c) -> dict:
    return {
        "tp": c.tp, "sl": c.sl, "rr": c.rr, "n": c.n,
        "win_rate": c.win_rate, "payoff": c.payoff,
        "expectancy": c.expectancy, "expectancy_stderr": c.expectancy_stderr,
        "expectancy_per_risk": c.expectancy_per_risk,
    }


def run() -> dict:
    out = []
    logic_ok = True
    for s in SLICES:
        res = optimize(**s)
        rec = res.best_per_risk
        # If a slice is recommended, the chosen cell must clear the gate.
        if res.recommend:
            consistent = (
                rec is not None
                and rec.n >= res.min_samples
                and rec.expectancy > 0
                and rec.expectancy > rec.expectancy_stderr
            )
            logic_ok = logic_ok and consistent
        out.append({
            "slice": s,
            "n_total": res.n_total,
            "horizon": res.horizon,
            "recommend": res.recommend,
            "note": res.note,
            "best_per_risk": _cell(rec) if rec else None,
            "best_expectancy": _cell(res.best) if res.best else None,
            "grid_head": [_cell(c) for c in res.grid[:5]],
        })
    return {
        "skill": "empirical-tp-sl-optimizer",
        "recommendation_logic_consistent": logic_ok,
        "n_slices": len(out),
        "slices": out,
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    for s in report["slices"]:
        print(f"{s['slice']}  n={s['n_total']}  recommend={s['recommend']}")
        print(f"    {s['note']}")
    print(f"recommendation logic consistent: {report['recommendation_logic_consistent']}")
    print("PASS" if report["recommendation_logic_consistent"] else "FAIL")
    return 0 if report["recommendation_logic_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
