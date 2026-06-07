"""
MEFAI · synthetic sample database generator

The production signal_performance book (181k labeled outcomes across forty
assets) is not committed to this repository: it is real account data and is
excluded by .gitignore. So that anyone can still run the agent and the sizing
engine end to end, this script writes a CLEARLY SYNTHETIC database of the exact
same shape (see schema.sql) into data/signal.db.

The rows here are generated from fixed per-symbol parameters with a seeded RNG.
They are illustrative ONLY. They are not a track record and must never be read
as one: the numbers are drawn to exercise the engine, not to report results.

Usage:
    python3 bnbhack/data/make_sample_db.py            # writes data/signal.db
    python3 bnbhack/data/make_sample_db.py --rows 800 # rows per (symbol,tf)
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "schema.sql")
DEFAULT_DB = os.path.join(HERE, "signal.db")

# Fixed, openly-stated synthetic parameters per symbol: (win_rate, payoff_ratio).
# A payoff above one with a sub-fifty win rate is exactly the positive-expectancy
# shape the engine is built to size; a couple of negative-edge entries are left
# in so the net-of-cost edge gate has something to reject.
SYMBOLS = {
    "BTCUSDT.P": (0.52, 1.8),
    "ETHUSDT.P": (0.49, 1.9),
    "BNBUSDT.P": (0.54, 1.6),
    "SOLUSDT.P": (0.47, 2.1),
    "XRPUSDT.P": (0.46, 1.2),   # thin / marginal edge on purpose
}
TIMEFRAMES = ["1h", "4h", "1d"]


def _leg(rng: random.Random, win_rate: float, payoff: float):
    """One resolved outcome: (result, pnl_pct, adverse_excursion_pct)."""
    win = rng.random() < win_rate
    if win:
        pnl = abs(rng.gauss(payoff, payoff * 0.4))
        adverse = abs(rng.gauss(payoff * 0.3, payoff * 0.2))
    else:
        pnl = -abs(rng.gauss(1.0, 0.4))
        adverse = abs(pnl) + abs(rng.gauss(0.5, 0.3))
    return ("win" if win else "loss"), round(pnl, 4), round(adverse, 4)


def build(db_path: str, rows_per_bucket: int) -> None:
    rng = random.Random(8004)  # seeded: the sample is reproducible
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db = sqlite3.connect(db_path)
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        db.executescript(fh.read())

    now = int(time.time())
    n = 0
    for symbol, (wr, payoff) in SYMBOLS.items():
        for tf in TIMEFRAMES:
            for i in range(rows_per_bucket):
                r1, p1, a1 = _leg(rng, wr, payoff)
                r4, p4, a4 = _leg(rng, wr, payoff)
                r24, p24, a24 = _leg(rng, wr, payoff)
                created = now - rng.randint(3600, 90 * 86400)
                db.execute(
                    "INSERT INTO signal_performance (symbol,timeframe,status,"
                    "created_ts,resolved_ts,result_1h,result_4h,result_24h,"
                    "pnl_1h,pnl_4h,pnl_24h,max_drawdown_pct) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (symbol, tf, "completed", created, created + 86400,
                     r1, r4, r24, p1, p4, p24, max(a1, a4, a24)),
                )
                n += 1
    db.commit()
    db.close()
    print(f"wrote {n} synthetic rows to {db_path} "
          f"({len(SYMBOLS)} symbols x {len(TIMEFRAMES)} timeframes x "
          f"{rows_per_bucket} rows)")
    print("NOTE: this is illustrative synthetic data, not a track record.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a synthetic sample book")
    ap.add_argument("--rows", type=int, default=400,
                    help="rows per (symbol, timeframe) bucket")
    ap.add_argument("--db", default=DEFAULT_DB, help="output sqlite path")
    args = ap.parse_args()
    build(args.db, max(1, args.rows))


if __name__ == "__main__":
    main()
