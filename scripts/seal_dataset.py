#!/usr/bin/env python3
"""
MEFAI BNB HACK · dataset Merkle commitment.

The production outcome base is private (it is the live business's signal
history), so the repository cannot ship it. This script makes the dataset
verifiable WITHOUT publishing it:

  1. it walks every row of `signal_performance` in primary-key order,
  2. canonicalizes the outcome-bearing fields of each row to compact JSON,
  3. hashes each row to a sha256 leaf and folds the leaves into a Merkle root,
  4. prints the root, the row count, the file sha256 and honest aggregates.

The operator runs it on the private production DB and seals the printed root
in a BSC mainnet transaction from the keeper wallet. A juror can:
  - run THIS script on the public sample DB and confirm the algorithm,
  - check the sealed root on BscScan,
  - and, under NDA or escrow, run the same script on the private DB and
    reproduce the exact sealed root - one byte of tampering changes it.

Usage:
  python3 scripts/seal_dataset.py [path/to/signal.db]
(defaults to data/signal.db, the public sample)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys

FIELDS = ["id", "signal_id", "symbol", "timeframe", "signal_type",
          "entry_price", "entry_time", "price_1h", "price_4h", "price_24h",
          "pnl_1h", "pnl_4h", "pnl_24h", "result_1h", "result_4h",
          "result_24h"]


def _leaf(row: tuple) -> bytes:
    obj = {k: row[i] for i, k in enumerate(FIELDS)}
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).digest()


def merkle_root(leaves: list) -> bytes:
    if not leaves:
        return hashlib.sha256(b"").digest()
    level = leaves
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(hashlib.sha256(left + right).digest())
        level = nxt
    return level[0]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/signal.db"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    # Use the intersection of the canonical field list with the columns the DB
    # actually has (the public sample omits a couple of production columns).
    # The fields used are printed: a root commits to exactly that field list.
    have = {r[1] for r in con.execute("PRAGMA table_info(signal_performance)")}
    global FIELDS
    FIELDS = [f for f in FIELDS if f in have]
    cur = con.execute(
        f"SELECT {', '.join(FIELDS)} FROM signal_performance ORDER BY id")
    leaves, n = [], 0
    agg = {"resolved_24h": 0, "win_24h": 0, "symbols": set()}
    for row in cur:
        leaves.append(_leaf(row))
        n += 1
        r24 = row[FIELDS.index("result_24h")]
        if r24 and r24 != "pending":
            agg["resolved_24h"] += 1
            if r24 in ("win", "tp", "profit", "correct"):
                agg["win_24h"] += 1
        agg["symbols"].add(row[FIELDS.index("symbol")])
    con.close()

    root = merkle_root(leaves)
    print(f"fields          : {','.join(FIELDS)}")
    print(f"rows            : {n}")
    print(f"merkle_root     : 0x{root.hex()}")
    print(f"dataset_sha256  : {file_sha256(db_path)}")
    print(f"distinct_symbols: {len(agg['symbols'])}")
    print(f"resolved_24h    : {agg['resolved_24h']}")
    if agg["resolved_24h"]:
        print(f"win_rate_24h    : "
              f"{agg['win_24h'] / agg['resolved_24h'] * 100:.2f}%")


if __name__ == "__main__":
    main()
