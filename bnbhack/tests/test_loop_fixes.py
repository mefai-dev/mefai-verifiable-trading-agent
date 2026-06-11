"""
MEFAI · loop hardening tests

Covers three audited behaviours of the live trading loop:

  1. Signal freshness (_signal_fresh + _signals_now): a stored signal row older
     than SIGNAL_MAX_AGE_BARS timeframe bars must never trigger a new entry at
     its stale price, and an unparseable timestamp fails CLOSED (treated as
     stale, never as fresh).

  2. Daily-floor last-resort base selection (_pick_lastresort_base): the one
     minimal qualifying swap placed late in the UTC day picks the most liquid
     ROUTABLE eligible base (preference ETH then LINK then AVAX, the cheapest
     deep/mid pools), skips bases the
     routability audit flagged and bases the book already holds, and returns
     None when nothing qualifies (the caller then logs and stands down rather
     than trading an unroutable token).

  3. The two helpers are pure, so these tests need no network, no chain
     adapter and no production data.

Run:  python3 -m unittest discover -s bnbhack/tests   (or: pytest bnbhack/tests)
"""

import os
import sqlite3
import sys
import tempfile
import unittest

# Make the agent modules importable regardless of the working directory.
_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import loop  # noqa: E402


class SignalFreshnessTest(unittest.TestCase):
    NOW = 1_750_000_000.0
    BAR_5M = 300

    def test_fresh_row_passes(self):
        # One bar old on a 5m book: comfortably fresh.
        self.assertTrue(loop._signal_fresh(self.NOW - self.BAR_5M, "5m", self.NOW))

    def test_boundary_age_still_fresh(self):
        # Exactly SIGNAL_MAX_AGE_BARS bars old is the last fresh moment.
        age = loop.SIGNAL_MAX_AGE_BARS * self.BAR_5M
        self.assertTrue(loop._signal_fresh(self.NOW - age, "5m", self.NOW))

    def test_stale_row_skipped(self):
        age = (loop.SIGNAL_MAX_AGE_BARS * self.BAR_5M) + 1
        self.assertFalse(loop._signal_fresh(self.NOW - age, "5m", self.NOW))

    def test_age_scales_with_timeframe(self):
        # 9 five-minute bars old: stale on 5m, fresh on 1h.
        ts = self.NOW - 9 * self.BAR_5M
        self.assertFalse(loop._signal_fresh(ts, "5m", self.NOW))
        self.assertTrue(loop._signal_fresh(ts, "1h", self.NOW))

    def test_unparseable_timestamp_fails_closed(self):
        for raw in (None, "", "yesterday", "2026-06-10 12:00:00", float("nan")):
            self.assertFalse(loop._signal_fresh(raw, "5m", self.NOW),
                             msg=f"raw={raw!r} must be treated as stale")

    def test_explicit_zero_bars_disables_gate(self):
        self.assertTrue(loop._signal_fresh(self.NOW - 10 * 86400, "5m",
                                           self.NOW, max_bars=0))

    def test_signals_now_skips_old_rows(self):
        # End to end through the real reader: a fresh BUY row is returned, a
        # stale row (same shape) is silently skipped.
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "signal.db")
        db = sqlite3.connect(db_path)
        db.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY, symbol TEXT,"
                   " timeframe TEXT, signal TEXT, timestamp REAL, price REAL)")
        import time as _time
        now = _time.time()
        fresh_ts = now - loop._TF_SECONDS["5m"]                       # 1 bar
        stale_ts = now - (loop.SIGNAL_MAX_AGE_BARS + 4) * loop._TF_SECONDS["5m"]
        db.execute("INSERT INTO signals (symbol,timeframe,signal,timestamp,price)"
                   " VALUES (?,?,?,?,?)", ("ETHUSDT.P", "5m", "buy", fresh_ts, 3000.0))
        db.execute("INSERT INTO signals (symbol,timeframe,signal,timestamp,price)"
                   " VALUES (?,?,?,?,?)", ("XRPUSDT.P", "5m", "sell", stale_ts, 2.0))
        db.commit()
        db.close()
        orig = loop.SIGNAL_DB
        loop.SIGNAL_DB = db_path
        try:
            out = loop._signals_now(["ETHUSDT", "XRPUSDT"], "5m")
        finally:
            loop.SIGNAL_DB = orig
        self.assertEqual([s["pair"] for s in out], ["ETHUSDT"])
        self.assertEqual(out[0]["side"], "buy")


class LastResortPickerTest(unittest.TestCase):
    # Includes the preferred deep/mid bases (ETH, LINK, AVAX) so the preference
    # order is actually exercised, plus thinner bases that only the alphabetical
    # fall-through should ever reach.
    SPOT = {"ETH": "ETH", "LINK": "LINK", "AVAX": "AVAX", "XRP": "XRP",
            "ADA": "ADA", "DOGE": "DOGE", "CAKE": "CAKE"}

    def test_prefers_eth_first(self):
        self.assertEqual(loop._pick_lastresort_base(self.SPOT), ("ETH", "ETH"))

    def test_unroutable_base_is_skipped(self):
        # ETH unroutable -> next preferred deep/mid pool is LINK.
        self.assertEqual(loop._pick_lastresort_base(self.SPOT, ["ETH"]),
                         ("LINK", "LINK"))

    def test_held_base_is_skipped(self):
        # ETH unroutable and LINK already held -> next preferred is AVAX.
        pick = loop._pick_lastresort_base(self.SPOT, ["ETH"], excluded=["LINK"])
        self.assertEqual(pick, ("AVAX", "AVAX"))

    def test_falls_through_to_remaining_spot_map(self):
        # All three preferred bases out: the remaining spot-map bases are
        # considered alphabetically (ADA before CAKE before DOGE).
        pick = loop._pick_lastresort_base(self.SPOT, ["ETH", "LINK", "AVAX"])
        self.assertEqual(pick, ("ADA", "ADA"))

    def test_case_insensitive_exclusions(self):
        self.assertEqual(loop._pick_lastresort_base(self.SPOT, ["eth"]),
                         ("LINK", "LINK"))

    def test_nothing_routable_returns_none(self):
        self.assertIsNone(loop._pick_lastresort_base(self.SPOT, list(self.SPOT)))

    def test_empty_spot_map_returns_none(self):
        self.assertIsNone(loop._pick_lastresort_base({}))

    def test_preference_order_is_eth_link_avax(self):
        self.assertEqual(loop._FLOOR_LASTRESORT_PREFERENCE,
                         ("ETH", "LINK", "AVAX"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
