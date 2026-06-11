"""
MEFAI BNB HACK · Position manager (Track 1 open/close lifecycle)

The agent's position memory and exit brain. The autonomous loop (loop.py) opens
a LONG spot leg on a MEFAI buy signal; this module is what then OWNS that
position until it is closed, so the agent does not just accumulate spot bags.

Per cycle the loop hands every open position to `manage`, which:
  1. reads a live mark price (Binance REST, the same price basis the MEFAI
     signal is computed on) for the position's symbol,
  2. closes the position when ANY exit rule fires:
       - take-profit  : mark crossed the committed target,
       - stop-loss    : mark crossed the committed stop,
       - signal flip  : the latest MEFAI signal on that symbol turned `sell`,
  3. realises the PnL (paper: marked off the live price; live: the proceeds of
     the gated token->USDT swap through bsc_exec.swap), and
  4. keeps a peak/trailing high-water mark per position for trailing exits.

It also gates new entries: at most `max_positions` open at once, and never a
second LONG on a symbol that is already open (no pyramiding); a fresh opposite
signal closes the open leg first (handled by the loop via `has_open`).

Safety / integrity:
  - PAPER by default. A close signs a real token->USDT swap ONLY when the loop
    passes execute=True, and that swap still goes through the bsc_exec security
    gate; nothing here weakens it.
  - No fabricated numbers. Paper PnL is marked off the real live price against
    the real recorded entry; size/qty are derived, never invented. A missing
    mark price simply defers the exit decision to the next cycle (never a guess).
  - The store carries no secrets and survives a restart, so a mid-window restart
    cannot forget an open position (and thereby skip its exit).
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

import bsc_exec
import perp_exec

logger = logging.getLogger("mefai.bnbhack.positions")

# Binance public spot ticker. REST is reachable from this datacenter (only the
# USDT-M futures websocket is geo-blocked), so this is a safe, key-free mark
# source that matches the price basis of the MEFAI signal. A second public
# market-data domain (data-api.binance.com) is tried if the primary host is
# unreachable, so a single endpoint hiccup cannot stall every exit at once;
# both serve the identical /api/v3/ticker/price feed.
_BINANCE_TICKER = os.getenv(
    "BNBHACK_MARK_URL", "https://api.binance.com/api/v3/ticker/price")
_BINANCE_TICKER_ALT = os.getenv(
    "BNBHACK_MARK_URL_ALT", "https://data-api.binance.com/api/v3/ticker/price")
_MARK_TIMEOUT = 8.0


def _now() -> int:
    return int(time.time())


async def mark_price(symbol: str, fallback: Optional[float] = None
                     ) -> Optional[float]:
    """Live spot mark for a USDT pair (e.g. BTCUSDT). Returns `fallback` on any
    failure so a transient network blip defers the exit decision rather than
    forcing a guess."""
    sym = (symbol or "").upper().replace(".P", "").strip()
    if not sym:
        return fallback
    urls = [u for u in (_BINANCE_TICKER, _BINANCE_TICKER_ALT) if u]
    for i, url in enumerate(urls):
        try:
            async with httpx.AsyncClient(timeout=_MARK_TIMEOUT) as client:
                r = await client.get(url, params={"symbol": sym})
            if r.status_code != 200:
                continue
            px = float(r.json().get("price") or 0)
            if math.isfinite(px) and px > 0:
                return px
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            continue
    # Every source failed this cycle: defer the exit (never guess).
    return fallback


# Fields a twak swap result may carry for the bought/received token amount. The
# close needs the USDT proceeds; the open needs the token qty received.
_OUT_FIELDS = ("output", "toAmount", "amountOut", "received", "outputAmount")


def _amount_from_result(result: Dict[str, Any]) -> Optional[float]:
    for k in _OUT_FIELDS:
        v = result.get(k) if isinstance(result, dict) else None
        f = bsc_exec._amount_field(v)
        if f is not None and f > 0:
            return f
    return None


def _leg_dir(row: sqlite3.Row) -> int:
    """+1 for a LONG leg, -1 for a SHORT leg. Reads the stored signal_dir; any
    non-negative value is treated as long so legacy rows (written before shorts
    were tradable) keep their long semantics."""
    try:
        return -1 if int(row["signal_dir"] or 1) < 0 else 1
    except Exception:
        return 1


def _row_is_floor(row: sqlite3.Row) -> bool:
    """True when this leg was opened by the daily-floor compliance path. Reads
    the stored is_floor flag; legacy rows written before the column existed
    raise on the missing key and default to False (not a floor leg)."""
    try:
        return bool(row["is_floor"])
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class PositionStore:
    """Durable open/closed position ledger. One row per leg; signal_dir marks a
    long (+1) or a short (-1) and every PnL/exit rule is direction-aware."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        with self._conn() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS positions ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " symbol TEXT, base TEXT, token TEXT, status TEXT,"
                " qty_token REAL, size_usd REAL, entry REAL, target REAL,"
                " stop REAL, peak REAL, signal_dir INTEGER,"
                " opened_ts INTEGER, open_tx TEXT,"
                " exit_price REAL, pnl_usd REAL, pnl_pct REAL,"
                " close_reason TEXT, closed_ts INTEGER)")
            # Forward-compatible migration: add the scale-out / ladder columns to
            # a ledger created by an earlier build (SQLite has no ADD COLUMN IF
            # NOT EXISTS, so guard against the column already existing).
            existing = {r["name"] for r in
                        db.execute("PRAGMA table_info(positions)")}
            for col, ddl in (
                ("tp1_done", "tp1_done INTEGER DEFAULT 0"),
                ("realized_partial_usd",
                 "realized_partial_usd REAL DEFAULT 0"),
                ("rungs_total", "rungs_total INTEGER DEFAULT 1"),
                ("rungs_filled", "rungs_filled INTEGER DEFAULT 1"),
                ("size_target_usd", "size_target_usd REAL DEFAULT 0"),
                # Disclosure flag: 1 when this leg was opened by the daily-floor
                # min-1-trade-per-day compliance path, not by a conviction signal.
                ("is_floor", "is_floor INTEGER DEFAULT 0"),
            ):
                if col not in existing:
                    db.execute("ALTER TABLE positions ADD COLUMN " + ddl)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    def open_rows(self) -> List[sqlite3.Row]:
        with self._conn() as db:
            return db.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY id ASC"
            ).fetchall()

    def open_count(self) -> int:
        with self._conn() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM positions WHERE status='open'"
            ).fetchone()[0])

    def has_open(self, symbol: str) -> bool:
        with self._conn() as db:
            return db.execute(
                "SELECT 1 FROM positions WHERE status='open' AND symbol=? LIMIT 1",
                (symbol,)).fetchone() is not None

    def open_row(self, symbol: str) -> Optional[sqlite3.Row]:
        with self._conn() as db:
            return db.execute(
                "SELECT * FROM positions WHERE status='open' AND symbol=? "
                "ORDER BY id ASC LIMIT 1", (symbol,)).fetchone()

    def add(self, rec: Dict[str, Any]) -> int:
        with self._conn() as db:
            cur = db.execute(
                "INSERT INTO positions (symbol,base,token,status,qty_token,"
                "size_usd,entry,target,stop,peak,signal_dir,opened_ts,open_tx,"
                "rungs_total,rungs_filled,size_target_usd,is_floor) "
                "VALUES (?,?,?,'open',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["symbol"], rec["base"], rec["token"], rec["qty_token"],
                 rec["size_usd"], rec["entry"], rec["target"], rec["stop"],
                 rec["entry"], rec["signal_dir"], rec["opened_ts"],
                 rec.get("open_tx", ""), rec.get("rungs_total", 1),
                 rec.get("rungs_filled", 1),
                 rec.get("size_target_usd", rec["size_usd"]),
                 1 if rec.get("is_floor") else 0))
            return int(cur.lastrowid)

    def add_if_openable(self, rec: Dict[str, Any], max_positions: int
                        ) -> Optional[int]:
        """Atomic guarded open: insert a fresh leg only if, re-checked inside one
        write transaction, the symbol still has no open leg AND the open count is
        under the cap. Closes the TOCTOU window where the loop reads entry_mode
        ('open') and only later records the leg, by which point another path
        could already have opened the symbol (a duplicate leg) or filled the cap.
        Returns the new row id, or None when the guard now blocks the open."""
        with self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            dup = db.execute(
                "SELECT 1 FROM positions WHERE status='open' AND symbol=? LIMIT 1",
                (rec["symbol"],)).fetchone()
            if dup is not None:
                return None
            cnt = int(db.execute(
                "SELECT COUNT(*) FROM positions WHERE status='open'"
            ).fetchone()[0])
            if cnt >= max_positions:
                return None
            cur = db.execute(
                "INSERT INTO positions (symbol,base,token,status,qty_token,"
                "size_usd,entry,target,stop,peak,signal_dir,opened_ts,open_tx,"
                "rungs_total,rungs_filled,size_target_usd,is_floor) "
                "VALUES (?,?,?,'open',?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["symbol"], rec["base"], rec["token"], rec["qty_token"],
                 rec["size_usd"], rec["entry"], rec["target"], rec["stop"],
                 rec["entry"], rec["signal_dir"], rec["opened_ts"],
                 rec.get("open_tx", ""), rec.get("rungs_total", 1),
                 rec.get("rungs_filled", 1),
                 rec.get("size_target_usd", rec["size_usd"]),
                 1 if rec.get("is_floor") else 0))
            return int(cur.lastrowid)

    def deployed_usd(self) -> float:
        """Total notional currently committed to open legs, so the sizer can
        treat only the FREE balance (equity minus deployed) as available
        collateral and never re-bet capital that is already in a position."""
        with self._conn() as db:
            return float(db.execute(
                "SELECT COALESCE(SUM(size_usd),0) FROM positions "
                "WHERE status='open'").fetchone()[0] or 0.0)

    def add_slice(self, rec: Dict[str, Any]) -> None:
        """Record a realised TP1 slice as its own closed row (so it shows in the
        recent-closes feed and is summed into the realised total)."""
        with self._conn() as db:
            db.execute(
                "INSERT INTO positions (symbol,base,token,status,qty_token,"
                "size_usd,entry,exit_price,pnl_usd,pnl_pct,close_reason,"
                "opened_ts,closed_ts) VALUES (?,?,?,'closed',?,?,?,?,?,?,?,?,?)",
                (rec["symbol"], rec["base"], rec["token"], rec["qty_token"],
                 rec["size_usd"], rec["entry"], rec["exit_price"],
                 rec["pnl_usd"], rec["pnl_pct"], rec["close_reason"],
                 rec["opened_ts"], _now()))

    def apply_tp1(self, pos_id: int, qty: float, size: float, stop: float,
                  target: float, peak: float, realized_add: float) -> None:
        """Shrink the leg after a TP1 partial: keep it open with the remaining
        qty/size, lock the stop into profit, extend to TP2, bank the slice."""
        with self._conn() as db:
            db.execute(
                "UPDATE positions SET tp1_done=1, qty_token=?, size_usd=?, "
                "stop=?, target=?, peak=?, "
                "realized_partial_usd=COALESCE(realized_partial_usd,0)+? "
                "WHERE id=?",
                (qty, size, stop, target, peak, realized_add, pos_id))

    def apply_add(self, pos_id: int, qty: float, size: float, entry: float,
                  rungs_filled: int) -> None:
        """Fill another entry rung: grow qty/size, move to the weighted-average
        entry. Stop/target stay anchored to the first rung's plan."""
        with self._conn() as db:
            db.execute(
                "UPDATE positions SET qty_token=?, size_usd=?, entry=?, "
                "rungs_filled=? WHERE id=?",
                (qty, size, entry, rungs_filled, pos_id))

    def update_peak(self, pos_id: int, peak: float) -> None:
        with self._conn() as db:
            db.execute("UPDATE positions SET peak=? WHERE id=?", (peak, pos_id))

    def update_stop(self, pos_id: int, stop: float, peak: float) -> None:
        with self._conn() as db:
            db.execute("UPDATE positions SET stop=?, peak=? WHERE id=?",
                       (stop, peak, pos_id))

    def close(self, pos_id: int, exit_price: float, pnl_usd: float,
              pnl_pct: float, reason: str) -> None:
        with self._conn() as db:
            db.execute(
                "UPDATE positions SET status='closed', exit_price=?, pnl_usd=?, "
                "pnl_pct=?, close_reason=?, closed_ts=? WHERE id=?",
                (exit_price, pnl_usd, pnl_pct, reason, _now(), pos_id))

    def realized_total(self) -> float:
        with self._conn() as db:
            return float(db.execute(
                "SELECT COALESCE(SUM(pnl_usd),0) FROM positions WHERE status='closed'"
            ).fetchone()[0] or 0.0)

    def recent_closes(self, limit: int = 12) -> List[sqlite3.Row]:
        with self._conn() as db:
            return db.execute(
                "SELECT * FROM positions WHERE status='closed' "
                "ORDER BY closed_ts DESC LIMIT ?", (limit,)).fetchall()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
@dataclass
class ExitRules:
    # Scale-out (the production MEFAI exit lifecycle ported to BSC spot): at the committed
    # target close `tp1_pct`% of the position (TP1), then pull the stop just into
    # profit (`profit_lock_pct` above entry, so the leg can no longer close red)
    # and extend the target to TP2 = entry + `tp2_mult` x the TP1 distance, so the
    # runner rides the rest of the move. Set tp1_pct to 0 or 100 to disable the
    # partial and take the whole leg at the first target.
    tp1_pct: float = float(os.getenv("BNBHACK_TP1_PCT", "50"))
    # The profit lock must clear the round-trip swap cost, otherwise pulling the
    # stop "into profit" still books a net loss once fees/slippage are paid; it
    # is therefore floored at the round-trip cost below.
    profit_lock_pct: float = float(os.getenv("BNBHACK_PROFIT_LOCK_PCT", "0.6"))
    tp2_mult: float = float(os.getenv("BNBHACK_TP2_MULT", "2.0"))
    # Only scale out a TP1 slice when the committed target gain is at least this
    # big; below it the partial would pay a second round-trip cost for a sliver
    # of profit, so the whole leg is taken at the first target instead.
    tp1_min_gain_pct: float = float(os.getenv("BNBHACK_TP1_MIN_GAIN_PCT", "1.0"))
    # Trailing: once a LONG is up `trail_arm_pct`, ratchet the stop to lock
    # `trail_lock_pct` of the move below the running peak.
    trail_arm_pct: float = float(os.getenv("BNBHACK_TRAIL_ARM_PCT", "0.8"))
    trail_lock_pct: float = float(os.getenv("BNBHACK_TRAIL_LOCK_PCT", "0.75"))
    slippage_pct: float = float(os.getenv("BNBHACK_SLIPPAGE_PCT", "1.0"))
    # Exits use a wider slippage than entries: guaranteeing the leg can close
    # matters more than the fill price, so a thin or moving pool never traps a
    # position (a tight exit slippage reverts with too-little-received).
    exit_slippage_pct: float = float(os.getenv("BNBHACK_EXIT_SLIPPAGE_PCT", "3.0"))
    # Estimated PancakeSwap round-trip cost as a percent of position notional.
    # Majors route through V3 0.05% fee pools, so the round-trip fee is ~0.10%
    # (2 x 0.05) and a deep-pool slippage plus BSC gas buffer brings the modelled
    # round-trip to ~0.20%. Subtracted from PAPER PnL only, so the paper book is
    # honest against the live venue; a real (execute=True) close already nets the
    # cost in the swap proceeds and is not double-charged.
    roundtrip_cost_pct: float = float(
        os.getenv("BNBHACK_ROUNDTRIP_COST_PCT", "0.2"))
    # Hard time stop: the out-of-sample walk-forward shows the net-of-cost edge is
    # captured on the 24h holding horizon (the 1h and 4h horizons lose to cost),
    # so a leg that has neither taken profit nor stopped out is held to the 24h
    # horizon before being closed (reason 'time') to bank the live edge. 0
    # disables the time stop.
    max_hold_sec: int = int(os.getenv("BNBHACK_MAX_HOLD_SEC", "86400"))
    # Operator manual hold: a symbol listed here is exempt from EVERY automatic
    # exit (stop / flip / time / target / trail). The leg stays open until the
    # operator closes it by hand. Other symbols trade and exit normally.
    manual_hold: frozenset = frozenset(
        s.strip().upper() for s in
        os.getenv("BNBHACK_MANUAL_HOLD_SYMBOLS", "").split(",") if s.strip())

    def __post_init__(self) -> None:
        # A profit lock below the round-trip cost would "lock in" a net loss, so
        # never let it sit under the cost the close itself pays.
        if self.profit_lock_pct < self.roundtrip_cost_pct:
            self.profit_lock_pct = self.roundtrip_cost_pct


@dataclass
class CloseEvent:
    symbol: str
    reason: str
    exit_price: float
    pnl_usd: float
    pnl_pct: float
    executed: bool
    detail: str = ""
    # A partial (TP1) close shrinks the leg but leaves it open; a full close
    # (stop / trail / target / tp2 / signal-flip) removes it from the book.
    partial: bool = False


class PositionManager:
    """Owns the open/close lifecycle for the agent's LONG spot legs."""

    def __init__(self, store: PositionStore,
                 rules: Optional[ExitRules] = None) -> None:
        self.store = store
        self.rules = rules or ExitRules()
        # Scale-in: split a fresh entry into this many rungs, filled over
        # consecutive confirming cycles (a buy signal that persists). 1 = the
        # whole size in one leg (no laddering). The total notional once every
        # rung is filled equals the size the loop would have opened at once, so
        # the risk envelope is unchanged; only the deployment is staged.
        # 1 = deploy the whole size in one leg (no laddering). Defaulted to 1
        # because every rung pays its own round-trip cost on this fee-heavy spot
        # venue, which eats a thin signal edge; raise it only on a market where
        # the staged fill clearly pays for the extra swaps.
        self.ladder_rungs = max(1, int(os.getenv("BNBHACK_LADDER_RUNGS", "1")))
        # M1 stuck-exit watch: per-position count of consecutive live-close
        # attempts that did not land (gate NO-GO / revert / RPC). Surfaced in the
        # snapshot so a leg that cannot be exited on chain is visible rather than
        # silently orphaned. In-memory (reset on process start) by design: it is
        # an operational alert, not accounting state.
        self._stuck_closes: Dict[int, int] = {}
        self._stuck_alert_after = max(
            1, int(os.getenv("BNBHACK_STUCK_CLOSE_ALERT", "3")))

    def deployed_usd(self) -> float:
        return self.store.deployed_usd()

    # -- entry gating --------------------------------------------------------
    def can_open(self, symbol: str, max_positions: int) -> bool:
        if self.store.has_open(symbol):
            return False
        return self.store.open_count() < max_positions

    def has_open(self, symbol: str) -> bool:
        return self.store.has_open(symbol)

    def _can_add(self, symbol: str) -> bool:
        """A symbol can take another entry rung while it still has rungs to fill
        and TP1 has not yet fired (we never add to a leg that is scaling out)."""
        row = self.store.open_row(symbol)
        if row is None or bool(row["tp1_done"]):
            return False
        return int(row["rungs_filled"] or 1) < int(row["rungs_total"] or 1)

    def entry_mode(self, symbol: str, max_positions: int) -> str:
        """How the loop should treat a fresh buy on `symbol`:
          'open' -> start a new ladder (room under the cap, nothing open),
          'add'  -> fill the next rung of the existing ladder,
          ''     -> blocked (cap full, or the leg is already full / scaling out).
        """
        if self.store.has_open(symbol):
            return "add" if self._can_add(symbol) else ""
        return "open" if self.store.open_count() < max_positions else ""

    # -- record an opened leg (first rung) -----------------------------------
    def record_open(self, *, symbol: str, base: str, token: str,
                    size_usd: float, entry: float, target: float, stop: float,
                    signal_dir: int, swap_result: Optional[Dict[str, Any]],
                    max_positions: int, rungs_total: int = 1,
                    size_target_usd: float = 0.0,
                    open_tx: str = "", is_floor: bool = False) -> Optional[int]:
        if entry <= 0 or size_usd <= 0:
            return None
        # Live: prefer the token amount actually received from the swap; paper
        # (or an unparseable result): derive the qty honestly from size/entry.
        qty = _amount_from_result(swap_result or {})
        if qty is None or qty <= 0:
            qty = size_usd / entry
        try:
            # Atomic guard: re-check no-open + under-cap inside the insert
            # transaction so a stale entry_mode read can never duplicate a leg.
            pid = self.store.add_if_openable({
                "symbol": symbol, "base": base, "token": token,
                "qty_token": qty, "size_usd": size_usd, "entry": entry,
                "target": target, "stop": stop, "signal_dir": signal_dir,
                "opened_ts": _now(), "open_tx": open_tx,
                "rungs_total": max(1, int(rungs_total)), "rungs_filled": 1,
                "size_target_usd": size_target_usd or size_usd,
                "is_floor": bool(is_floor)}, max_positions)
            if pid is None:
                logger.warning(
                    "record_open blocked for %s: open leg / cap re-check failed",
                    symbol)
            return pid
        except Exception as exc:
            logger.warning("record_open failed for %s: %s", symbol, exc)
            return None

    # -- fill another entry rung (scale-in) ----------------------------------
    def record_add(self, *, symbol: str, add_size_usd: float, fill_price: float,
                   swap_result: Optional[Dict[str, Any]]) -> Optional[int]:
        """Add to an open ladder at `fill_price`, moving to the weighted-average
        entry. Stop/target stay where the first rung set them, so the risk
        envelope does not widen as the position is built."""
        if add_size_usd <= 0 or fill_price <= 0:
            return None
        row = self.store.open_row(symbol)
        if row is None or bool(row["tp1_done"]):
            return None
        if int(row["rungs_filled"] or 1) >= int(row["rungs_total"] or 1):
            return None
        add_qty = _amount_from_result(swap_result or {})
        if add_qty is None or add_qty <= 0:
            add_qty = add_size_usd / fill_price
        old_qty = float(row["qty_token"] or 0)
        old_size = float(row["size_usd"] or 0)
        old_entry = float(row["entry"] or fill_price)
        new_qty = old_qty + add_qty
        new_entry = ((old_qty * old_entry + add_qty * fill_price) / new_qty
                     if new_qty > 0 else fill_price)
        new_filled = int(row["rungs_filled"] or 1) + 1
        try:
            self.store.apply_add(row["id"], new_qty, old_size + add_size_usd,
                                 new_entry, new_filled)
            logger.info("ADD(rung %d/%d) %s +$%.2f @ %.8f avg->%.8f",
                        new_filled, int(row["rungs_total"] or 1), symbol,
                        add_size_usd, fill_price, new_entry)
            return int(row["id"])
        except Exception as exc:
            logger.warning("record_add failed for %s: %s", symbol, exc)
            return None

    # -- per-cycle management of every open leg ------------------------------
    async def manage(self, *, latest_side: Dict[str, str],
                     execute: bool) -> List[CloseEvent]:
        """Walk every open position, apply the exit rules, and (when execute)
        sign the closing swap. `latest_side` maps symbol -> 'buy'/'sell' from the
        freshest MEFAI signal so a flip can force an exit."""
        events: List[CloseEvent] = []
        for p in self.store.open_rows():
            try:
                ev = await self._manage_one(p, latest_side, execute)
            except Exception as exc:
                logger.warning("manage failed for %s: %s", p["symbol"], exc)
                continue
            if ev is not None:
                events.append(ev)
        return events

    async def _manage_one(self, p: sqlite3.Row, latest_side: Dict[str, str],
                          execute: bool) -> Optional[CloseEvent]:
        symbol = p["symbol"]
        entry = float(p["entry"] or 0)
        if entry <= 0:
            return None
        mark = await mark_price(symbol, fallback=None)
        if mark is None:
            # No live price this cycle: defer (never guess an exit).
            return None

        d = _leg_dir(p)
        # Favorable extreme tracked in the 'peak' column: the best price the
        # trade has reached in its own direction (highest for a long, lowest for
        # a short). The trailing stop ratchets off this extreme.
        prev_peak = float(p["peak"] or entry)
        peak = max(prev_peak, mark) if d > 0 else min(prev_peak, mark)
        stop = float(p["stop"] or 0)
        target = float(p["target"] or 0)
        tp1_done = bool(p["tp1_done"])

        # Operator manual hold: never auto-close this symbol; just track peak.
        if symbol.upper() in self.rules.manual_hold:
            if peak != prev_peak:
                self.store.update_peak(int(p["id"]), peak)
            return None

        # 1) Stop. Before TP1 it is the committed protective stop ('stop'); after
        #    TP1 it has been pulled into profit, so a hit is a locked-in win and
        #    is reported as a trailing exit, never a loss. A long stops out when
        #    price falls to the stop; a short when price rises to it.
        if stop > 0 and ((d > 0 and mark <= stop) or (d < 0 and mark >= stop)):
            return await self._close(p, mark, "trail" if tp1_done else "stop",
                                     execute)

        # 2) A fresh opposite MEFAI signal closes the whole leg immediately
        #    (a long is closed by a 'sell' flip, a short by a 'buy' flip).
        opp = "sell" if d > 0 else "buy"
        if latest_side.get(symbol) == opp:
            return await self._close(p, mark, "signal-flip", execute)

        # 3) Time stop. The net-of-cost edge is captured on the 24h holding
        #    horizon, so a leg that has neither hit target nor stop is closed
        #    once it has been held past max_hold_sec to bank the edge (reason
        #    'time'). Direction independent.
        if self.rules.max_hold_sec > 0:
            age = _now() - int(p["opened_ts"] or _now())
            if age >= self.rules.max_hold_sec:
                return await self._close(p, mark, "time", execute)

        # 4) Target. The first time, scale out a TP1 slice, lock the stop into
        #    profit and let the runner ride to TP2; the second time (already
        #    scaled out) close the runner at TP2. With TP1 disabled (0 or 100%),
        #    or when the target gain is too small to amortise a second swap, the
        #    first target simply closes the whole leg. A long takes profit when
        #    price rises to the target; a short when price falls to it.
        if target > 0 and ((d > 0 and mark >= target) or (d < 0 and mark <= target)):
            target_gain_pct = (d * (target - entry) / entry * 100.0
                               if entry > 0 else 0.0)
            if (not tp1_done and 0 < self.rules.tp1_pct < 100
                    and target_gain_pct >= self.rules.tp1_min_gain_pct):
                return await self._partial_tp1(p, mark, target, peak, execute)
            return await self._close(p, mark, "tp2" if tp1_done else "target",
                                     execute)

        # 5) No exit: ratchet the trailing stop in the trade's favor, then bump
        #    the favorable extreme (up for a long, down for a short).
        new_stop = self._trail_stop(entry, peak, stop, d)
        if new_stop is not None and (
                (d > 0 and new_stop > stop)
                or (d < 0 and (stop <= 0 or new_stop < stop))):
            self.store.update_stop(p["id"], new_stop, peak)
        elif (d > 0 and peak > prev_peak) or (d < 0 and peak < prev_peak):
            self.store.update_peak(p["id"], peak)
        return None

    async def _partial_tp1(self, p: sqlite3.Row, mark: float, target: float,
                           peak: float, execute: bool) -> Optional[CloseEvent]:
        """Scale out `tp1_pct`% of the leg at the committed target, bank the
        slice, lock the stop into profit and extend the target to TP2."""
        symbol = p["symbol"]
        d = _leg_dir(p)
        # A live perp short is closed in full at the first target: the venue
        # close is reduce-all, and a partial reduce-only leg would pay a second
        # round-trip on a thin slice. A LONG (spot) and a PAPER short keep the
        # scale-out. This routes only the live-perp short to a clean full close.
        if execute and d < 0 and perp_exec.enabled():
            return await self._close(p, mark, "target", execute)
        entry = float(p["entry"] or mark)
        qty = float(p["qty_token"] or 0)
        size = float(p["size_usd"] or 0)
        token = p["token"]
        frac = self.rules.tp1_pct / 100.0
        close_qty = qty * frac
        close_size = size * frac
        exit_price = target  # fill at the committed target
        executed = False
        detail = f"paper TP1 {self.rules.tp1_pct:.0f}%"

        # Only a LONG holds a spot token to sell on the venue; a SHORT leg is
        # paper-only (live shorts route through the perp venue, not spot) so it
        # never signs a spot swap here.
        if execute and d > 0 and close_qty > 0 and token:
            try:
                sw = await bsc_exec.swap(
                    close_qty, token, "USDT",
                    slippage_pct=self.rules.exit_slippage_pct, execute=True,
                    approx_usd=close_qty * mark)
                executed = bool(sw.executed)
                detail = sw.detail
                proceeds = _amount_from_result(sw.result or {})
                if executed and proceeds and proceeds > 0:
                    exit_price = proceeds / close_qty
            except Exception as exc:
                logger.warning("TP1 swap failed for %s: %s", symbol, exc)
                detail = "tp1 swap error"
            if not executed:
                # Live close attempted but the swap did not land (gate NO-GO,
                # revert, RPC). Do NOT book the slice or shrink the leg, or the
                # ledger would desync from the real token balance; defer and let
                # the next cycle retry while the position stays fully open.
                logger.warning("live TP1 not executed for %s (%s); deferring",
                               symbol, detail)
                return None

        slice_pnl = close_qty * d * (exit_price - entry)
        slice_pct = d * (exit_price - entry) / entry * 100.0 if entry > 0 else 0.0
        if not execute:
            # Paper: charge the modelled round-trip swap cost so the paper book
            # is honest against the live venue (a real close already nets it).
            slice_pnl -= close_qty * entry * self.rules.roundtrip_cost_pct / 100.0
            slice_pct -= self.rules.roundtrip_cost_pct
        self.store.add_slice({
            "symbol": symbol, "base": p["base"], "token": token,
            "qty_token": close_qty, "size_usd": close_size, "entry": entry,
            "exit_price": exit_price, "pnl_usd": slice_pnl, "pnl_pct": slice_pct,
            "close_reason": "tp1", "opened_ts": p["opened_ts"]})

        # Pull the stop into profit: above entry for a long, below entry for a
        # short, and only ever in the tightening direction.
        prof = entry * (1.0 + d * self.rules.profit_lock_pct / 100.0)
        cur = float(p["stop"] or 0)
        lock = (max(cur, prof) if d > 0
                else (min(cur, prof) if cur > 0 else prof))
        tp2 = entry + self.rules.tp2_mult * (target - entry)
        self.store.apply_tp1(p["id"], qty - close_qty, size - close_size, lock,
                             tp2, max(peak, mark), slice_pnl)
        logger.info("TP1(%s) %.0f%% @ %.8f pnl=%.2f%% lock->%.8f tp2->%.8f",
                    symbol, self.rules.tp1_pct, exit_price, slice_pct, lock, tp2)
        return CloseEvent(symbol=symbol, reason="tp1", exit_price=exit_price,
                          pnl_usd=slice_pnl, pnl_pct=slice_pct, executed=executed,
                          detail=detail, partial=True)

    def _trail_stop(self, entry: float, peak: float,
                    cur_stop: float, d: int = 1) -> Optional[float]:
        # `peak` is the favorable extreme (highest for a long, lowest for a
        # short). Arm only once the unrealized gain clears the arm threshold,
        # then lock a fraction of the run: below the extreme for a long, above
        # it for a short. Returns a candidate stop only when it tightens.
        gain_pct = d * (peak - entry) / entry * 100.0 if entry > 0 else 0.0
        if gain_pct < self.rules.trail_arm_pct:
            return None
        locked = peak * (1.0 - d * self.rules.trail_lock_pct / 100.0)
        if d > 0:
            return locked if locked > cur_stop else None
        return locked if (cur_stop <= 0 or locked < cur_stop) else None

    async def _close(self, p: sqlite3.Row, mark: float, reason: str,
                     execute: bool) -> Optional[CloseEvent]:
        symbol = p["symbol"]
        d = _leg_dir(p)
        entry = float(p["entry"] or mark)
        qty = float(p["qty_token"] or 0)
        token = p["token"]
        executed = False
        exit_price = mark
        detail = f"paper close ({reason})"

        # A LONG holds a spot token to sell on PancakeSwap; a live SHORT is
        # market-closed (reduce-only) on the perp venue. When perps are disabled
        # (the default) a short leg is paper-only and never signs here.
        if execute and d > 0 and qty > 0 and token:
            # Real exit: sell the held token back to USDT through the gate.
            try:
                sw = await bsc_exec.swap(
                    qty, token, "USDT",
                    slippage_pct=self.rules.exit_slippage_pct,
                    execute=True,
                    approx_usd=qty * mark)
                executed = bool(sw.executed)
                detail = sw.detail
                proceeds = _amount_from_result(sw.result or {})
                if executed and proceeds and proceeds > 0:
                    exit_price = proceeds / qty
            except Exception as exc:
                logger.warning("close swap failed for %s: %s", symbol, exc)
                detail = "close swap error"
            if not executed:
                # Live exit attempted but did not land (gate NO-GO, revert, RPC).
                # Leave the position open so the ledger never claims a close that
                # the real token balance does not reflect; retry next cycle. Count
                # the miss so a leg that repeatedly cannot be exited is surfaced
                # as a stuck-exit alert instead of silently orphaning.
                n = self._stuck_closes.get(int(p["id"]), 0) + 1
                self._stuck_closes[int(p["id"])] = n
                lvl = logger.error if n >= self._stuck_alert_after else logger.warning
                lvl("live close not executed for %s (%s); leaving open "
                    "(stuck attempt %d/%d)", symbol, detail, n,
                    self._stuck_alert_after)
                return None
        elif execute and d < 0 and perp_exec.enabled():
            # Real exit of a live short: market-close (reduce-only) on the perp
            # venue. The fill price marks the exit; on a miss leave the leg open
            # (same stuck-exit guard as the long path) so the ledger never claims
            # a close the venue position does not reflect.
            try:
                po = await perp_exec.close_short(symbol)
                executed = bool(po.executed)
                detail = po.detail
                if executed and po.price and po.price > 0:
                    exit_price = po.price
            except Exception as exc:
                logger.warning("perp close failed for %s: %s", symbol, exc)
                detail = "perp close error"
            if not executed:
                n = self._stuck_closes.get(int(p["id"]), 0) + 1
                self._stuck_closes[int(p["id"])] = n
                lvl = logger.error if n >= self._stuck_alert_after else logger.warning
                lvl("live perp close not executed for %s (%s); leaving open "
                    "(stuck attempt %d/%d)", symbol, detail, n,
                    self._stuck_alert_after)
                return None

        pnl_usd = qty * d * (exit_price - entry)
        pnl_pct = d * (exit_price - entry) / entry * 100.0 if entry > 0 else 0.0
        if not execute:
            # Paper: charge the modelled round-trip swap cost so the paper book
            # is honest against the live venue (a real close already nets it).
            pnl_usd -= qty * entry * self.rules.roundtrip_cost_pct / 100.0
            pnl_pct -= self.rules.roundtrip_cost_pct
        self._stuck_closes.pop(int(p["id"]), None)
        self.store.close(p["id"], exit_price, pnl_usd, pnl_pct, reason)
        logger.info("CLOSE(%s) %s @ %.8f pnl=%.2f%% ($%.2f) executed=%s",
                    reason, symbol, exit_price, pnl_pct, pnl_usd, executed)
        return CloseEvent(symbol=symbol, reason=reason, exit_price=exit_price,
                          pnl_usd=pnl_usd, pnl_pct=pnl_pct, executed=executed,
                          detail=detail)

    # -- cockpit views -------------------------------------------------------
    async def snapshot(self) -> Dict[str, Any]:
        """Open positions with live unrealized PnL + realized total, for state."""
        rows = self.store.open_rows()
        open_out: List[Dict[str, Any]] = []
        unrealized = 0.0
        for p in rows:
            d = _leg_dir(p)
            entry = float(p["entry"] or 0)
            qty = float(p["qty_token"] or 0)
            mark = await mark_price(p["symbol"], fallback=entry) or entry
            u = qty * d * (mark - entry)
            unrealized += u
            open_out.append({
                "symbol": p["symbol"], "entry": round(entry, 8),
                "mark": round(mark, 8), "target": round(float(p["target"] or 0), 8),
                "stop": round(float(p["stop"] or 0), 8),
                "side": "long" if d > 0 else "short",
                "size_usd": round(float(p["size_usd"] or 0), 2),
                "qty": qty, "unrealized_usd": round(u, 2),
                "unrealized_pct": round(d * (mark - entry) / entry * 100.0, 2)
                if entry > 0 else 0.0,
                "tp1_done": bool(p["tp1_done"]),
                "rungs_filled": int(p["rungs_filled"] or 1),
                "rungs_total": int(p["rungs_total"] or 1),
                "realized_partial_usd": round(
                    float(p["realized_partial_usd"] or 0), 2),
                "opened_ts": p["opened_ts"], "open_tx": p["open_tx"] or "",
                # Disclosure: True when this leg was forced by the daily-floor
                # min-1-trade-per-day compliance path, not a conviction signal.
                "is_floor": bool(_row_is_floor(p))})
        closes_out: List[Dict[str, Any]] = []
        for c in self.store.recent_closes(8):
            closes_out.append({
                "symbol": c["symbol"], "reason": c["close_reason"],
                "exit": round(float(c["exit_price"] or 0), 8),
                "pnl_usd": round(float(c["pnl_usd"] or 0), 2),
                "pnl_pct": round(float(c["pnl_pct"] or 0), 2),
                "closed_ts": c["closed_ts"]})
        open_ids = {int(p["id"]) for p in rows}
        stuck = [{"id": pid, "attempts": n}
                 for pid, n in self._stuck_closes.items()
                 if pid in open_ids and n >= self._stuck_alert_after]
        return {
            "open": open_out,
            "open_count": len(open_out),
            "unrealized_usd": round(unrealized, 2),
            "realized_usd": round(self.store.realized_total(), 2),
            "closes": closes_out,
            "stuck_exits": stuck,
        }
