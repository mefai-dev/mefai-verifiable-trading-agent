"""
MEFAI BNB HACK · BSC execution adapter (Trust Wallet Agent Kit wrapper)

This is the agent's hands: the one module allowed to move real funds on BSC. It
wraps the Trust Wallet Agent Kit CLI (`twak`) self-custody wallet for spot swaps
(PancakeSwap-class routing via the 0x aggregator), native/token transfers, and
balance reads. Perps (ApolloX) are NOT routed here; twak has no perp primitive,
so leveraged exposure stays on the CEX adapter (autotrade/exchange_adapter.py)
and is documented as a follow-on, not silently faked.

Safety architecture (defence in depth):
  1. Every spend is gated through `tx_security_solver.evaluate_trade` FIRST. A
     swap or transfer that the solver blocks is never handed to the wallet. The
     gate runs in strict / fail-closed mode: an unreachable risk source blocks.
  2. The wallet password is NEVER placed on argv (it would leak via `ps`/proc).
     twak reads it from the TWAK_WALLET_PASSWORD env we pass to the child only.
  3. Subprocesses are spawned with an explicit argv list (no shell), so a token
     symbol or address can never be interpreted as a shell command.
  4. Token symbols resolve through a fixed BSC registry; an arbitrary string is
     accepted only when it is a well-formed 0x address, which is then risk-vetted
     by the solver before any approval or swap.
  5. Quote-only is the default. Execution requires execute=True AND a passing
     verdict AND a configured wallet password.

READ-PATHS (quote, balance) need no password and never move funds. WRITE-PATHS
(swap execute, transfer) are the only ones that sign.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from tx_security_solver import TradePlan, SecurityVerdict, evaluate_trade

logger = logging.getLogger("mefai.bnbhack.bsc_exec")

# twak binary. Resolved once; an unset/renamed binary degrades to a clean error
# rather than a shell lookup at call time.
TWAK_BIN = os.getenv("TWAK_BIN") or shutil.which("twak") or "/usr/bin/twak"

CHAIN = "bsc"
CHAIN_ID = 56
# Trust Wallet coin type for BNB Smart Chain. The transfer command requires a
# token asset id (c<coinId> for native, c<coinId>_t<contract> for a BEP-20); it
# has no --chain flag, so the asset id is the only chain selector for a transfer.
BSC_COIN_ID = 20000714

# Wall-clock caps so a hung CLI can never block the agent loop indefinitely.
QUOTE_TIMEOUT = 25.0
EXEC_TIMEOUT = 120.0
BALANCE_TIMEOUT = 25.0
# A CLI response above this is rejected; twak never needs more and an unbounded
# stdout could exhaust memory.
_MAX_OUTPUT_BYTES = 1 << 20  # 1 MiB

# Hard policy caps independent of the solver (the solver is per-token; these are
# blanket spend guards so a logic bug upstream cannot size an absurd order). The
# USD cap is enforced from the QUOTE where possible, not from a caller-asserted
# figure, and fails closed when no notional can be derived for an execute.
MAX_SWAP_USD = float(os.getenv("BSC_MAX_SWAP_USD", "250"))
MAX_TRANSFER_USD = float(os.getenv("BSC_MAX_TRANSFER_USD", "100"))
MAX_SLIPPAGE_PCT = 3.0          # mirrors solver MAX_SLIPPAGE_BPS (300 bps)
MIN_SLIPPAGE_PCT = 0.05
# Price-impact (route depth) guard. twak returns priceImpact as a percent; a
# thin / illiquid route is the real slippage hazard the requested-tolerance check
# cannot see, so it is blocked / warned here from the live quote.
MAX_PRICE_IMPACT_PCT = 5.0
WARN_PRICE_IMPACT_PCT = 1.0
# Absolute per-symbol native-unit backstop, independent of any USD figure, so a
# missing or low approx_usd still cannot authorise an oversized order. Tokens not
# listed fall back to the USD gate (which fails closed for an execute).
MAX_NATIVE_PER_SWAP: Dict[str, float] = {
    "BNB": 0.5, "WBNB": 0.5,
    "USDT": 250.0, "USDC": 250.0, "BUSD": 250.0,
    "BTCB": 0.004, "ETH": 0.08, "SOL": 1.7,
    "CAKE": 120.0, "XRP": 120.0, "ADA": 400.0, "DOGE": 1500.0,
}
# Stablecoins whose unit value is ~1 USD, used to derive a swap notional from the
# quote without an external price feed.
_USD_STABLES = {"USDT", "USDC", "BUSD"}

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
# Symbols we will ever name to the CLI. A symbol outside this set must be given
# as a 0x address instead, so a typo never resolves to an unintended token.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{2,12}$")

# Canonical BSC token addresses for the assets the agent trades. Used to feed the
# security solver a concrete token to honeypot/contract scan. BNB is native (no
# token contract) so it carries the zero sentinel and skips token-risk scanning.
BSC_TOKENS: Dict[str, str] = {
    "BNB": "0x0000000000000000000000000000000000000000",
    "WBNB": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
    "USDT": "0x55d398326f99059ff775485246999027b3197955",
    "USDC": "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
    "BUSD": "0xe9e7cea3dedca5984780bafc599bd69add087d56",
    "BTCB": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",
    "ETH": "0x2170ed0880ac9a755fd29b2688956bd959f933f8",
    "CAKE": "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82",
    "XRP": "0x1d2f0da169ceb9fc7b3144628db156f3f6c60dbe",
    "ADA": "0x3ee2200efb3400fabb9aacf31297cbdd1d435d47",
    "DOGE": "0xba2ae424d960c26247dd6c32edc70b295c744c43",
    "SOL": "0x570a5d26f7765ecb712c0924e4de545b89fd43df",
}

# 0x Exchange Proxy on BSC: the spender twak's swap route approves. Surfaced so
# the solver can vet the router/spender of a swap, not just the bought token.
ZEROX_PROXY_BSC = "0xdef1c0ded9bec7f1a1670819833240f027b25eff"

# Public agent wallet (the `from` for a preflight eth_call). Read-only address;
# never a key. Absent => preflight has no sender and degrades to a SKIP.
AGENT_WALLET = (os.getenv("TWAK_AGENT_WALLET") or "").strip()


def _is_addr(v: Any) -> bool:
    return isinstance(v, str) and bool(_ADDR_RE.match(v.strip()))


def _resolve_token(sym_or_addr: str) -> Optional[str]:
    """Map a trading symbol to its BSC address, or accept a raw 0x address.
    Returns None for anything that is neither, so the caller rejects it before
    any CLI or network use."""
    if not isinstance(sym_or_addr, str):
        return None
    s = sym_or_addr.strip()
    if _is_addr(s):
        return s.lower()
    up = s.upper()
    if up in BSC_TOKENS:
        return BSC_TOKENS[up]
    return None


def _cli_token_arg(sym_or_addr: str) -> Optional[str]:
    """The exact argument handed to `twak swap` for a token leg. A known symbol
    is passed verbatim (twak resolves it); a raw address is passed as-is. Anything
    that is neither a clean symbol nor a 0x address is refused (no injection)."""
    if not isinstance(sym_or_addr, str):
        return None
    s = sym_or_addr.strip()
    if _is_addr(s):
        return s.lower()
    if _SYMBOL_RE.match(s) and s.upper() in BSC_TOKENS:
        return s.upper()
    return None


# Only these vars are handed to the twak child. The password and the kit
# credentials reach the CLI out-of-band (never via argv); every OTHER secret in
# the service environment is withheld so a child / its deps cannot read or log it.
_CHILD_ENV_ALLOW = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "NODE_OPTIONS",
    "TWAK_ACCESS_ID", "TWAK_HMAC_SECRET", "TWAK_WALLET_PASSWORD",
    "TWAK_AGENT_ID", "TWAK_AGENT_WALLET", "TWAK_BIN",
)


def _child_env() -> Dict[str, str]:
    """Minimal allowlisted environment for the twak child. The password is
    delivered via TWAK_WALLET_PASSWORD (out-of-band, never argv); no unrelated
    secret in the service env is exposed to the child or its dependencies."""
    env = {k: os.environ[k] for k in _CHILD_ENV_ALLOW if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


@dataclass
class CliResult:
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    raw: str = ""


async def _run_twak(args: List[str], timeout: float,
                    with_password: bool) -> CliResult:
    """Spawn twak with an explicit argv (no shell) and parse its --json stdout.
    Never raises: every failure mode becomes CliResult(ok=False, error=...).

    with_password only asserts a password is configured for a write path; it is
    NEVER appended to argv. twak picks it up from TWAK_WALLET_PASSWORD in the env.
    """
    if with_password and not os.getenv("TWAK_WALLET_PASSWORD"):
        return CliResult(False, error="wallet password not configured")
    argv = [TWAK_BIN, *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_child_env(),
            stdin=asyncio.subprocess.DEVNULL,
        )
    except (OSError, ValueError) as e:
        return CliResult(False, error=f"cannot start twak: {e}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        return CliResult(False, error=f"twak timed out after {timeout:.0f}s")
    out = (out or b"")[:_MAX_OUTPUT_BYTES]
    err = (err or b"")[:_MAX_OUTPUT_BYTES]
    stdout = out.decode("utf-8", "replace").strip()
    stderr = err.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        # Prefer a structured error if twak emitted one, else the stderr text.
        msg = stderr or stdout or f"twak exited {proc.returncode}"
        parsed = _maybe_json(stdout) or _maybe_json(stderr)
        if isinstance(parsed, dict) and parsed.get("error"):
            msg = str(parsed.get("error"))
        return CliResult(False, error=msg, raw=stdout)
    body = _maybe_json(stdout)
    if not isinstance(body, dict):
        return CliResult(False, error="twak returned non-JSON output", raw=stdout)
    return CliResult(True, data=body, raw=stdout)


def _maybe_json(s: str) -> Optional[Any]:
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        # twak may print a banner line before the JSON; take the last {...} block.
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                return None
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# --- read paths (no signing) -----------------------------------------------

async def balance() -> CliResult:
    """Native BNB + token balances for the agent wallet on BSC. No password."""
    return await _run_twak(
        ["wallet", "balance", "--chain", CHAIN, "--json"],
        timeout=BALANCE_TIMEOUT, with_password=False)


async def quote(amount: float, from_token: str, to_token: str,
                slippage_pct: float = 1.0) -> CliResult:
    """Quote a swap WITHOUT executing. Validates inputs and clamps slippage to the
    policy band before the CLI ever sees them."""
    amt = _to_float(amount)
    if amt is None or amt <= 0:
        return CliResult(False, error="amount must be a positive number")
    src = _cli_token_arg(from_token)
    dst = _cli_token_arg(to_token)
    if src is None:
        return CliResult(False, error=f"unrecognised source token: {from_token!r}")
    if dst is None:
        return CliResult(False, error=f"unrecognised dest token: {to_token!r}")
    if src == dst:
        return CliResult(False, error="source and destination are the same token")
    slip = _to_float(slippage_pct)
    if slip is None:
        slip = 1.0
    slip = max(MIN_SLIPPAGE_PCT, min(MAX_SLIPPAGE_PCT, slip))
    return await _run_twak(
        ["swap", _fmt_amount(amt), src, dst,
         "--chain", CHAIN, "--slippage", _fmt_pct(slip),
         "--quote-only", "--json"],
        timeout=QUOTE_TIMEOUT, with_password=False)


def _fmt_amount(a: float) -> str:
    """Render an amount as a plain decimal string for the CLI: no scientific
    notation, no binary-float artifacts (Decimal(str(a)) captures the value the
    caller meant), capped at 18 fractional digits (the max token precision)."""
    try:
        d = Decimal(str(a)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return "0"
    # Clamp fractional precision to 18 dp without introducing an exponent.
    s = f"{d:.18f}".rstrip("0").rstrip(".")
    return s or "0"


def _amount_field(v: Any) -> Optional[float]:
    """Pull the leading numeric out of a quote amount like '5.8 USDT' or 5.8."""
    f = _to_float(v)
    if f is not None:
        return f
    if isinstance(v, str):
        m = re.match(r"\s*([0-9]*\.?[0-9]+)", v)
        if m:
            return _to_float(m.group(1))
    return None


def _fmt_pct(p: float) -> str:
    return f"{p:.4f}".rstrip("0").rstrip(".") or "0"


# --- gated write paths (sign only after the security verdict says GO) -------

@dataclass
class SwapOutcome:
    go: bool
    executed: bool
    verdict: Optional[SecurityVerdict]
    quote: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


def _is_native_sentinel(addr: Optional[str]) -> bool:
    """True for the zero address that marks native BNB (no token contract)."""
    return isinstance(addr, str) and _is_addr(addr) and int(addr, 16) == 0


def _plan_tx_from_quote(qbody: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract an unsigned {from,to,data,value} from the twak quote so the solver's
    preflight can eth_call-simulate the EXACT swap before it is signed. The quote
    may nest the transaction under a few common keys; we look in each and degrade
    to None (preflight then SKIPs honestly) when no calldata is present, rather
    than fabricating a call. Requires the public agent wallet for the `from`."""
    if not isinstance(qbody, dict) or not _is_addr(AGENT_WALLET):
        return None
    tx: Optional[Dict[str, Any]] = None
    for key in ("tx", "transaction", "txn", "swapTransaction", "rawTransaction"):
        v = qbody.get(key)
        if isinstance(v, dict):
            tx = v
            break
    if tx is None and ("to" in qbody or "data" in qbody):
        tx = qbody
    if not isinstance(tx, dict):
        return None
    to = tx.get("to") or tx.get("router") or tx.get("allowanceTarget")
    data = tx.get("data") or tx.get("calldata") or tx.get("callData")
    if not _is_addr(to) or not isinstance(data, str) or not data.startswith("0x"):
        return None
    out: Dict[str, Any] = {"from": AGENT_WALLET, "to": to, "data": data}
    val = tx.get("value")
    if val is not None:
        out["value"] = val
    return out


def _quote_to_plan(qbody: Dict[str, Any], to_addr: str, slippage_pct: float,
                   equity: Optional[float], equity_floor: Optional[float]
                   ) -> TradePlan:
    """Build the solver TradePlan from a twak quote. The bought token and the 0x
    spender are honeypot/contract scanned; the quote's own output vs minReceived
    feeds the solver's stronger slippage path (realised tolerance), the requested
    slippage carries through for the MEV read, and the quote's unsigned swap tx
    (when present) is forwarded so preflight eth_call-simulates the exact route. A
    swap whose DESTINATION is native BNB has no token contract to scan, so token is
    left None (the gate then relies on the spender + slippage + preflight + governor
    checks) rather than the zero address, which would hard-fail address validation."""
    bps = int(round(max(0.0, slippage_pct) * 100))
    token = None if _is_native_sentinel(to_addr) else (to_addr if _is_addr(to_addr) else None)
    # Derive expected_out / min_out from the live quote on a shared integer scale
    # (the solver's slippage ratio is scale-invariant, so the exact token decimals
    # do not matter here). This exercises the tighter realised-slippage check.
    exp_out = min_out = None
    exp_f = _amount_field(qbody.get("output"))
    min_f = _amount_field(qbody.get("minReceived"))
    if exp_f is not None and exp_f > 0:
        exp_out = int(exp_f * 1_000_000_000)
        if min_f is not None and min_f >= 0:
            min_out = int(min_f * 1_000_000_000)
    return TradePlan(
        token=token,
        router=ZEROX_PROXY_BSC,
        chain_id=CHAIN_ID,
        expected_out=exp_out,
        min_out=min_out,
        slippage_bps=bps,
        max_slippage_bps=int(round(MAX_SLIPPAGE_PCT * 100)),
        # Feed the real unsigned swap tx (when the quote carries calldata) so the
        # solver eth_call-simulates the exact route; absent => preflight SKIPs.
        tx=_plan_tx_from_quote(qbody),
        equity=equity,
        equity_floor=equity_floor,
    )


def _notional_usd(amount: float, from_token: str, to_token: str,
                  qbody: Dict[str, Any], approx_usd: Optional[float]
                  ) -> Optional[float]:
    """Best-effort USD notional of a swap for the cap check. Selling a stable ->
    amount is the notional. Buying a stable -> the cap must NOT be evadable by a
    manipulated-low DEX quote, so the notional is the LARGER of the quote output
    and the caller's independent mark (approx_usd, a Binance-derived USD value):
    flooring with the independent mark means a quote massaged below the cap cannot
    authorise an oversized order. Falls back to approx_usd, then None (caller
    treats None as 'cannot value' and fails closed for an execute)."""
    src = (from_token or "").strip().upper()
    dst = (to_token or "").strip().upper()
    appx = _to_float(approx_usd) if approx_usd is not None else None
    if src in _USD_STABLES:
        # Selling a stable: amount is the notional, but never let it read below an
        # independent mark either (defensive; they should agree closely).
        return max(amount, appx) if appx is not None and appx > 0 else amount
    if dst in _USD_STABLES:
        out = _amount_field(qbody.get("output"))
        cands = [v for v in (out, appx) if v is not None and v > 0]
        if cands:
            return max(cands)
    return appx


def _price_impact_pct(qbody: Dict[str, Any]) -> Optional[float]:
    return _amount_field(qbody.get("priceImpact"))


async def swap(amount: float, from_token: str, to_token: str,
               slippage_pct: float = 1.0, *, execute: bool = False,
               equity: Optional[float] = None,
               equity_floor: Optional[float] = None,
               approx_usd: Optional[float] = None) -> SwapOutcome:
    """Quote a swap, run the security gate, and (only if execute=True AND the gate
    says GO) sign it. Quote-only by default. The gate ALWAYS runs, even when
    execute=False, so the cockpit can show the verdict before a human commits."""
    amt = _to_float(amount)
    if amt is None or amt <= 0:
        return SwapOutcome(False, False, None,
                           detail="amount must be a positive number")
    dst_addr = _resolve_token(to_token)
    src_addr = _resolve_token(from_token)
    if src_addr is None or dst_addr is None:
        return SwapOutcome(False, False, None,
                           detail=f"unrecognised token: {from_token!r}/{to_token!r}")

    # Absolute native-unit backstop on the SOLD token, independent of any USD
    # figure, so a missing/low approx_usd cannot authorise an oversized order.
    src_sym = (from_token or "").strip().upper()
    nat_cap = MAX_NATIVE_PER_SWAP.get(src_sym)
    if nat_cap is not None and amt > nat_cap:
        return SwapOutcome(False, False, None,
                           detail=f"swap {amt:g} {src_sym} over native cap "
                                  f"{nat_cap:g} {src_sym}")

    q = await quote(amount, from_token, to_token, slippage_pct)
    if not q.ok:
        # The raw quote error can embed a tool/RPC endpoint; keep it in the server
        # log only and return a generic detail (this surfaces in public state).
        logger.warning("bsc swap quote failed: %s", q.error)
        return SwapOutcome(False, False, None, detail="quote unavailable")

    # Quote-derived USD cap (does not rely on the caller asserting approx_usd).
    usd = _notional_usd(amt, from_token, to_token, q.data, approx_usd)
    if usd is not None and usd > MAX_SWAP_USD:
        return SwapOutcome(False, False, None, quote=q.data,
                           detail=f"swap ~${usd:.0f} over cap ${MAX_SWAP_USD:.0f}")
    # Fail closed: an execute we cannot value (no stable leg, no approx_usd, and
    # not covered by a native cap) is refused rather than allowed unbounded.
    if execute and usd is None and nat_cap is None:
        return SwapOutcome(False, False, None, quote=q.data,
                           detail="cannot value swap (no stable leg / native cap "
                                  "/ approx_usd); refusing to execute unbounded")

    # Price-impact (route depth) guard from the live quote.
    pi = _price_impact_pct(q.data)
    if pi is not None and pi > MAX_PRICE_IMPACT_PCT:
        return SwapOutcome(False, False, None, quote=q.data,
                           detail=f"price impact {pi:.2f}% over cap "
                                  f"{MAX_PRICE_IMPACT_PCT:.1f}% (thin liquidity)")

    slip = max(MIN_SLIPPAGE_PCT, min(MAX_SLIPPAGE_PCT, _to_float(slippage_pct) or 1.0))
    plan = _quote_to_plan(q.data, dst_addr, slip, equity, equity_floor)
    verdict = await evaluate_trade(plan, strict=True)

    impact_note = (f" (price impact {pi:.2f}%)"
                   if pi is not None and pi > WARN_PRICE_IMPACT_PCT else "")
    if not verdict.go:
        return SwapOutcome(False, False, verdict, quote=q.data,
                           detail=f"BLOCKED by security gate: {verdict.detail}")
    if not execute:
        return SwapOutcome(True, False, verdict, quote=q.data,
                           detail=f"GO (quote-only): {verdict.detail}{impact_note}")

    src = _cli_token_arg(from_token)
    dst = _cli_token_arg(to_token)
    if src is None or dst is None:
        return SwapOutcome(True, False, verdict, quote=q.data,
                           detail="gate passed but token args failed revalidation")
    ex = await _run_twak(
        ["swap", _fmt_amount(amt), src, dst,
         "--chain", CHAIN, "--slippage", _fmt_pct(slip), "--json"],
        timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("bsc swap gate passed but execution failed: %s", ex.error)
        return SwapOutcome(True, False, verdict, quote=q.data,
                           detail="gate passed but execution failed")
    return SwapOutcome(True, True, verdict, quote=q.data, result=ex.data,
                       detail=f"executed after passing security gate{impact_note}")


@dataclass
class TransferOutcome:
    go: bool
    executed: bool
    verdict: Optional[SecurityVerdict]
    result: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


async def transfer(to: str, amount: float, token: str = "BNB", *,
                   execute: bool = False, confirm_to: Optional[str] = None,
                   approx_usd: Optional[float] = None) -> TransferOutcome:
    """Gated token/native transfer. The destination is honeypot/contract vetted
    (a transfer INTO a malicious contract is a known drain vector) and the USD cap
    is enforced before any signing. Quote-only / dry by default."""
    dest = _resolve_addr(to)
    if dest is None:
        return TransferOutcome(False, False, None,
                               detail=f"invalid destination address: {to!r}")
    tok = _resolve_token(token)
    if tok is None:
        return TransferOutcome(False, False, None,
                               detail=f"unrecognised token: {token!r}")
    amt = _to_float(amount)
    if amt is None or amt <= 0:
        return TransferOutcome(False, False, None,
                               detail="amount must be a positive number")
    if approx_usd is not None:
        usd = _to_float(approx_usd)
        if usd is not None and usd > MAX_TRANSFER_USD:
            return TransferOutcome(False, False, None,
                                   detail=f"transfer ~${usd:.0f} over cap "
                                          f"${MAX_TRANSFER_USD:.0f}")

    # Build the twak asset id (the only chain selector for a transfer): native
    # BNB is c<coinId>; a BEP-20 is c<coinId>_t<contract>. The destination going
    # INTO a token contract is a known drain vector, so vetting is fail-closed.
    is_native = _is_native_sentinel(tok) or (token or "").strip().upper() == "BNB"
    if is_native:
        asset_id = f"c{BSC_COIN_ID}"
    elif _is_addr(tok):
        asset_id = f"c{BSC_COIN_ID}_t{tok}"
    else:
        return TransferOutcome(False, False, None,
                               detail=f"cannot build asset id for token {token!r}")

    # Vet the destination (skips cleanly for an EOA; fail-closed for a contract).
    plan = TradePlan(token=dest, chain_id=CHAIN_ID, trade_amount=1)
    verdict = await evaluate_trade(plan, strict=True)
    if not verdict.go:
        return TransferOutcome(False, False, verdict,
                               detail=f"BLOCKED: destination vet failed: "
                                      f"{verdict.detail}")
    if not execute:
        return TransferOutcome(True, False, verdict,
                               detail="GO (dry-run): destination vetted")

    # The CLI-side USD ceiling is always passed (never conditional on the caller
    # supplying approx_usd), clamped to the policy cap.
    cap_usd = MAX_TRANSFER_USD
    if approx_usd is not None:
        a = _to_float(approx_usd)
        if a is not None:
            cap_usd = min(MAX_TRANSFER_USD, a)
    args = ["transfer", "--to", dest, "--amount", _fmt_amount(amt),
            "--token", asset_id, "--max-usd", _fmt_amount(cap_usd), "--json"]
    if confirm_to:
        cto = _resolve_addr(confirm_to)
        if cto is None or cto != dest:
            return TransferOutcome(True, False, verdict,
                                   detail="confirm_to does not match destination")
        args += ["--confirm-to", cto]
    ex = await _run_twak(args, timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("bsc transfer gate passed but execution failed: %s", ex.error)
        return TransferOutcome(True, False, verdict,
                               detail="gate passed but transfer failed")
    return TransferOutcome(True, True, verdict, result=ex.data,
                           detail="transfer executed after destination vet")


def _resolve_addr(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s.lower() if _is_addr(s) else None


# --- perps note ------------------------------------------------------------
# ApolloX (BSC perps) is intentionally NOT executed through this adapter: twak
# exposes no perp/derivative primitive, so leveraged exposure is kept on the
# audited CEX adapter (autotrade/exchange_adapter.py, Binance USDT-M). Routing a
# fake "perp" through a spot swap would misreport risk to the drawdown governor.
# This boundary is a safety decision, not a missing feature.
SUPPORTS_PERPS = False
