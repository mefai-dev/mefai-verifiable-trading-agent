"""
MEFAI · per-asset funding contrarian tests

The fusion engine reads each asset's perpetual funding rate and turns crowding
into a CONTRARIAN tilt: a crowded-long book (longs paying shorts, positive
funding) leans SHORT, a crowded-short book (negative funding) leans LONG, and
ordinary funding inside a deadzone abstains so it adds no noise.

These tests pin that pure mapping (no network) so the contrarian sign, the
deadzone, the strength ramp, and the graceful handling of a bad upstream value
can never silently regress.

Run:  python3 -m unittest discover -s bnbhack/tests   (or: pytest bnbhack/tests)
"""

import os
import sys
import unittest

# Make the agent modules importable regardless of the working directory.
_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import fusion_providers as fp  # noqa: E402


class FundingContrarianTest(unittest.TestCase):
    def test_crowded_long_leans_short(self):
        # Longs paying shorts (positive funding) is a crowded-long book.
        r = fp.funding_contrarian(0.0005)
        self.assertTrue(r.available)
        self.assertEqual(r.direction, -1)
        self.assertGreater(r.strength, 0.0)
        self.assertIn("crowded long", r.detail)

    def test_crowded_short_leans_long(self):
        r = fp.funding_contrarian(-0.0005)
        self.assertTrue(r.available)
        self.assertEqual(r.direction, 1)
        self.assertGreater(r.strength, 0.0)
        self.assertIn("crowded short", r.detail)

    def test_deadzone_abstains(self):
        # Resting funding inside the deadzone expresses no directional view.
        for f in (0.0, fp.FUNDING_DEADZONE, -fp.FUNDING_DEADZONE, 0.00005):
            r = fp.funding_contrarian(f)
            self.assertTrue(r.available)
            self.assertEqual(r.direction, 0, msg=f"{f} should abstain")
            self.assertEqual(r.strength, 0.0)

    def test_strength_ramps_and_saturates(self):
        # Strength rises from the deadzone edge to full at FUNDING_FULL, then caps.
        mid = fp.funding_contrarian(0.00035)     # between deadzone and full
        full = fp.funding_contrarian(fp.FUNDING_FULL)
        over = fp.funding_contrarian(0.01)        # extreme crowding
        self.assertGreater(mid.strength, 0.0)
        self.assertLess(mid.strength, 1.0)
        self.assertAlmostEqual(full.strength, 1.0, places=6)
        self.assertEqual(over.strength, 1.0)
        self.assertEqual(over.direction, -1)

    def test_gate_source_has_no_hit_rate(self):
        # Funding has no win/loss record: it is a gate weighted by prior only.
        r = fp.funding_contrarian(0.0005)
        self.assertIsNone(r.hit_rate)
        self.assertEqual(r.skill_weight(), r.prior)  # gate -> full prior

    def test_bad_value_is_unavailable_not_raised(self):
        for bad in (None, "x", float("nan"), float("inf")):
            r = fp.funding_contrarian(bad)
            self.assertFalse(r.available, msg=f"{bad!r} should be unavailable")
            self.assertEqual(r.direction, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
