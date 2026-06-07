"""
MEFAI BNB HACK · Pre-Trade Transaction Security Solver

The solver: a single safety gate that EVERY on-chain trade must clear before
the agent is allowed to spend. It fuses the MEFAI on-chain analysis stack (the
local proxy's token-risk, honeypot, and contract-reader endpoints) with its own
preflight simulation, slippage / approval / gas hygiene, an MEV exposure read,
and the RiskGovernor equity-floor authorization into ONE go / block verdict.

Design:
- Every check returns a CheckResult and NEVER raises; an adapter that cannot
  answer degrades to SKIP rather than crashing the gate.
- A single FAIL blocks the trade (`go=False`). WARN lowers the score but does not
  block. SKIP means the input was absent for that check.
- FAIL-CLOSED policy: in strict mode (the default) a security-critical check
  (token risk, contract scan, preflight) that cannot reach its data source while
  a trade is actually intended is treated as a BLOCK, not a silent pass. An
  outage of the analysis stack must never authorize an unvetted trade.
- Network access is limited to the LOCAL trusted proxy (127.0.0.1) and a fixed
  allowlist of public BSC RPC hosts, so no part of a trade plan can redirect a
  request elsewhere (no SSRF surface).

Convention: amounts are integer wei unless a field says otherwise. Addresses are
validated to the 0x + 40 hex form before any use.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

# Local trusted proxy that fronts the MEFAI on-chain analysis endpoints. Default
# is loopback; an operator may override the host but a trade plan never can.
PROXY_BASE = os.getenv("MEFAI_PROXY_URL", "http://127.0.0.1:8210").rstrip("/")

# Public BSC JSON-RPC endpoints used for preflight eth_call and gas baseline.
# Only these hosts are ever contacted; any other host is refused before a request
# is made, so the RPC client cannot be pointed at an attacker-chosen target.
_RPC_ENDPOINTS = [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.ninicoin.io",
    "https://bsc.publicnode.com",
]
_ALLOWED_RPC_HOSTS = {urlsplit(u).hostname for u in _RPC_ENDPOINTS}

_ZERO_ADDR = "0x" + "0" * 40
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]*$")
# Any allowance at or above this is treated as an unlimited / infinite approval.
_INFINITE_APPROVAL = 1 << 255
# Solidity Error(string) and Panic(uint256) selectors used to detect a revert.
_ERROR_SELECTOR = "08c379a0"
_PANIC_SELECTOR = "4e487b71"

# Default risk thresholds (overridable per call via TradePlan).
MAX_SLIPPAGE_BPS = 300        # 3.0% hard cap on tolerated slippage
MEV_SLIPPAGE_WARN_BPS = 100   # >1.0% tolerated slippage flags sandwich exposure
GAS_PRICE_MAX_MULT = 3.0      # gas price above 3x the network baseline is refused
# BSC gas is cheap and its eth_gasPrice baseline can read as low as ~0.05 gwei,
# so a pure ratio test would block a perfectly normal 1-3 gwei tx. Any gas price
# at or below this absolute floor is always sane regardless of the baseline; the
# ratio test only applies above it.
GAS_ALWAYS_SANE_WEI = 5 * 10**9   # 5 gwei
GAS_ABSURD_WEI = 5000 * 10**9     # > 5000 gwei is never sane on BSC
HONEYPOT_LOSS_FAIL = 50.0     # contract-reader round-trip loss% that blocks
HONEYPOT_LOSS_WARN = 15.0     # round-trip loss% that warns
TAX_FAIL_PCT = 20.0           # buy or sell tax at/above this blocks
TAX_WARN_PCT = 8.0            # buy or sell tax at/above this warns

_HTTP_TIMEOUT = 6.0
# Reject an analysis-source response larger than this; a trusted local proxy or a
# public RPC never needs to return more, and an unbounded body could exhaust memory.
_MAX_RESPONSE_BYTES = 512 * 1024
# A revert payload above this is decoded only up to the cap.
_MAX_REVERT_HEX = 8192
# Calldata larger than this is not forwarded to the RPC node (sane upper bound).
_MAX_CALLDATA_HEX = 256 * 1024

# Score penalties (advisory; the authoritative gate is `go`, not the score).
SCORE_PENALTY_FAIL = 35.0
SCORE_PENALTY_WARN = 10.0
SCORE_PENALTY_CRITICAL_SKIP = 20.0   # an unavailable security-critical source
# Gas: warn band starts at this fraction of the hard multiplier.
GAS_WARN_BAND = 0.66

# Checks whose failure or unavailability must block in strict (fail-closed) mode.
_CRITICAL_CHECKS = {"token_risk", "contract_scan", "preflight_sim"}


def _finite(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _to_int(x: Any) -> Optional[int]:
    """Parse an integer amount that may arrive as int, decimal string, or 0x hex.
    Returns None when it cannot be parsed (so a check can SKIP rather than guess)."""
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return int(x) if math.isfinite(x) else None
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return None
        try:
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            return None
    return None


def _is_addr(a: Any) -> bool:
    return isinstance(a, str) and bool(_ADDR_RE.match(a.strip()))


def _norm_addr(a: Any) -> Optional[str]:
    if not _is_addr(a):
        return None
    return a.strip().lower()


def _decode_revert(data: Any) -> str:
    """Best-effort decode of a revert payload. The standard Error(string) selector
    is 0x08c379a0 followed by an ABI-encoded string. The input is capped first so a
    hostile payload cannot drive a large allocation."""
    if not isinstance(data, str) or not data.startswith("0x"):
        return ""
    body = data[2:_MAX_REVERT_HEX]
    if body[:8].lower() == _ERROR_SELECTOR and len(body) >= 8 + 64 + 64:
        try:
            # Clamp the claimed length to what is actually present so an inflated
            # length field cannot allocate beyond the (already capped) payload.
            length = int(body[8 + 64:8 + 128], 16)
            avail = (len(body) - (8 + 128)) // 2
            length = max(0, min(length, avail))
            raw = bytes.fromhex(body[8 + 128:8 + 128 + length * 2])
            return raw.decode("utf-8", "replace")
        except (ValueError, UnicodeDecodeError):
            return ""
    return ""


def _is_revert_payload(data: Any) -> bool:
    """True when an eth_call RESULT itself carries a revert selector. Some RPC
    nodes return reverts as the call output rather than as a JSON-RPC error, so a
    PASS must not be inferred from a 0x08c379a0/Panic result blob."""
    if not isinstance(data, str) or not data.startswith("0x"):
        return False
    sel = data[2:10].lower()
    return sel in (_ERROR_SELECTOR, _PANIC_SELECTOR)


def _effective_slippage_bps(plan: "TradePlan") -> Optional[int]:
    """Single slippage-bps derivation shared by the slippage and MEV checks so
    both assess the SAME tolerance. Prefers an explicit min_out vs expected_out
    quote, falling back to a stated slippage_bps."""
    exp = _to_int(plan.expected_out)
    mout = _to_int(plan.min_out)
    if exp is not None and mout is not None and exp > 0 and 0 < mout <= exp:
        # Ceil so a sub-bp loss is never rounded down to under-report slippage.
        return math.ceil((exp - mout) / exp * 10000)
    return _to_int(plan.slippage_bps)


# --- adapters (network, all non-raising) -----------------------------------

def _too_large(r: "httpx.Response") -> bool:
    clen = r.headers.get("content-length")
    if clen is not None:
        try:
            if int(clen) > _MAX_RESPONSE_BYTES:
                return True
        except ValueError:
            pass
    return len(r.content) > _MAX_RESPONSE_BYTES


async def _proxy_get(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{PROXY_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200 or _too_large(r):
                return None
            body = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    # Only an object is usable; a list/scalar would make later .get() calls raise.
    return body if isinstance(body, dict) else None


async def _rpc_call(method: str, params: List[Any]) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """Call the allowlisted BSC RPC endpoints in order until one answers.
    Returns (result, error) where at most one is non-None. Both None means every
    endpoint was unreachable."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for url in _RPC_ENDPOINTS:
        host = urlsplit(url).hostname
        if host not in _ALLOWED_RPC_HOSTS:
            continue  # defensive: never contact a non-allowlisted host
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                r = await client.post(url, json=payload)
                if r.status_code != 200 or _too_large(r):
                    continue
                body = r.json()
            if not isinstance(body, dict):
                continue
            if body.get("error"):
                return None, body["error"]
            return body.get("result"), None
        except (httpx.HTTPError, ValueError):
            continue
    return None, None


# --- result model ----------------------------------------------------------

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


@dataclass
class CheckResult:
    name: str
    status: str               # PASS / WARN / FAIL / SKIP
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.status == FAIL


@dataclass
class TradePlan:
    """The intended on-chain trade to vet. Every field is optional: a missing
    field makes the dependent check SKIP rather than fail, so the gate can be run
    on a partial plan and tightened as more of the trade is known."""

    token: Optional[str] = None            # token being bought/sold
    router: Optional[str] = None           # DEX router / spender to approve
    chain_id: int = 56
    # slippage
    expected_out: Optional[int] = None     # quoted output (wei/base units)
    min_out: Optional[int] = None          # enforced minimum output
    slippage_bps: Optional[int] = None     # tolerated slippage in basis points
    max_slippage_bps: int = MAX_SLIPPAGE_BPS
    # approval hygiene
    approval_amount: Optional[int] = None  # allowance about to be granted
    trade_amount: Optional[int] = None     # amount the trade will actually spend
    # preflight
    tx: Optional[Dict[str, Any]] = None    # {from,to,data,value} for eth_call
    # gas
    gas_price_wei: Optional[int] = None
    gas_limit: Optional[int] = None
    gas_price_max_mult: float = GAS_PRICE_MAX_MULT
    # RiskGovernor authorization
    equity: Optional[float] = None         # current account equity
    equity_floor: Optional[float] = None   # bonded drawdown kill-switch floor


@dataclass
class SecurityVerdict:
    go: bool
    score: float                       # 0-100 confidence the trade is safe
    checks: List[CheckResult] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    detail: str = ""


# --- pure checks -----------------------------------------------------------

def check_addresses(plan: TradePlan) -> CheckResult:
    bad: List[str] = []
    for label, val in (("token", plan.token), ("router", plan.router)):
        if val is None:
            continue
        norm = _norm_addr(val)
        if norm is None:
            bad.append(f"{label} not a valid address")
        elif norm == _ZERO_ADDR:
            bad.append(f"{label} is the zero address")
    if bad:
        return CheckResult("address_validation", FAIL, "; ".join(bad))
    if plan.token is None and plan.router is None:
        return CheckResult("address_validation", SKIP, "no addresses supplied")
    return CheckResult("address_validation", PASS, "addresses well-formed")


def check_slippage(plan: TradePlan) -> CheckResult:
    cap_raw = _to_int(plan.max_slippage_bps)
    cap = max(0, cap_raw) if cap_raw is not None else MAX_SLIPPAGE_BPS
    # Prefer an explicit min_out vs expected_out, else fall back to slippage_bps.
    exp = _to_int(plan.expected_out)
    mout = _to_int(plan.min_out)
    if exp is not None and mout is not None:
        if exp <= 0:
            return CheckResult("slippage_guard", SKIP, "no positive quote")
        if mout <= 0:
            return CheckResult("slippage_guard", FAIL,
                               "min_out is zero: unbounded slippage")
        if mout > exp:
            return CheckResult("slippage_guard", WARN,
                               "min_out exceeds quote (stale quote?)")
        # Ceil so a sub-bp loss is never rounded down to under-report slippage.
        bps = math.ceil((exp - mout) / exp * 10000)
        data = {"slippage_bps": bps, "cap_bps": cap}
        if bps > cap:
            return CheckResult("slippage_guard", FAIL,
                               f"slippage {bps}bps over cap {cap}bps", data)
        return CheckResult("slippage_guard", PASS,
                           f"slippage {bps}bps within cap {cap}bps", data)
    bps = _to_int(plan.slippage_bps)
    if bps is not None:
        data = {"slippage_bps": bps, "cap_bps": cap}
        if bps < 0:
            return CheckResult("slippage_guard", FAIL, "negative slippage", data)
        if bps > cap:
            return CheckResult("slippage_guard", FAIL,
                               f"slippage {bps}bps over cap {cap}bps", data)
        return CheckResult("slippage_guard", PASS,
                           f"slippage {bps}bps within cap {cap}bps", data)
    return CheckResult("slippage_guard", SKIP, "no slippage inputs")


def check_approval(plan: TradePlan) -> CheckResult:
    if plan.approval_amount is None:
        return CheckResult("approval_hygiene", SKIP, "no approval in plan")
    appr = _to_int(plan.approval_amount)
    if appr is None:
        return CheckResult("approval_hygiene", SKIP, "approval not a number")
    if appr < 0:
        return CheckResult("approval_hygiene", FAIL, "negative approval")
    if appr >= _INFINITE_APPROVAL:
        return CheckResult("approval_hygiene", FAIL,
                           "infinite / unlimited approval requested; "
                           "grant the exact spend amount instead")
    spend = _to_int(plan.trade_amount)
    if spend is None:
        return CheckResult("approval_hygiene", WARN,
                           "finite approval but no trade_amount to compare")
    if appr < spend:
        return CheckResult("approval_hygiene", FAIL,
                           "approval below the trade amount; spend would revert")
    if appr > spend:
        return CheckResult("approval_hygiene", WARN,
                           "approval exceeds the trade amount; approve exact and "
                           "revoke after settlement",
                           {"approval": appr, "spend": spend})
    return CheckResult("approval_hygiene", PASS,
                       "exact-amount approval", {"approval": appr})


def check_mev(plan: TradePlan) -> CheckResult:
    # MEV / sandwich exposure is a function of how loose the slippage tolerance is.
    # Use the same derivation as the slippage check so both assess one tolerance.
    bps = _effective_slippage_bps(plan)
    if bps is None:
        return CheckResult("mev_guard", SKIP, "no slippage to assess")
    if bps > MEV_SLIPPAGE_WARN_BPS:
        return CheckResult("mev_guard", WARN,
                           f"slippage {bps}bps invites sandwich extraction; use a "
                           "private route or tighten tolerance",
                           {"slippage_bps": bps})
    return CheckResult("mev_guard", PASS,
                       f"slippage {bps}bps tight enough to deter sandwiching",
                       {"slippage_bps": bps})


def check_risk_governor(plan: TradePlan) -> CheckResult:
    if plan.equity is None or plan.equity_floor is None:
        return CheckResult("risk_governor", SKIP, "no equity / floor supplied")
    equity = _finite(plan.equity, 0.0)
    floor = _finite(plan.equity_floor, 0.0)
    if equity < floor:
        return CheckResult("risk_governor", FAIL,
                           f"equity {equity:.2f} below bonded floor {floor:.2f}; "
                           "kill-switch engaged, no new trade authorized",
                           {"equity": equity, "floor": floor})
    return CheckResult("risk_governor", PASS,
                       f"equity {equity:.2f} above floor {floor:.2f}",
                       {"equity": equity, "floor": floor})


# --- network checks --------------------------------------------------------

async def check_token_risk(plan: TradePlan) -> CheckResult:
    token = _norm_addr(plan.token)
    if token is None:
        return CheckResult("token_risk", SKIP, "no valid token")
    body = await _proxy_get("/bsc-honeypot-check", {"address": token})
    if not body:
        return CheckResult("token_risk", SKIP, "risk source unavailable",
                           {"unavailable": True})
    verdict = str(body.get("verdict", "")).upper()
    buy_tax = _finite(body.get("buyTax"), 0.0)
    sell_tax = _finite(body.get("sellTax"), 0.0)
    flags = body.get("flags") or []
    flag_labels = {str(f.get("label", "")).lower() for f in flags if isinstance(f, dict)}
    data = {"verdict": verdict, "buyTax": buy_tax, "sellTax": sell_tax}
    hard = {"honeypot", "cannot_sell_all", "cannot sell", "selfdestruct"}
    if verdict == "DANGER" or flag_labels & hard:
        return CheckResult("token_risk", FAIL,
                           f"token flagged {verdict or 'DANGER'}", data)
    worst_tax = max(buy_tax, sell_tax)
    if worst_tax >= TAX_FAIL_PCT:
        return CheckResult("token_risk", FAIL,
                           f"tax too high (buy {buy_tax:.1f}% sell {sell_tax:.1f}%)",
                           data)
    if verdict == "RISKY" or worst_tax >= TAX_WARN_PCT:
        return CheckResult("token_risk", WARN,
                           f"elevated risk {verdict} (buy {buy_tax:.1f}% "
                           f"sell {sell_tax:.1f}%)", data)
    return CheckResult("token_risk", PASS,
                       f"token risk {verdict or 'SAFE'}", data)


async def check_contract(plan: TradePlan) -> CheckResult:
    token = _norm_addr(plan.token)
    if token is None:
        return CheckResult("contract_scan", SKIP, "no valid token")
    body = await _proxy_get("/contract-reader", {"address": token})
    if not body:
        return CheckResult("contract_scan", SKIP, "contract source unavailable",
                           {"unavailable": True})
    risks = body.get("risks") or []
    crit = [r for r in risks if isinstance(r, dict)
            and str(r.get("sev", "")).lower() in ("crit", "critical")]
    honeypot = body.get("honeypot") or {}
    loss = _finite(honeypot.get("roundTripLossPct"), -1.0)
    proxy = (body.get("proxy") or {}).get("isProxy")
    verified = bool(body.get("verified"))
    data = {"verified": verified, "isProxy": bool(proxy),
            "roundTripLossPct": loss, "n_risks": len(risks)}

    if loss >= HONEYPOT_LOSS_FAIL:
        return CheckResult("contract_scan", FAIL,
                           f"round-trip loss {loss:.1f}% indicates honeypot/high tax",
                           data)
    if crit:
        msgs = ", ".join(str(r.get("code") or r.get("msg")) for r in crit[:3])
        return CheckResult("contract_scan", FAIL,
                           f"critical contract risk: {msgs}", data)
    warn_bits: List[str] = []
    if 0 <= loss < HONEYPOT_LOSS_FAIL and loss >= HONEYPOT_LOSS_WARN:
        warn_bits.append(f"round-trip loss {loss:.1f}%")
    if proxy:
        warn_bits.append("upgradeable proxy")
    if not verified:
        warn_bits.append("source unverified")
    high = [r for r in risks if isinstance(r, dict)
            and str(r.get("sev", "")).lower() == "high"]
    if high:
        warn_bits.append(f"{len(high)} high-severity pattern(s)")
    if warn_bits:
        return CheckResult("contract_scan", WARN, "; ".join(warn_bits), data)
    return CheckResult("contract_scan", PASS, "no critical contract risk", data)


async def check_preflight(plan: TradePlan) -> CheckResult:
    tx = plan.tx
    if not isinstance(tx, dict):
        return CheckResult("preflight_sim", SKIP, "no tx to simulate")
    to = _norm_addr(tx.get("to"))
    frm = _norm_addr(tx.get("from"))
    if to is None or frm is None:
        return CheckResult("preflight_sim", SKIP, "tx missing valid from/to")
    call: Dict[str, Any] = {"from": frm, "to": to}
    data_field = tx.get("data")
    # Only forward well-formed, length-bounded calldata to the node.
    if (isinstance(data_field, str) and len(data_field) <= _MAX_CALLDATA_HEX
            and _HEX_RE.match(data_field)):
        call["data"] = data_field
    value = _to_int(tx.get("value"))
    if value is not None and value > 0:
        call["value"] = hex(value)
    result, error = await _rpc_call("eth_call", [call, "latest"])
    if error is not None:
        reason = _decode_revert(error.get("data")) if isinstance(error, dict) else ""
        msg = error.get("message", "reverted") if isinstance(error, dict) else "reverted"
        detail = f"preflight reverted: {reason or msg}"
        return CheckResult("preflight_sim", FAIL, detail,
                           {"revert": reason or msg})
    # Some nodes return a revert as the call OUTPUT rather than a JSON-RPC error;
    # a result that carries a revert selector must not be read as success.
    if _is_revert_payload(result):
        reason = _decode_revert(result)
        return CheckResult("preflight_sim", FAIL,
                           f"preflight reverted: {reason or 'execution reverted'}",
                           {"revert": reason or "execution reverted"})
    if result is None:
        return CheckResult("preflight_sim", SKIP, "no RPC endpoint answered",
                           {"unavailable": True})
    return CheckResult("preflight_sim", PASS, "preflight simulation succeeded")


async def check_gas(plan: TradePlan) -> CheckResult:
    if plan.gas_price_wei is None:
        return CheckResult("gas_sanity", SKIP, "no gas price in plan")
    gp = _to_int(plan.gas_price_wei)
    if gp is None:
        return CheckResult("gas_sanity", SKIP, "gas price not a number")
    if gp <= 0:
        return CheckResult("gas_sanity", FAIL, "non-positive gas price")
    # An absurd absolute value is always blocked, whatever the baseline says.
    if gp > GAS_ABSURD_WEI:
        return CheckResult("gas_sanity", FAIL,
                           "gas price absurdly high", {"gas_price_wei": gp})
    # A cheap, normal BSC gas price is never blocked on ratio alone.
    if gp <= GAS_ALWAYS_SANE_WEI:
        return CheckResult("gas_sanity", PASS,
                           f"gas price {gp/10**9:.2f} gwei within sane range",
                           {"gas_price_wei": gp})
    baseline_hex, _err = await _rpc_call("eth_gasPrice", [])
    baseline = _to_int(baseline_hex)
    mult = max(1.0, _finite(plan.gas_price_max_mult, GAS_PRICE_MAX_MULT))
    # Floor the baseline at the always-sane level so a near-zero reported baseline
    # cannot turn a normal gas price into a huge multiple.
    if baseline and baseline > 0:
        ref = max(baseline, GAS_ALWAYS_SANE_WEI)
        ratio = gp / ref
        data = {"gas_price_wei": gp, "baseline_wei": baseline,
                "ref_wei": ref, "ratio": round(ratio, 2)}
        if ratio > mult:
            return CheckResult("gas_sanity", FAIL,
                               f"gas price {ratio:.1f}x the sane baseline; "
                               "likely a misconfigured or attacked tx", data)
        if ratio > mult * GAS_WARN_BAND:
            return CheckResult("gas_sanity", WARN,
                               f"gas price {ratio:.1f}x baseline (elevated)", data)
        return CheckResult("gas_sanity", PASS,
                           f"gas price {ratio:.1f}x baseline", data)
    return CheckResult("gas_sanity", SKIP, "no gas baseline to compare")


# --- orchestrator ----------------------------------------------------------

def _has_trade_intent(plan: TradePlan) -> bool:
    """True when the plan actually intends to move funds, so a missing token or an
    unreachable analysis source is a real gap rather than an empty probe."""
    return any(v is not None for v in (
        plan.tx, plan.router, plan.approval_amount, plan.trade_amount,
        plan.expected_out, plan.min_out, plan.slippage_bps,
    ))


async def evaluate_trade(plan: TradePlan, strict: bool = True) -> SecurityVerdict:
    """Run every safety check and fold them into one go / block verdict.

    The network checks run concurrently; the pure checks run inline. The trade is
    authorized (`go=True`) only when no check FAILs AND, in strict mode, every
    security-critical check actually ran. The score is advisory; `go` is the gate.

    strict (default True) enforces FAIL-CLOSED behavior:
      - a security-critical check (token risk, contract scan, preflight) whose
        data source is unreachable while a trade is intended becomes a BLOCK;
      - a trade that intends to spend but supplies no valid token (so it cannot be
        honeypot/contract scanned at all) is BLOCKED;
      - a plan with trade intent but no security-critical check that produced a
        real PASS/WARN/FAIL verdict is BLOCKED as insufficiently vetted.
    """
    intent = _has_trade_intent(plan)
    pure = [
        check_addresses(plan),
        check_slippage(plan),
        check_approval(plan),
        check_mev(plan),
        check_risk_governor(plan),
    ]

    # Only probe token/contract when the token address is well-formed, so we never
    # forward malformed input to the network adapters.
    token_ok = _norm_addr(plan.token) is not None
    net_coros = [check_preflight(plan), check_gas(plan)]
    if token_ok:
        net_coros = [check_token_risk(plan), check_contract(plan)] + net_coros
    net = await asyncio.gather(*net_coros)

    checks: List[CheckResult] = pure + list(net)

    # FAIL-CLOSED escalations (strict mode only).
    if strict and intent:
        # 1. A spend with no valid token cannot be honeypot/contract scanned.
        if not token_ok:
            checks.append(CheckResult(
                "token_required", FAIL,
                "trade intends to spend but supplies no valid token to vet"))
        # 2. An unreachable security-critical source must not pass silently.
        for c in checks:
            if (c.name in _CRITICAL_CHECKS and c.status == SKIP
                    and c.data.get("unavailable")):
                c.status = FAIL
                c.detail = f"{c.detail} (blocked: source unavailable, fail-closed)"
        # 3. Demand that at least one security-critical check actually verdicted.
        verdicted = any(c.name in _CRITICAL_CHECKS and c.status in (PASS, WARN, FAIL)
                        for c in checks)
        if not verdicted:
            checks.append(CheckResult(
                "coverage", FAIL,
                "no security-critical check could verdict this trade"))

    blockers = [c.name for c in checks if c.status == FAIL]
    warnings = [c.name for c in checks if c.status == WARN]
    go = len(blockers) == 0

    score = 100.0
    for c in checks:
        if c.status == FAIL:
            score -= SCORE_PENALTY_FAIL
        elif c.status == WARN:
            score -= SCORE_PENALTY_WARN
        elif (c.status == SKIP and c.name in _CRITICAL_CHECKS
              and c.data.get("unavailable")):
            score -= SCORE_PENALTY_CRITICAL_SKIP
    score = max(0.0, min(100.0, score))
    # The score must never imply safety for a blocked trade.
    if not go:
        score = min(score, 40.0)

    if not go:
        detail = f"BLOCK: {len(blockers)} failing check(s): " + ", ".join(blockers)
    elif warnings:
        detail = f"GO with {len(warnings)} warning(s): " + ", ".join(warnings)
    else:
        detail = "GO: all checks passed"

    return SecurityVerdict(
        go=go, score=round(score, 1), checks=checks,
        blockers=blockers, warnings=warnings, detail=detail,
    )
