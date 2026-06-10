"""
MEFAI · token routing + native-destination gate + preflight calldata tests

Covers three audited properties:
  1. Every base the loop's _BSC_SPOT watchlist can emit resolves through the
     SAME token lookup quote()/swap() use, and assert_routable surfaces any
     base that does not (fail-fast at startup instead of a mid-loop swap error).
  2. A swap whose destination is native BNB builds a TradePlan that carries the
     canonical WBNB address, so the strict security gate scans the wrapped
     asset rather than blocking on token_required / coverage.
  3. check_preflight FAILs calldata that is present but malformed or oversized
     instead of silently dropping it and certifying an empty eth_call.

These tests stub the RPC/proxy layers, so they need no network and no key.

Run:  python3 -m unittest discover -s bnbhack/tests
"""

import asyncio
import os
import sys
import unittest

_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import bsc_exec  # noqa: E402
import tx_security_solver as solver  # noqa: E402

# Literal copy of the base list from loop.py _BSC_SPOT. Kept literal on purpose:
# if loop.py grows a base that bsc_exec cannot route, this test must fail.
_BSC_SPOT_BASES = ["ETH", "XRP", "ADA", "DOGE", "CAKE",
                   "LINK", "AVAX", "AAVE", "ATOM", "LTC"]

_WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
_FROM = "0x" + "2" * 40
_TO = "0x" + "3" * 40


class TestSpotBasesRoutable(unittest.TestCase):
    def test_every_spot_base_resolves(self):
        for base in _BSC_SPOT_BASES:
            addr = bsc_exec._resolve_token(base)
            self.assertIsNotNone(addr, f"{base} does not resolve in BSC_TOKENS")
            self.assertRegex(addr, r"^0x[0-9a-f]{40}$")

    def test_assert_routable_empty_for_full_list(self):
        self.assertEqual(bsc_exec.assert_routable(_BSC_SPOT_BASES), [])

    def test_assert_routable_flags_fake_base(self):
        missing = bsc_exec.assert_routable(_BSC_SPOT_BASES + ["FAKECOIN"])
        self.assertEqual(missing, ["FAKECOIN"])


class TestNativeDestinationPlan(unittest.TestCase):
    def test_native_bnb_plan_carries_wbnb_token(self):
        qbody = {"output": "1.23", "minReceived": "1.20"}
        plan = bsc_exec._quote_to_plan(
            qbody, bsc_exec.BSC_TOKENS["BNB"], 1.0, None, None)
        self.assertEqual(plan.token, _WBNB)

    def test_erc20_destination_unchanged(self):
        qbody = {"output": "1.23", "minReceived": "1.20"}
        usdt = bsc_exec.BSC_TOKENS["USDT"]
        plan = bsc_exec._quote_to_plan(qbody, usdt, 1.0, None, None)
        self.assertEqual(plan.token, usdt)

    def test_strict_gate_does_not_block_native_destination(self):
        """evaluate_trade on a BNB-destination plan must not raise the
        token_required or coverage blockers (the C33 regression)."""
        async def proxy_stub(path, params):
            if "honeypot" in path:
                return {"verdict": "SAFE", "buyTax": 0, "sellTax": 0, "flags": []}
            return {"verified": True, "risks": [],
                    "honeypot": {"roundTripLossPct": 0.0},
                    "proxy": {"isProxy": False}}

        async def rpc_stub(method, params):
            return "0x", None

        orig_proxy, orig_rpc = solver._proxy_get, solver._rpc_call
        solver._proxy_get, solver._rpc_call = proxy_stub, rpc_stub
        try:
            qbody = {"output": "1.23", "minReceived": "1.20"}
            plan = bsc_exec._quote_to_plan(
                qbody, bsc_exec.BSC_TOKENS["BNB"], 1.0, None, None)
            verdict = asyncio.run(solver.evaluate_trade(plan, strict=True))
        finally:
            solver._proxy_get, solver._rpc_call = orig_proxy, orig_rpc
        self.assertNotIn("token_required", verdict.blockers)
        self.assertNotIn("coverage", verdict.blockers)
        self.assertTrue(verdict.go, verdict.detail)


class TestPreflightCalldataValidation(unittest.TestCase):
    def _run(self, tx):
        plan = solver.TradePlan(tx=tx)
        return asyncio.run(solver.check_preflight(plan))

    def test_malformed_data_fails(self):
        res = self._run({"from": _FROM, "to": _TO, "data": "zz-not-hex"})
        self.assertEqual(res.status, solver.FAIL)
        self.assertIn("calldata malformed or oversized", res.detail)

    def test_oversized_data_fails(self):
        big = "0x" + "a" * (solver._MAX_CALLDATA_HEX + 2)
        res = self._run({"from": _FROM, "to": _TO, "data": big})
        self.assertEqual(res.status, solver.FAIL)
        self.assertIn("not simulated", res.detail)

    def test_non_string_data_fails(self):
        res = self._run({"from": _FROM, "to": _TO, "data": 12345})
        self.assertEqual(res.status, solver.FAIL)

    def test_absent_data_keeps_prior_behavior(self):
        async def rpc_stub(method, params):
            return "0x", None
        orig = solver._rpc_call
        solver._rpc_call = rpc_stub
        try:
            res = self._run({"from": _FROM, "to": _TO})
        finally:
            solver._rpc_call = orig
        self.assertEqual(res.status, solver.PASS)


if __name__ == "__main__":
    unittest.main()
