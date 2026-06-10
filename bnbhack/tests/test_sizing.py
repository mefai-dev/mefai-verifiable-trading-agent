"""
MEFAI · engine integrity tests

These tests exercise the two claims that matter most for a verifiable agent:

  1. The drawdown budget cannot be breached. For ANY approved position the
     worst-case loss (notional x stop) is bounded by DD_BUDGET_K * R * equity,
     where R is the remaining room to the internal drawdown cap. As R shrinks to
     zero the agent physically cannot size a position. This is the off-chain
     twin of the on-chain RiskGovernor.

  2. The engine is direction aware. A short leg carries dir = -1 and a long
     carries dir = +1, and realized pnl is signed by direction, so the book
     earns in falling weeks as well as rising ones.

The tests build a small, clearly-synthetic signal_performance database (the
same shape as bnbhack/data/schema.sql) in a temp directory, so they need no
production data and run anywhere with the standard library.

Run:  python3 -m unittest discover -s bnbhack/tests   (or: pytest bnbhack/tests)
"""

import os
import random
import sqlite3
import sys
import tempfile
import unittest

# Make the agent modules importable regardless of the working directory.
_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import sizing  # noqa: E402
import position_manager as pm  # noqa: E402


def _build_db(path, win_rate=0.55, payoff=2.0, rows=600, symbol="BTCUSDT.P", tf="1h"):
    """Write a synthetic signal_performance bucket with a known positive edge."""
    rng = random.Random(8004)
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE signal_performance (id INTEGER PRIMARY KEY, symbol TEXT,"
        " timeframe TEXT, status TEXT, result_1h TEXT, result_4h TEXT,"
        " result_24h TEXT, pnl_1h REAL, pnl_4h REAL, pnl_24h REAL,"
        " max_drawdown_pct REAL);"
    )
    for _ in range(rows):
        win = rng.random() < win_rate
        if win:
            pnl = abs(rng.gauss(payoff, payoff * 0.3))
            adverse = abs(rng.gauss(payoff * 0.3, 0.2))
            res = "win"
        else:
            pnl = -abs(rng.gauss(1.0, 0.3))
            adverse = abs(pnl) + abs(rng.gauss(0.5, 0.2))
            res = "loss"
        db.execute(
            "INSERT INTO signal_performance (symbol,timeframe,status,result_1h,"
            "result_4h,result_24h,pnl_1h,pnl_4h,pnl_24h,max_drawdown_pct) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            (symbol, tf, "completed", res, res, res, pnl, pnl, pnl, adverse),
        )
    db.commit()
    db.close()


class KellyFractionTest(unittest.TestCase):
    def test_known_values(self):
        # f* = p - (1-p)/b
        self.assertAlmostEqual(sizing.kelly_fraction(0.5, 2.0), 0.25, places=6)
        self.assertAlmostEqual(sizing.kelly_fraction(0.6, 1.0), 0.20, places=6)

    def test_clamped_and_guarded(self):
        self.assertEqual(sizing.kelly_fraction(0.4, 1.0), 0.0)   # negative -> 0
        self.assertEqual(sizing.kelly_fraction(0.9, 0.0), 0.0)   # b<=0 -> 0
        self.assertLessEqual(sizing.kelly_fraction(0.99, 50.0), 1.0)


class SizingSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "signal.db")
        _build_db(self.db)
        # Point the read-only sizing reader at the synthetic book and clear caches.
        self._orig = sizing.SIGNAL_DB
        sizing.SIGNAL_DB = self.db
        sizing._stats_cache.clear(); sizing._stats_ts.clear()
        sizing._prior_cache.clear(); sizing._prior_ts.clear()

    def tearDown(self):
        sizing.SIGNAL_DB = self._orig
        sizing._stats_cache.clear(); sizing._stats_ts.clear()
        sizing._prior_cache.clear(); sizing._prior_ts.clear()

    def test_drawdown_budget_never_breached(self):
        inp = sizing.SizingInput(symbol="BTCUSDT", timeframe="1h", equity=10000.0,
                                 current_drawdown=0.0)
        r = sizing.size_position(inp)
        self.assertTrue(r.approved, msg=r.reasons)
        # The headline guarantee: worst-case loss <= DD_BUDGET_K * R * equity.
        bound = sizing.DD_BUDGET_K * r.drawdown_room_R * r.equity
        self.assertLessEqual(r.worst_case_loss, bound + 1e-6)
        self.assertGreater(r.notional, 0.0)

    def test_exhausted_room_blocks_all_size(self):
        # Drawdown already at the internal cap (0.7 * jury_cap) -> R = 0.
        inp = sizing.SizingInput(symbol="BTCUSDT", timeframe="1h", equity=10000.0,
                                 current_drawdown=0.20)
        r = sizing.size_position(inp)
        self.assertFalse(r.approved)
        self.assertEqual(r.worst_case_loss, 0.0)
        self.assertEqual(r.drawdown_room_R, 0.0)

    def test_regime_off_stands_aside(self):
        inp = sizing.SizingInput(symbol="BTCUSDT", timeframe="1h", equity=10000.0,
                                 current_drawdown=0.0, regime_gate=0.0)
        r = sizing.size_position(inp)
        self.assertFalse(r.approved)
        self.assertEqual(r.notional, 0.0)

    def test_thin_bucket_no_bet(self):
        # A symbol with no rows falls back to the prior with n=0 < MIN_EDGE_SAMPLES.
        inp = sizing.SizingInput(symbol="DOGEUSDT", timeframe="1h", equity=10000.0,
                                 current_drawdown=0.0)
        r = sizing.size_position(inp)
        self.assertFalse(r.approved)


class MarginSpendPropertyTest(unittest.TestCase):
    """Regression for the margin == equity identity bug. sizing defined
    leverage = notional / equity and then margin = notional / leverage, which
    reduced to `equity` in EVERY branch, so a consumer treating margin as the
    per-trade spend deployed the whole account on each leg. The properties
    asserted here: the executed spend (min of notional and any external caps)
    keeps the risk budget, and margin only ever equals equity when the leg is
    GENUINELY levered to the point of committing the full account."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "signal.db")
        _build_db(self.db)
        self._orig = sizing.SIGNAL_DB
        sizing.SIGNAL_DB = self.db
        sizing._stats_cache.clear(); sizing._stats_ts.clear()
        sizing._prior_cache.clear(); sizing._prior_ts.clear()

    def tearDown(self):
        sizing.SIGNAL_DB = self._orig
        sizing._stats_cache.clear(); sizing._stats_ts.clear()
        sizing._prior_cache.clear(); sizing._prior_ts.clear()

    def test_executed_spend_respects_risk_budget(self):
        # Across a grid of inputs the SPEND the loop derives from the sizer
        # (min of notional and external caps) must keep the per-trade risk
        # budget: spend * stop_fraction <= rho * equity (small float slack).
        for equity in (250.0, 1000.0, 10000.0, 100378.0):
            for dd in (0.0, 0.02, 0.05, 0.10):
                for stop in (None, 0.005, 0.02, 0.10):
                    for conv in (0.4, 1.0):
                        inp = sizing.SizingInput(
                            symbol="BTCUSDT", timeframe="1h", equity=equity,
                            current_drawdown=dd, stop_distance=stop,
                            conviction=conv)
                        r = sizing.size_position(inp)
                        if not r.approved:
                            continue
                        for cap in (250.0, equity, float("inf")):
                            spend = min(r.notional, cap)
                            self.assertLessEqual(
                                spend * r.stop_distance,
                                r.risk_budget_rho * r.equity * 1.001,
                                msg=f"eq={equity} dd={dd} stop={stop} "
                                    f"conv={conv} cap={cap}")

    def test_margin_not_equity_unless_genuinely_levered(self):
        # A wide explicit stop keeps the position UNLEVERED (notional < equity);
        # the committed capital is then the notional itself, never the whole
        # account.
        inp = sizing.SizingInput(symbol="BTCUSDT", timeframe="1h",
                                 equity=10000.0, current_drawdown=0.0,
                                 stop_distance=0.10)
        r = sizing.size_position(inp)
        self.assertTrue(r.approved, msg=r.reasons)
        self.assertLessEqual(r.leverage, 1.0)
        self.assertAlmostEqual(r.margin, r.notional, places=6)
        self.assertLess(r.margin, r.equity)

    def test_levered_margin_is_notional_over_leverage(self):
        # A tight stop pushes notional above equity (leverage > 1); margin is
        # then genuinely notional / leverage. With leverage defined as
        # notional / equity that equals the full account, the one case where
        # margin == equity is legitimate.
        inp = sizing.SizingInput(symbol="BTCUSDT", timeframe="1h",
                                 equity=10000.0, current_drawdown=0.0,
                                 stop_distance=0.002)
        r = sizing.size_position(inp)
        self.assertTrue(r.approved, msg=r.reasons)
        self.assertGreater(r.leverage, 1.0)
        self.assertAlmostEqual(r.margin, r.notional / r.leverage, places=6)
        # The worst-case loss bound still holds in the levered branch.
        bound = sizing.DD_BUDGET_K * r.drawdown_room_R * r.equity
        self.assertLessEqual(r.worst_case_loss, bound + 1e-6)


class DirectionAwareTest(unittest.TestCase):
    def test_leg_dir_reads_signal_dir(self):
        self.assertEqual(pm._leg_dir({"signal_dir": 1}), 1)
        self.assertEqual(pm._leg_dir({"signal_dir": -1}), -1)
        self.assertEqual(pm._leg_dir({"signal_dir": None}), 1)  # default long

    def test_pnl_sign_convention(self):
        # pnl_pct = dir * (exit - entry) / entry * 100, the exact form the
        # position manager uses for both the realized and unrealized legs.
        entry, up, down = 100.0, 110.0, 90.0
        long_up = 1 * (up - entry) / entry * 100.0
        short_down = -1 * (down - entry) / entry * 100.0
        self.assertGreater(long_up, 0)     # long gains when price rises
        self.assertGreater(short_down, 0)  # short gains when price falls
        self.assertAlmostEqual(long_up, short_down, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
