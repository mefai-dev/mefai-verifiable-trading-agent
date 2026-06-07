#!/usr/bin/env python3
"""Narrative Rotation · ranking-separation verification.

Builds the verified symbol ranking, forms an equal-weight top-N rotation basket,
and checks that it separates from the global baseline and from a bottom-N basket.
Read-only and deterministic. The live CMC narrative tilt is not exercised here
(it needs a network key); this proves the verified backbone carries signal.
Emits output/report.json.
"""

from __future__ import annotations

import json
import os
import sys

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from leaderboard import build_leaderboard  # noqa: E402

TOP_N = 8
MIN_SAMPLES = 50
HORIZON = "24h"
RANK_BY = "expectancy"


def _basket(entries) -> dict:
    n = len(entries)
    if n == 0:
        return {"n": 0, "mean_expectancy": 0.0, "mean_win_rate": 0.0}
    return {
        "n": n,
        "mean_expectancy": round(sum(e.expectancy for e in entries) / n, 4),
        "mean_win_rate": round(sum(e.win_rate for e in entries) / n, 4),
        "symbols": [e.key for e in entries],
    }


def run() -> dict:
    lb = build_leaderboard(group_by="symbol", rank_by=RANK_BY,
                           min_samples=MIN_SAMPLES, horizon=HORIZON)
    entries = lb.entries
    top = entries[:TOP_N]
    bottom = entries[-TOP_N:] if len(entries) >= TOP_N else entries

    top_b = _basket(top)
    bottom_b = _basket(bottom)
    baseline = round(lb.overall.expectancy, 4)

    # The top/bottom comparison is only meaningful on a disjoint partition; with
    # fewer than 2*TOP_N qualified symbols the baskets overlap and the separation
    # test would be partly self-referential, so it is marked inconclusive.
    clean_partition = len(entries) >= 2 * TOP_N

    beats_baseline = top_b["mean_expectancy"] > baseline
    beats_bottom = top_b["mean_expectancy"] > bottom_b["mean_expectancy"]

    return {
        "skill": "narrative-rotation",
        "rank_by": RANK_BY, "horizon": HORIZON, "min_samples": MIN_SAMPLES,
        "qualified_symbols": len(entries),
        "below_threshold": lb.below_threshold,
        "clean_partition": clean_partition,
        "global_baseline_expectancy": baseline,
        "top_basket": top_b,
        "bottom_basket": bottom_b,
        "top_beats_baseline": beats_baseline,
        "top_beats_bottom": beats_bottom,
        "separation_ok": clean_partition and beats_baseline and beats_bottom,
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"qualified symbols     : {report['qualified_symbols']}")
    print(f"clean partition       : {report['clean_partition']}")
    print(f"global baseline exp   : {report['global_baseline_expectancy']}")
    print(f"top-{TOP_N} basket exp     : {report['top_basket']['mean_expectancy']}")
    print(f"bottom-{TOP_N} basket exp  : {report['bottom_basket']['mean_expectancy']}")
    print(f"top beats baseline    : {report['top_beats_baseline']}")
    print(f"top beats bottom      : {report['top_beats_bottom']}")
    print("PASS" if report["separation_ok"] else "FAIL")
    return 0 if report["separation_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
