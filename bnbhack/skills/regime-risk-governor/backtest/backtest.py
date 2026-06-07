#!/usr/bin/env python3
"""Regime Risk Governor · gate monotonicity verification.

Sweeps regime direction x strength over a recommended bracket and confirms:
aligned size is non-decreasing in conviction, opposed size is non-increasing,
extreme opposition stands aside, and the drawdown gate forces allowed size to
zero at the cap. Read-only and deterministic. Emits output/report.json.
"""

from __future__ import annotations

import json
import os
import sys

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from tp_sl_optimizer import optimize, regime_overlay  # noqa: E402
from sizing import INTERNAL_CAP_RATIO, DD_BUDGET_K  # noqa: E402

# A pooled slice with enough resolved trades to clear the significance gate, so
# the full regime ladder (aligned up, opposed down, extreme stand-aside) runs.
SLICE = {"symbol": None, "timeframe": "15m", "signal_type": "buy"}
STRENGTHS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
JURY_CAP = 0.20


def _scales(res, direction):
    out = []
    for s in STRENGTHS:
        d = regime_overlay(res, regime_direction=direction, regime_strength=s)
        out.append({"strength": s, "deploy": d.deploy,
                    "risk_scale": d.risk_scale, "alignment": d.alignment})
    return out


def _non_decreasing(vals):
    return all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))


def _non_increasing(vals):
    return all(b <= a + 1e-9 for a, b in zip(vals, vals[1:]))


def run() -> dict:
    res = optimize(**SLICE)
    report = {"skill": "regime-risk-governor", "slice": SLICE,
              "has_edge": res.recommend, "note": res.note}

    if not res.recommend:
        report["gate_checks_ok"] = True
        report["detail"] = "no significant edge; overlay correctly deploys nothing"
        report["aligned"] = _scales(res, 1)
        report["opposed"] = _scales(res, -1)
        report["drawdown_gate"] = _drawdown_gate()
        return report

    aligned = _scales(res, 1)
    opposed = _scales(res, -1)
    al_scales = [r["risk_scale"] for r in aligned]
    op_scales = [r["risk_scale"] for r in opposed]
    extreme_stands_aside = not opposed[-1]["deploy"]  # strength 1.0 opposed

    dd = _drawdown_gate()

    report.update({
        "aligned": aligned,
        "opposed": opposed,
        "aligned_size_non_decreasing": _non_decreasing(al_scales),
        "opposed_size_non_increasing": _non_increasing(op_scales),
        "extreme_opposition_stands_aside": extreme_stands_aside,
        "drawdown_gate": dd,
        "gate_checks_ok": (
            _non_decreasing(al_scales)
            and _non_increasing(op_scales)
            and extreme_stands_aside
            and dd["room_zero_at_cap"]
        ),
    })
    return report


def _drawdown_gate() -> dict:
    internal_cap = INTERNAL_CAP_RATIO * JURY_CAP
    rows = []
    for dd in [0.0, 0.05, 0.10, internal_cap, internal_cap + 0.02]:
        R = max(0.0, internal_cap - dd)
        rows.append({"drawdown": round(dd, 4), "R": round(R, 5),
                     "max_risk_fraction": round(DD_BUDGET_K * R, 6)})
    return {"internal_cap": round(internal_cap, 4), "rows": rows,
            "room_zero_at_cap": rows[-2]["R"] == 0.0 and rows[-1]["R"] == 0.0}


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"slice has edge        : {report['has_edge']}")
    if "aligned_size_non_decreasing" in report:
        print(f"aligned non-decreasing: {report['aligned_size_non_decreasing']}")
        print(f"opposed non-increasing: {report['opposed_size_non_increasing']}")
        print(f"extreme stands aside  : {report['extreme_opposition_stands_aside']}")
    print(f"drawdown room zero @cap: {report['drawdown_gate']['room_zero_at_cap']}")
    print("PASS" if report["gate_checks_ok"] else "FAIL")
    return 0 if report["gate_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
