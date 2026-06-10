"""
MEFAI BNB HACK · Perp execution adapter (Track 1 live SHORT leg)

The agent is two-sided by design: a LONG is expressed directly on PancakeSwap
spot (bsc_exec), but a SHORT cannot be expressed on spot (there is no borrow
leg). This module is the SHORT leg's execution venue. It routes a directional
short through the USDT-M futures adapter (Binance-first) that ships with the
private MEFAI deployment running alongside this repo · exactly the venue the
bsc_exec perps note documents for leveraged exposure. The public tree ships
this short leg disabled by default: without that adapter and venue keys it
stays an honest no-go. ApolloX is deliberately NOT wired as a raw
leveraged-DEX contract signer here: twak exposes no perp primitive and a
bespoke signer would be a much larger funds-touching surface, so the gated
CEX futures adapter is the supported venue.

Safety / integrity (mirrors bsc_exec):
  - OFF by default. open_short / close_short are an honest no-go (sign nothing,
    move no funds, hold no key) unless BNBHACK_EXECUTE_PERP=1 AND venue API keys
    are configured. With the flag off (the default) the loop's live-short path
    stays the exact honest no-go it already is.
  - Leverage is pinned (BNBHACK_PERP_LEVERAGE, default 1x), so the short is a
    pure directional hedge sized by the same drawdown-Kelly notional as the spot
    long · never extra leverage the drawdown governor cannot see.
  - account_equity_usd() lets the loop fold the venue's margin balance + open
    unrealized PnL into mark-to-market equity, so a live short's risk is VISIBLE
    to the RiskGovernor drawdown killswitch and is never reported only on the
    BSC wallet (which would understate true exposure).
  - Keys come only from the environment, are never logged and never leave this
    process. No call raises into the loop; every failure is an honest no-go.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mefai.bnbhack.perp")

# The USDT-M futures adapter is part of the private MEFAI deployment that runs
# alongside this repo (an autotrade package at the repo root when deployed).
# Add that directory to the import path lazily so this module has no
# import-time dependency when perps are disabled (the default).
_AUTOTRADE_DIR = Path(__file__).resolve().parents[2] / "autotrade"


def _flag_on() -> bool:
    return os.getenv("BNBHACK_EXECUTE_PERP", "") == "1"


def _keys() -> Optional[Dict[str, Any]]:
    """Venue credentials from the environment, or None when unconfigured. Never
    logged. The secret is read here and handed straight to the adapter."""
    key = os.getenv("BNBHACK_PERP_KEY", "").strip()
    secret = os.getenv("BNBHACK_PERP_SECRET", "").strip()
    if not key or not secret:
        return None
    return {
        "venue": os.getenv("BNBHACK_PERP_VENUE", "binance").strip().lower(),
        "api_key": key,
        "api_secret": secret,
        "testnet": os.getenv("BNBHACK_PERP_TESTNET", "") == "1",
        "quote": os.getenv("BNBHACK_PERP_QUOTE", "USDT").strip().upper(),
    }


def configured() -> bool:
    """True when venue keys are present (independent of the execute flag), so the
    cockpit can show the perp leg is provisioned without revealing anything."""
    return _keys() is not None


def enabled() -> bool:
    """Live perp shorts execute only when the flag is on AND keys are present."""
    return _flag_on() and configured()


def leverage() -> int:
    try:
        return max(1, int(os.getenv("BNBHACK_PERP_LEVERAGE", "1")))
    except ValueError:
        return 1


def margin_mode() -> str:
    m = os.getenv("BNBHACK_PERP_MARGIN_MODE", "isolated").strip().lower()
    return m if m in ("isolated", "cross") else "isolated"


@dataclass
class PerpOutcome:
    go: bool
    executed: bool
    detail: str
    result: Optional[Dict[str, Any]] = None
    price: float = 0.0          # fill price (entry on open, exit on close)
    qty: float = 0.0            # contracts filled
    notional_usd: float = 0.0


# ---------------------------------------------------------------------------
# Lazy adapter singleton
# ---------------------------------------------------------------------------
_adapter: Any = None
_adapter_lock = asyncio.Lock()


async def _get_adapter() -> Any:
    """Build (once) the futures adapter for the configured venue. Raises
    on a real config error; callers wrap every use in a no-go guard."""
    global _adapter
    if _adapter is not None:
        return _adapter
    async with _adapter_lock:
        if _adapter is not None:
            return _adapter
        keys = _keys()
        if keys is None:
            raise RuntimeError("perp venue keys not configured")
        if str(_AUTOTRADE_DIR) not in sys.path:
            sys.path.insert(0, str(_AUTOTRADE_DIR))
        from exchange_adapter import ExchangeAdapter  # type: ignore
        _adapter = ExchangeAdapter(
            venue=keys["venue"], api_key=keys["api_key"],
            api_secret=keys["api_secret"], testnet=keys["testnet"],
            quote=keys["quote"])
        return _adapter


def _fill_price(order: Dict[str, Any]) -> float:
    """Best-effort average fill price from a ccxt order result (0 when absent)."""
    if not isinstance(order, dict):
        return 0.0
    for k in ("average", "price"):
        v = order.get(k)
        try:
            f = float(v)
            if f > 0:
                return f
        except (TypeError, ValueError):
            continue
    return 0.0


def _fill_qty(order: Dict[str, Any]) -> float:
    if not isinstance(order, dict):
        return 0.0
    for k in ("filled", "amount"):
        v = order.get(k)
        try:
            f = float(v)
            if f > 0:
                return f
        except (TypeError, ValueError):
            continue
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def open_short(symbol: str, notional_usd: float,
                     *, equity: Optional[float] = None) -> PerpOutcome:
    """Open (or add to) a directional short of `notional_usd` on the perp venue.
    Honest no-go when perps are disabled or below the venue minimum; never
    raises. Leverage is pinned (default 1x) so the notional matches the sizer's
    drawdown-budget figure rather than amplifying it."""
    if not enabled():
        return PerpOutcome(
            go=False, executed=False,
            detail="live short requires a perp venue (BNBHACK_EXECUTE_PERP=1 "
                   "plus venue keys); paper-simulated only")
    if notional_usd <= 0:
        return PerpOutcome(go=False, executed=False,
                           detail="short notional collapsed to 0")
    try:
        ad = await _get_adapter()
        lev = leverage()
        await ad.prepare_symbol(symbol, lev, margin_mode())
        mark = await ad.fetch_mark_price(symbol)
        if not mark or mark <= 0:
            return PerpOutcome(go=False, executed=False,
                               detail="no live perp mark price")
        amount = ad.amount_to_precision(symbol, notional_usd / mark)
        if amount <= 0:
            return PerpOutcome(go=False, executed=False,
                               detail="size rounds below the venue lot step")
        filt = await ad.symbol_filters(symbol)
        amt_min = filt.get("amount_min")
        cost_min = filt.get("cost_min")
        if amt_min and amount < float(amt_min):
            return PerpOutcome(go=False, executed=False,
                               detail=f"below venue min size ({amt_min})")
        if cost_min and (amount * mark) < float(cost_min):
            return PerpOutcome(go=False, executed=False,
                               detail=f"below venue min notional (${cost_min})")
        order = await ad.market_order(symbol, "sell", amount, reduce_only=False)
        px = _fill_price(order) or mark
        qty = _fill_qty(order) or amount
        return PerpOutcome(
            go=True, executed=True,
            detail=f"perp short opened ({lev}x {margin_mode()})",
            result={"venue": ad.venue, "order_id": order.get("id"),
                    "side": "short"} if isinstance(order, dict) else None,
            price=px, qty=qty, notional_usd=qty * px)
    except Exception as exc:  # noqa: BLE001 · never raise into the loop
        # The adapter scrubs venue text; keep the loop-side message generic.
        logger.warning("perp open_short failed for %s: %s", symbol, exc)
        return PerpOutcome(go=False, executed=False,
                           detail="perp venue rejected the short")


async def close_short(symbol: str) -> PerpOutcome:
    """Market-close the open short on `symbol` (reduce-only). Honest no-go when
    perps are disabled; reports executed=False (not an error) when there is no
    open position to close. Never raises."""
    if not enabled():
        return PerpOutcome(go=False, executed=False,
                           detail="perp venue disabled")
    try:
        ad = await _get_adapter()
        order = await ad.close_position(symbol)
        if order is None:
            return PerpOutcome(go=True, executed=False,
                               detail="no open perp position")
        return PerpOutcome(
            go=True, executed=True, detail="perp short closed",
            result={"venue": ad.venue, "order_id": order.get("id")}
            if isinstance(order, dict) else None,
            price=_fill_price(order), qty=_fill_qty(order))
    except Exception as exc:  # noqa: BLE001
        logger.warning("perp close_short failed for %s: %s", symbol, exc)
        return PerpOutcome(go=False, executed=False,
                           detail="perp venue rejected the close")


async def account_equity_usd() -> Optional[float]:
    """Venue account equity in USD = quote margin (free+used) + open unrealized
    PnL, so the loop can fold the short leg into mark-to-market equity and keep
    the drawdown governor honest. Returns None on any read failure so the caller
    holds last-good rather than publishing a total that omits the perp leg."""
    if not configured():
        return None
    try:
        ad = await _get_adapter()
        bal = await ad.fetch_balance_quote()
        total = float(bal.get("total") or (bal.get("free", 0) + bal.get("used", 0)))
        upnl = 0.0
        for p in await ad.fetch_positions():
            upnl += float(p.get("unrealized_pnl") or 0)
        eq = total + upnl
        return eq if eq >= 0 else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.warning("perp account_equity read failed: %s", exc)
        return None


def status() -> Dict[str, Any]:
    """Non-sensitive status for the published state (no keys, no balances)."""
    k = _keys()
    return {
        "enabled": enabled(),
        "configured": configured(),
        "venue": (k or {}).get("venue") if k else None,
        "leverage": leverage(),
        "margin_mode": margin_mode(),
    }


async def shutdown() -> None:
    """Best-effort socket teardown on loop exit."""
    global _adapter
    if _adapter is not None:
        try:
            await _adapter.close()
        except Exception:  # noqa: BLE001
            pass
        _adapter = None
