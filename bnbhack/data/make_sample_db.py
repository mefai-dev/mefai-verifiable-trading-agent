"""
MEFAI · synthetic sample database generator

The production database (the live `signals` stream and the labeled
`signal_performance` book of 181k resolved outcomes across forty assets) is not
committed to this repository: it is real account data and is excluded by
.gitignore. So that anyone can still run the agent, the sizing engine, the
TP/SL optimizer, the leaderboard and the walk-forward backtests end to end,
this script writes a CLEARLY SYNTHETIC database of the exact same shape (see
schema.sql) into data/signal.db.

Every row is generated from fixed per-symbol parameters with a seeded RNG, then
each trade is simulated as a coherent price path: a favorable excursion (MFE)
and an adverse excursion (MAE) decide which take-profit and stop-loss barriers
were touched and when, so the optimizer has a real, internally-consistent grid
to sweep. The numbers are illustrative ONLY. They are not a track record and
must never be read as one.

Usage:
    python3 bnbhack/data/make_sample_db.py            # writes data/signal.db
    python3 bnbhack/data/make_sample_db.py --rows 800 # rows per (symbol, tf)
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "schema.sql")
DEFAULT_DB = os.path.join(HERE, "signal.db")

# Per-symbol synthetic shape: (win_rate, payoff_ratio, reference_price).
# A payoff above one with a sub-fifty-five win rate is exactly the positive
# expectancy shape the engine is built to size; XRP is left marginal so the
# net-of-cost edge gate has a cell to reject.
SYMBOLS = {
    "BTCUSDT.P": (0.515, 1.5, 60000.0),
    "ETHUSDT.P": (0.510, 1.5, 3000.0),
    "BNBUSDT.P": (0.520, 1.4, 600.0),
    "SOLUSDT.P": (0.498, 1.6, 150.0),
    "XRPUSDT.P": (0.480, 1.1, 0.60),
}
# 5m is the live loop's default scan timeframe; the longer buckets feed the
# 24h-horizon backtests. Every bucket carries enough rows to clear the
# optimizer and walk-forward minimum-sample gates.
TIMEFRAMES = ["5m", "1h", "4h", "1d"]

TP_LEVELS = [(0.5, "tp_05"), (1.0, "tp_1"), (1.5, "tp_15"), (2.0, "tp_2"),
             (3.0, "tp_3"), (5.0, "tp_5"), (10.0, "tp_10")]
SL_LEVELS = [(0.2, "sl_02"), (0.3, "sl_03"), (0.5, "sl_05"), (0.7, "sl_07"),
             (0.9, "sl_09"), (1.0, "sl_1"), (1.5, "sl_15"), (2.0, "sl_2"),
             (3.0, "sl_3"), (4.0, "sl_4"), (5.0, "sl_5"), (7.0, "sl_7"),
             (10.0, "sl_10")]
HORIZON_SEC = 86400  # the 24h label window the barrier times live inside


def _trade(rng: random.Random, win_rate: float, payoff: float):
    """Simulate one resolved trade as a coherent path.

    Returns a dict of every signal_performance field for the row. PnL is
    direction-signed (positive = favorable); MFE/MAE drive the barrier hits."""
    win = rng.random() < win_rate
    side = "buy" if rng.random() < 0.5 else "sell"  # direction is independent
    if win:
        r24 = abs(rng.gauss(payoff * 0.85, payoff * 0.3))  # favorable %
    else:
        r24 = -abs(rng.gauss(0.8, 0.35))                   # adverse %

    # Favorable / adverse excursions bracket the realized move (both >= 0).
    mfe = max(r24, 0.0) + abs(rng.gauss(0.4, 0.3)) + 0.05
    mae = max(-r24, 0.0) + abs(rng.gauss(0.4, 0.3)) + 0.05
    # Time it took to reach each extreme (seconds inside the 24h window).
    reach_tp = rng.randint(1800, HORIZON_SEC)
    reach_sl = rng.randint(1800, HORIZON_SEC)

    row = {
        "signal_type": side,
        "pnl_24h": round(r24, 4),
        "pnl_4h": round(r24 * rng.uniform(0.5, 0.9), 4),
        "pnl_1h": round(r24 * rng.uniform(0.2, 0.6), 4),
        "max_drawdown_pct": round(mae, 4),
        "max_profit_pct": round(mfe, 4),
    }
    for col, val in (("result_1h", row["pnl_1h"]), ("result_4h", row["pnl_4h"]),
                     ("result_24h", row["pnl_24h"])):
        row[col] = "win" if val > 0 else "loss"

    # Barriers: a TP at p% is touched iff MFE reached p%; smaller barriers are
    # reached earlier (time scales with how far into the run the level sits).
    for pct, c in TP_LEVELS:
        if mfe >= pct:
            frac = pct / mfe
            row[f"{c}_hit"] = 1
            row[f"{c}_time"] = max(60, int(frac * reach_tp))
        else:
            row[f"{c}_hit"] = 0
            row[f"{c}_time"] = None
    for pct, c in SL_LEVELS:
        if mae >= pct:
            frac = pct / mae
            row[f"{c}_hit"] = 1
            row[f"{c}_time"] = max(60, int(frac * reach_sl))
        else:
            row[f"{c}_hit"] = 0
            row[f"{c}_time"] = None
    return row


def build(db_path: str, rows_per_bucket: int) -> None:
    rng = random.Random(8004)  # seeded: the sample is reproducible
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db = sqlite3.connect(db_path)
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        db.executescript(fh.read())

    barrier_cols = []
    for _p, c in TP_LEVELS + SL_LEVELS:
        barrier_cols += [f"{c}_hit", f"{c}_time"]
    base_cols = ["symbol", "timeframe", "signal_type", "status", "entry_time",
                 "entry_price", "result_1h", "result_4h", "result_24h",
                 "pnl_1h", "pnl_4h", "pnl_24h", "max_drawdown_pct",
                 "max_profit_pct"]
    all_cols = base_cols + barrier_cols
    placeholders = ",".join("?" * len(all_cols))
    insert_sql = (f"INSERT INTO signal_performance ({','.join(all_cols)}) "
                  f"VALUES ({placeholders})")

    now = int(time.time())
    window = 120 * 86400  # spread entries over ~120 days, ascending by time
    n_perf = 0
    for symbol, (wr, payoff, ref_price) in SYMBOLS.items():
        for tf in TIMEFRAMES:
            for i in range(rows_per_bucket):
                t = _trade(rng, wr, payoff)
                entry_time = now - window + int(i / rows_per_bucket * window)
                entry_price = round(ref_price * (1.0 + rng.gauss(0, 0.03)), 6)
                values = [symbol, tf, t["signal_type"], "completed", entry_time,
                          entry_price, t["result_1h"], t["result_4h"],
                          t["result_24h"], t["pnl_1h"], t["pnl_4h"],
                          t["pnl_24h"], t["max_drawdown_pct"],
                          t["max_profit_pct"]]
                for _p, c in TP_LEVELS + SL_LEVELS:
                    values += [t[f"{c}_hit"], t[f"{c}_time"]]
                db.execute(insert_sql, values)
                n_perf += 1

    # The live signal stream: a short recent history per (symbol, timeframe),
    # so the fusion layer and the loop read a fresh 'buy'/'sell' for each.
    n_sig = 0
    for symbol, (wr, _payoff, ref_price) in SYMBOLS.items():
        for tf in TIMEFRAMES:
            for k in range(20):
                side = "buy" if rng.random() < wr else "sell"
                ts = now - (20 - k) * 300
                price = round(ref_price * (1.0 + rng.gauss(0, 0.02)), 6)
                db.execute(
                    "INSERT INTO signals (symbol,timeframe,signal,timestamp,"
                    "price) VALUES (?,?,?,?,?)", (symbol, tf, side, ts, price))
                n_sig += 1

    db.commit()
    db.close()
    buckets = len(SYMBOLS) * len(TIMEFRAMES)
    print(f"wrote {n_perf} synthetic signal_performance rows + {n_sig} signals "
          f"to {db_path} ({len(SYMBOLS)} symbols x {len(TIMEFRAMES)} timeframes "
          f"x {rows_per_bucket} rows over {buckets} buckets)")
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
