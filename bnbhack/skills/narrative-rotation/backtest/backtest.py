#!/usr/bin/env python3
"""Narrative Rotation · out-of-sample ranking-separation verification.

The naive separation test (rank symbols and measure the top basket on the SAME
record) is near-tautological: the top basket is the top basket by construction.
This backtest instead splits the labeled record by time:

  * TRAIN window  [start, split)  -> rank symbols, pick the top-N and bottom-N
  * TEST  window  [split, end)    -> measure those baskets' realized expectancy

so the selection never sees the window it is scored on. If ranking by past edge
predicts future edge, the train-selected top basket still beats both the test
baseline and the train-selected bottom basket on the held-out window. The naive
in-sample numbers are reported alongside for transparency, clearly labeled.

Read-only and deterministic. The live CMC narrative tilt is not exercised here
(it needs a network key). Emits output/report.json.
"""

from __future__ import annotations

import json
import os
import sys

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from leaderboard import build_leaderboard, DEFAULT_DB_PATH, _ro_connect  # noqa: E402

TOP_N = 8
MIN_SAMPLES = 50          # train-window sample gate for selection
TEST_MIN_SAMPLES = 30     # holdout-window sample gate for scoring
TRAIN_FRAC = 0.6
HORIZON = "24h"
RANK_BY = "expectancy"


def _split_ts(db_path: str, train_frac: float = TRAIN_FRAC):
    """Entry_time at the train_frac percentile, so [start, split) holds
    train_frac of the dated rows. Deterministic for a given DB snapshot."""
    conn = _ro_connect(db_path)
    try:
        rows = [r[0] for r in conn.execute(
            "SELECT entry_time FROM signal_performance "
            "WHERE entry_time IS NOT NULL ORDER BY entry_time")]
    finally:
        conn.close()
    if not rows:
        return None
    idx = min(len(rows) - 1, int(len(rows) * train_frac))
    return int(rows[idx])


def _basket(entries) -> dict:
    n = len(entries)
    if n == 0:
        return {"n": 0, "mean_expectancy": 0.0, "symbols": []}
    return {
        "n": n,
        "mean_expectancy": round(sum(e.expectancy for e in entries) / n, 4),
        "symbols": [e.key for e in entries],
    }


def _scored_basket(symbols, test_map) -> dict:
    """Mean TEST-window expectancy of a basket selected on the TRAIN window.
    Only symbols that also clear the test sample gate contribute."""
    vals = [(s, test_map[s]) for s in symbols if s in test_map]
    if not vals:
        return {"n_selected": len(symbols), "n_scored": 0,
                "mean_test_expectancy": 0.0, "symbols_scored": []}
    return {
        "n_selected": len(symbols),
        "n_scored": len(vals),
        "mean_test_expectancy": round(sum(v for _, v in vals) / len(vals), 4),
        "symbols_scored": [s for s, _ in vals],
    }


def run() -> dict:
    db_path = os.getenv("MEFAI_SIGNAL_DB", DEFAULT_DB_PATH)
    split = _split_ts(db_path)

    # In-sample reference (the naive, self-selected separation), kept only for
    # transparency so the holdout result can be compared against it.
    full = build_leaderboard(group_by="symbol", rank_by=RANK_BY,
                             min_samples=MIN_SAMPLES, horizon=HORIZON)
    f_entries = full.entries
    f_top, f_bottom = f_entries[:TOP_N], f_entries[-TOP_N:]
    in_sample = {
        "qualified_symbols": len(f_entries),
        "baseline_expectancy": round(full.overall.expectancy, 4),
        "top_basket": _basket(f_top),
        "bottom_basket": _basket(f_bottom),
        "clean_partition": len(f_entries) >= 2 * TOP_N,
        "top_beats_baseline": _basket(f_top)["mean_expectancy"] > round(full.overall.expectancy, 4),
        "top_beats_bottom": _basket(f_top)["mean_expectancy"] > _basket(f_bottom)["mean_expectancy"],
    }

    # Out-of-sample holdout: select on train, score on test.
    train = build_leaderboard(group_by="symbol", rank_by=RANK_BY,
                              min_samples=MIN_SAMPLES, horizon=HORIZON,
                              until_ts=split)
    test = build_leaderboard(group_by="symbol", rank_by=RANK_BY,
                             min_samples=TEST_MIN_SAMPLES, horizon=HORIZON,
                             since_ts=split)
    t_entries = train.entries
    top_sel = [e.key for e in t_entries[:TOP_N]]
    bottom_sel = [e.key for e in t_entries[-TOP_N:]]
    test_map = {e.key: e.expectancy for e in test.entries}
    test_baseline = round(test.overall.expectancy, 4)

    top_sb = _scored_basket(top_sel, test_map)
    bottom_sb = _scored_basket(bottom_sel, test_map)

    clean_partition = (len(t_entries) >= 2 * TOP_N
                       and set(top_sel).isdisjoint(bottom_sel))
    scored_ok = top_sb["n_scored"] > 0 and bottom_sb["n_scored"] > 0
    beats_baseline = top_sb["mean_test_expectancy"] > test_baseline
    beats_bottom = top_sb["mean_test_expectancy"] > bottom_sb["mean_test_expectancy"]

    holdout = {
        "selected_on": "train", "scored_on": "test",
        "train_qualified_symbols": len(t_entries),
        "test_qualified_symbols": len(test.entries),
        "test_baseline_expectancy": test_baseline,
        "top_basket": top_sb,
        "bottom_basket": bottom_sb,
        "clean_partition": clean_partition,
        "top_beats_baseline": beats_baseline,
        "top_beats_bottom": beats_bottom,
    }

    separation_ok = clean_partition and scored_ok and beats_baseline and beats_bottom

    return {
        "skill": "narrative-rotation",
        "rank_by": RANK_BY, "horizon": HORIZON, "min_samples": MIN_SAMPLES,
        "test_min_samples": TEST_MIN_SAMPLES,
        "split": {
            "train_frac": TRAIN_FRAC,
            "split_ts": split,
            "note": "half-open windows: train [start, split_ts), test [split_ts, end)",
        },
        "holdout": holdout,
        "in_sample": in_sample,
        "separation_ok": separation_ok,
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    h = report["holdout"]
    print(f"split_ts              : {report['split']['split_ts']}")
    print(f"train qualified       : {h['train_qualified_symbols']}")
    print(f"test qualified        : {h['test_qualified_symbols']}")
    print(f"test baseline exp     : {h['test_baseline_expectancy']}")
    print(f"holdout top exp       : {h['top_basket']['mean_test_expectancy']} "
          f"(scored {h['top_basket']['n_scored']}/{h['top_basket']['n_selected']})")
    print(f"holdout bottom exp    : {h['bottom_basket']['mean_test_expectancy']} "
          f"(scored {h['bottom_basket']['n_scored']}/{h['bottom_basket']['n_selected']})")
    print(f"top beats baseline    : {h['top_beats_baseline']}")
    print(f"top beats bottom      : {h['top_beats_bottom']}")
    print("PASS" if report["separation_ok"] else "FAIL")
    return 0 if report["separation_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
