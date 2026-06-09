"""
MEFAI · standing-allowance security check tests

The pre-trade solver reads the wallet's CURRENT on-chain allowance of the sold
ERC-20 to the swap spender and surfaces a standing infinite approval. The single
property that matters for safety is that this read is ADVISORY: it must warn on a
pre-existing infinite allowance yet never block a legitimate swap, including the
normal first-swap case where the spender has not been approved yet (allowance 0).

These tests stub the RPC layer, so they need no network and no key.

Run:  python3 -m unittest discover -s bnbhack/tests
"""

import asyncio
import os
import sys
import unittest

_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import tx_security_solver as solver  # noqa: E402

_TOKEN = "0x" + "1" * 40
_OWNER = "0x" + "2" * 40
_SPENDER = "0x" + "3" * 40


def _stub_result(result):
    async def _f(method, params):
        return result, None
    return _f


def _stub_unavailable():
    async def _f(method, params):
        return None, None
    return _f


class StandingAllowanceTest(unittest.TestCase):
    def setUp(self):
        self._orig = solver._rpc_call

    def tearDown(self):
        solver._rpc_call = self._orig

    def _check(self, plan):
        return asyncio.run(solver.check_standing_allowance(plan))

    def _plan(self, **kw):
        base = dict(sell_token=_TOKEN, owner=_OWNER, router=_SPENDER)
        base.update(kw)
        return solver.TradePlan(**base)

    def test_infinite_allowance_warns_but_never_blocks(self):
        solver._rpc_call = _stub_result("0x" + "f" * 64)  # 2**256-1
        r = self._check(self._plan(trade_amount=10 ** 18))
        self.assertEqual(r.status, solver.WARN)
        self.assertFalse(r.blocks)
        self.assertGreaterEqual(r.data["allowance"], solver._INFINITE_APPROVAL)

    def test_zero_allowance_passes_so_a_first_swap_is_not_blocked(self):
        solver._rpc_call = _stub_result("0x" + "0" * 64)
        r = self._check(self._plan(trade_amount=10 ** 18))
        self.assertEqual(r.status, solver.PASS)
        self.assertFalse(r.blocks)

    def test_finite_allowance_above_spend_warns(self):
        # allowance = 5e18, spend = 1e18
        solver._rpc_call = _stub_result("0x" + format(5 * 10 ** 18, "064x"))
        r = self._check(self._plan(trade_amount=10 ** 18))
        self.assertEqual(r.status, solver.WARN)
        self.assertFalse(r.blocks)

    def test_rpc_unavailable_skips_not_critical(self):
        solver._rpc_call = _stub_unavailable()
        r = self._check(self._plan(trade_amount=10 ** 18))
        self.assertEqual(r.status, solver.SKIP)
        self.assertTrue(r.data.get("unavailable"))
        self.assertNotIn("standing_allowance", solver._CRITICAL_CHECKS)

    def test_native_sell_token_skips_without_any_rpc(self):
        # Native BNB (zero sentinel) has no ERC-20 allowance leg; must not even read.
        solver._rpc_call = _stub_unavailable()
        r = self._check(self._plan(sell_token="0x" + "0" * 40))
        self.assertEqual(r.status, solver.SKIP)

    def test_missing_owner_skips(self):
        solver._rpc_call = _stub_unavailable()
        r = self._check(self._plan(owner=None))
        self.assertEqual(r.status, solver.SKIP)


if __name__ == "__main__":
    unittest.main()
