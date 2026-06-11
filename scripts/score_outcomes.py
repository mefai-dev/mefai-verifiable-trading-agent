#!/usr/bin/env python3
"""
MEFAI BNB HACK · deterministic, operator-independent outcome scoring.

The on-chain grading (CommitRevealPredictionRegistry.verifyOutcome) is signed by
the oracle key, so a skeptic should not have to trust that the operator graded a
prediction honestly. They do not have to: grading is a PURE, public function of
data that is already in the dataset (whose Merkle root is sealed on chain by
scripts/seal_dataset.py). This script IS that function. Anyone can run it on the
public sample to confirm the rule, and under NDA/escrow on the private DB to
recompute every win/loss and the whole leaderboard from scratch.

The rule (identical to the data generator and the live leaderboard):
  * pnl_h is the DIRECTION-SIGNED realized return over horizon h (positive means
    the market moved in the signal's favor). For a real row it is recomputed
    from the recorded prices:
        buy : pnl_24h = (price_24h - entry_price) / entry_price * 100
        sell: pnl_24h = (entry_price - price_24h) / entry_price * 100
    (when a price column is absent, the stored pnl_24h is used verbatim).
  * a resolved row is a WIN iff pnl_24h > 0, else a LOSS. The 24h horizon is the
    canonical, near-fully-resolved label.
  * win_rate = wins / resolved ; expectancy = mean(pnl_24h) over resolved.

The script ALSO audits the stored result_24h labels against this rule and reports
any mismatch, so a juror can confirm the shipped labels were not hand-edited.

Usage:
  python3 scripts/score_outcomes.py [path/to/signal.db]   (default data/signal.db)
"""
from __future__ import annotations

import sqlite3
import sys


def recompute_pnl(side: str, entry, p24, stored_pnl):
    """Direction-signed 24h return in percent, recomputed from prices when
    available, else the stored value (the public sample stores pnl directly)."""
    try:
        e = float(entry)
        if p24 is not None and e:
            raw = (float(p24) - e) / e * 100.0
            return raw if str(side).lower() == "buy" else -raw
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    try:
        return float(stored_pnl)
    except (TypeError, ValueError):
        return None


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/signal.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    have = {r[1] for r in con.execute("PRAGMA table_info(signal_performance)")}
    price_col = "price_24h" if "price_24h" in have else None
    cols = ["signal_type", "entry_price",
            price_col or "entry_price", "pnl_24h", "result_24h"]
    rows = con.execute(
        f"SELECT {', '.join(cols)} FROM signal_performance").fetchall()
    con.close()

    n = resolved = wins = mismatches = 0
    pnl_sum = 0.0
    for side, entry, p24, stored_pnl, stored_res in rows:
        n += 1
        pnl = recompute_pnl(side, entry, p24 if price_col else None, stored_pnl)
        if pnl is None or stored_res in (None, "", "pending"):
            continue
        resolved += 1
        label = "win" if pnl > 0 else "loss"
        if label == "win":
            wins += 1
        pnl_sum += pnl
        if str(stored_res).lower() not in (label, "tie"):
            mismatches += 1

    print(f"dataset        : {db}")
    print(f"price recompute: {'yes (price_24h present)' if price_col else 'no (stored pnl)'}")
    print(f"rows           : {n}")
    print(f"resolved (24h) : {resolved}")
    if resolved:
        print(f"recomputed wins: {wins}")
        print(f"win_rate       : {wins / resolved * 100:.2f}%")
        print(f"expectancy     : {pnl_sum / resolved:+.4f}% per signal")
    print(f"label mismatch : {mismatches}  "
          f"({'PASS · stored labels match the rule' if mismatches == 0 else 'REVIEW'})")


if __name__ == "__main__":
    main()
