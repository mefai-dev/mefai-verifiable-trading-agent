"""
MEFAI BNB HACK · live-trade broadcaster (transparency feed)

A best-effort, fire-and-forget Telegram broadcaster the loop uses to announce
each trade leg it takes, so anyone watching can verify the agent's activity in
real time against the live cockpit and the BSC result ledger.

Design rules:
  - Read-only and side-effect free for trading: this NEVER signs, never moves
    funds, never touches a key. It only posts a human-readable message.
  - Fully optional: if no bot token / chat id is configured it is a silent
    no-op, so the loop runs identically with or without it.
  - Never blocks the event loop and never raises: the network POST runs in a
    worker thread and every failure is swallowed (logged at debug), because a
    notification must never stall or crash the trading cycle.
  - No secrets in any message: only the public trade facts (symbol, side, size,
    prices, PnL) and the public BscScan tx link.

Configuration (all via environment):
  BNBHACK_TG_BOT_TOKEN   Telegram bot token (falls back to TELEGRAM_BOT_TOKEN).
  BNBHACK_TG_CHAT_ID     Target chat / channel id for the broadcast.
  BNBHACK_TG_PAPER       "1" (default) also announces paper legs, clearly
                         labelled PAPER; "0" announces only live executed legs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("mefai.bnbhack.notify")

_BOT_TOKEN = (os.getenv("BNBHACK_TG_BOT_TOKEN")
              or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
_CHAT_ID = os.getenv("BNBHACK_TG_CHAT_ID", "").strip()
_PAPER_OK = os.getenv("BNBHACK_TG_PAPER", "1") == "1"


def enabled() -> bool:
    """True only when a bot token and a target chat are both configured."""
    return bool(_BOT_TOKEN and _CHAT_ID)


def paper_enabled() -> bool:
    """Whether paper (simulated) legs are announced alongside live ones."""
    return _PAPER_OK


def _post_sync(text: str) -> None:
    """Blocking Telegram sendMessage. Runs in a worker thread; never raises."""
    try:
        url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
        body = json.dumps({
            "chat_id": _CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("telegram broadcast failed: %s", exc)
    except Exception as exc:  # never let a notification crash the loop
        logger.debug("telegram broadcast error: %s", exc)


async def broadcast(text: str) -> None:
    """Fire-and-forget broadcast. No-op when unconfigured; never raises."""
    if not enabled() or not text:
        return
    try:
        await asyncio.to_thread(_post_sync, text)
    except Exception as exc:
        logger.debug("telegram broadcast dispatch failed: %s", exc)


def _esc(s: Any) -> str:
    """Minimal HTML escape for the few free-text fields we interpolate."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _mode_tag(live: bool) -> str:
    return "\U0001F7E2 LIVE" if live else "\U0001F4DD PAPER"


def format_open(sec: Dict[str, Any], symbol: str, direction: int,
                entry: float, target: float, stop: float,
                is_floor: bool = False) -> Optional[str]:
    """Render an opened / added leg, or None if it should not be announced."""
    live = bool(sec.get("executed"))
    if not live and not _PAPER_OK:
        return None
    side = "LONG" if direction >= 0 else "SHORT"
    rung = sec.get("mode", "")
    verb = "Opened" if rung == "open" else "Added to"
    lines = [
        f"{_mode_tag(live)} · {verb} {side} {_esc(symbol)}",
    ]
    usd = sec.get("usd")
    if usd is not None:
        lines.append(f"Size · ${usd:,.2f}" + (
            f" (one of {sec.get('rungs')} rungs)" if sec.get("rungs") else ""))
    if entry:
        lines.append(f"Entry · {entry:,.6g}")
    if target:
        lines.append(f"Target · {target:,.6g}")
    if stop:
        lines.append(f"Stop · {stop:,.6g}")
    if is_floor:
        lines.append("Note · daily floor (kept \u22651 trade/day)")
    detail = sec.get("detail")
    if detail:
        lines.append(f"Gate · {_esc(detail)}")
    return "\n".join(lines)


def format_close(close: Dict[str, Any]) -> Optional[str]:
    """Render a closed leg, or None if it should not be announced."""
    live = bool(close.get("executed"))
    if not live and not _PAPER_OK:
        return None
    pnl = close.get("pnl_usd", 0.0)
    pct = close.get("pnl_pct", 0.0)
    mark = "\U0001F4C8" if pnl >= 0 else "\U0001F4C9"
    kind = "Partial close" if close.get("partial") else "Closed"
    lines = [
        f"{_mode_tag(live)} · {mark} {kind} {_esc(close.get('symbol', ''))}",
        f"PnL · ${pnl:,.2f} ({pct:+.2f}%)",
    ]
    exitp = close.get("exit_price")
    if exitp:
        lines.append(f"Exit · {exitp:,.6g}")
    reason = close.get("reason")
    if reason:
        lines.append(f"Reason · {_esc(reason)}")
    return "\n".join(lines)
