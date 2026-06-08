"""
MEFAI BNB HACK · Autonomous trading loop (Track 1 LIVE driver)

The agent's heart: a self-contained decision loop that runs the full pipeline on
each tick and publishes its live state so the cockpit can show the judged window
accruing in real time.

Per cycle, for every watchlist (symbol, timeframe):
  1. reveal any due pending commitments (disclose what was sealed last tick),
  2. read the live MEFAI signal, fuse ALL sources into one conviction
     (fusion_core), size the bet with drawdown-budget fractional Kelly (sizing),
  3. check the RiskGovernor pre-trade gate (chain_writer.can_trade),
  4. COMMIT a keccak seal of the prediction BEFORE acting (commit-reveal), so the
     judged window is itself un-backfillable,
  5. run the pre-trade security gate and (only when enabled) execute the spot leg
     via the audited bsc_exec adapter,
  6. record equity to the RiskGovernor and publish a state snapshot.

Autonomy + safety:
  - PAPER / DRY by default. Spot swaps sign only when BNBHACK_EXECUTE_TRADES=1;
    commit/reveal/equity sign only when BNBHACK_EXECUTE_CHAIN=1 AND the relevant
    key is configured. With neither, the loop runs fully (decides, gates, plans,
    publishes) and signs nothing.
  - Every spend still passes the bsc_exec security gate; nothing here weakens it.
  - No source failure can crash the loop: each candidate is isolated, and the
    cycle always publishes a heartbeat.
  - The published state JSON carries NO secrets (no salts, no keys); salts live
    only in a local SQLite so a future reveal can recompute the seal.

This module relies only on the already-audited agent modules; it adds
orchestration, not new trading or signing primitives.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import signal as _signal
import sqlite3
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import agent_card
import bsc_exec
import chain_writer
from chain_writer import SIGNAL_BUY, SIGNAL_SELL
from fusion_core import fuse
from fusion_providers import gather_readings
from position_manager import PositionManager, PositionStore
from sizing import SizingInput, size_position

logger = logging.getLogger("mefai.bnbhack.loop")

SIGNAL_DB = os.getenv("MEFAI_SIGNAL_DB",
                      "data/signal.db")

_STATE_DIR = Path(os.getenv(
    "BNBHACK_LOOP_STATE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")))
STATE_PATH = Path(os.getenv("BNBHACK_LOOP_STATE",
                            str(_STATE_DIR / "loop_state.json")))
PENDING_DB = Path(os.getenv("BNBHACK_LOOP_DB",
                            str(_STATE_DIR / "loop_pending.db")))
# Persisted mark-to-market drawdown reference. Surviving a restart here is what
# stops a mid-window restart from re-baselining (and thereby forgiving) an
# accrued drawdown. Priority: BNBHACK_START_EQUITY_USD env > this file > first
# live reading.
START_EQUITY_PATH = Path(os.getenv("BNBHACK_START_EQUITY_FILE",
                                   str(_STATE_DIR / "start_equity.json")))
# Persisted drawdown high-water mark. Without this a mid-window restart would
# reset peak_equity to the live equity (a value already below an earlier peak),
# forgiving the accrued drawdown and letting the sizer over-bet. Persisting the
# peak makes the drawdown budget (and the killswitch margin) survive a restart.
PEAK_EQUITY_PATH = Path(os.getenv("BNBHACK_PEAK_EQUITY_FILE",
                                  str(_STATE_DIR / "peak_equity.json")))

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "1w": 604800,
}

# Bare base -> the BSC spot token the loop would actually buy for a LONG (BTC is
# traded as BTCB on BSC). Bases not listed get a prediction but no spot leg.
_BSC_SPOT = {"BTC": "BTCB", "ETH": "ETH", "BNB": "BNB", "SOL": "SOL",
             "XRP": "XRP", "ADA": "ADA", "DOGE": "DOGE", "CAKE": "CAKE"}


def _now() -> int:
    return int(time.time())


def _base_of(pair: str) -> str:
    s = (pair or "").upper().strip().replace(".P", "")
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


_VALID_HORIZONS = ("1h", "4h", "24h")


def _horizon_for_tf(tf: str) -> str:
    if tf in ("1m", "3m", "5m", "15m", "30m", "1h"):
        return "1h"
    if tf in ("2h", "4h", "6h"):
        return "4h"
    return "24h"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class LoopConfig:
    watchlist: List[str] = field(default_factory=lambda: [
        s.strip().upper() for s in os.getenv(
            "BNBHACK_WATCHLIST", "BTCUSDT,ETHUSDT,BNBUSDT"
        ).split(",") if s.strip()])
    timeframe: str = os.getenv("BNBHACK_TIMEFRAME", "5m")
    # Sizing/edge horizon. The out-of-sample walk-forward shows that at the
    # realistic PancakeSwap V3 round-trip cost only the 24h holding horizon is
    # net-profitable (the 1h and 4h horizons lose to cost), so the agent
    # prioritises 24h: the net-of-cost edge gate is evaluated against the 24h
    # labelled outcome regardless of the scan timeframe. Set BNBHACK_HORIZON=auto
    # to fall back to the per-timeframe mapping (_horizon_for_tf).
    horizon: str = os.getenv("BNBHACK_HORIZON", "24h")
    equity: float = float(os.getenv("BNBHACK_EQUITY", "1000"))
    jury_cap: float = float(os.getenv("BNBHACK_JURY_CAP", "0.20"))
    # Most simultaneous open LONG legs (one per symbol; no pyramiding).
    max_positions: int = int(os.getenv("BNBHACK_MAX_POSITIONS", "3"))
    # Minimum fused conviction (0-100) to act. Raised from a permissive 25 to a
    # more selective 35: a thin signal that only just clears consensus is more
    # likely to be a coin-flip whose edge the round-trip fee eats, so it is now
    # screened out before it even reaches the net-of-cost sizer gate.
    conviction_min: float = float(os.getenv("BNBHACK_CONVICTION_MIN", "35"))
    # Regime filter: when the CMC regime source is risk-off (its contrarian
    # Fear & Greed read votes SHORT) with at least this conviction, stand aside
    # on NEW longs (existing legs keep being managed/exited as normal). Set
    # BNBHACK_REGIME_FILTER=0 to disable; strength 0.5 == F&G >= 75 (extreme
    # greed) given the source's abs(fg-50)/50 scaling.
    regime_filter: bool = os.getenv("BNBHACK_REGIME_FILTER", "1") == "1"
    regime_block_strength: float = float(
        os.getenv("BNBHACK_REGIME_BLOCK_STRENGTH", "0.5"))
    interval: float = float(os.getenv("BNBHACK_LOOP_INTERVAL", "60"))
    reveal_after: float = float(os.getenv("BNBHACK_REVEAL_AFTER", "90"))
    # A reveal already stops at reveal_deadline; this caps wasted gas/retries on
    # a reveal that keeps reverting before the deadline. After the cap the row is
    # closed as 'revealed-paper' (the commit stands; only the reveal is waived).
    reveal_max_attempts: int = int(os.getenv("BNBHACK_REVEAL_MAX_ATTEMPTS", "4"))
    # Finished pending rows older than this are pruned so the store stays bounded
    # over the multi-day live window. Un-revealed commitments are never pruned.
    pending_retention_days: float = float(
        os.getenv("BNBHACK_PENDING_RETENTION_DAYS", "14"))
    include_cmc: bool = os.getenv("BNBHACK_INCLUDE_CMC", "1") == "1"
    execute_trades: bool = os.getenv("BNBHACK_EXECUTE_TRADES", "") == "1"
    execute_chain: bool = os.getenv("BNBHACK_EXECUTE_CHAIN", "") == "1"
    slippage_pct: float = float(os.getenv("BNBHACK_SLIPPAGE_PCT", "1.0"))
    # Minimum seconds between on-ledger equity writes when execute_chain is on.
    # The decision cadence stays at `interval`, but steady-state RiskGovernor
    # writes are throttled to conserve gas over the multi-day live window. A new
    # equity low always forces an immediate write so the drawdown killswitch
    # stays responsive (see run_cycle).
    chain_equity_interval: float = float(
        os.getenv("BNBHACK_CHAIN_EQUITY_INTERVAL", "300"))
    # Mark-to-market: when on, equity is the live wallet USD value (twak
    # totalUsd) instead of the static paper baseline, so the RiskGovernor
    # drawdown reflects real PnL. start_equity_usd pins the drawdown reference
    # (0 = capture the first live reading). chain_equity_baseline is the integer
    # scale the on-ledger vault was registered with (100000 = $1000.00 in cents);
    # live equity is normalised to it so drawdown percent matches the registered
    # high-water mark without re-touching the contract.
    mark_to_market: bool = os.getenv("BNBHACK_MARK_TO_MARKET", "") == "1"
    start_equity_usd: float = float(os.getenv("BNBHACK_START_EQUITY_USD", "0"))
    chain_equity_baseline: int = int(
        os.getenv("BNBHACK_CHAIN_EQUITY_BASELINE", "100000"))

    def mode(self) -> str:
        if self.execute_trades or self.execute_chain:
            bits = []
            if self.execute_trades:
                bits.append("spot")
            if self.execute_chain:
                bits.append("chain")
            return "live:" + "+".join(bits)
        return "paper"


# ---------------------------------------------------------------------------
# Pending-commit store (salts never leave this process)
# ---------------------------------------------------------------------------
class PendingStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        with closing(self._conn()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS pending ("
                " local_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " agent_id TEXT, symbol TEXT, timeframe TEXT, signal INTEGER,"
                " confidence INTEGER, entry INTEGER, target INTEGER, stop INTEGER,"
                " expires_at INTEGER, reveal_deadline INTEGER, salt BLOB,"
                " commit_id INTEGER, committed_ts INTEGER, revealed INTEGER DEFAULT 0,"
                " prediction_id INTEGER, status TEXT, commit_tx TEXT, reveal_tx TEXT,"
                " reveal_attempts INTEGER DEFAULT 0)")
            # Migrate a DB that predates the bounded-reveal-attempt counter. A
            # second run finds the column already present and ignores the error.
            try:
                db.execute("ALTER TABLE pending ADD COLUMN "
                           "reveal_attempts INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, timeout=5)
        c.row_factory = sqlite3.Row
        # WAL keeps the salt-bearing commitment durable across an abrupt restart
        # (a half-written rollback journal cannot strand the store), lets the
        # state publisher read while the loop writes, and synchronous=NORMAL is
        # the safe-with-WAL durability point. busy_timeout absorbs the brief
        # writer overlap instead of raising. Best-effort: a PRAGMA failure must
        # not stop the store from opening.
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass
        return c

    def add(self, rec: Dict[str, Any]) -> int:
        with closing(self._conn()) as db, db:
            cur = db.execute(
                "INSERT INTO pending (agent_id,symbol,timeframe,signal,confidence,"
                "entry,target,stop,expires_at,reveal_deadline,salt,commit_id,"
                "committed_ts,revealed,status,commit_tx) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (rec["agent_id"], rec["symbol"], rec["timeframe"], rec["signal"],
                 rec["confidence"], rec["entry"], rec["target"], rec["stop"],
                 rec["expires_at"], rec["reveal_deadline"], rec["salt"],
                 rec.get("commit_id"), rec["committed_ts"], rec["status"],
                 rec.get("commit_tx", "")))
            return int(cur.lastrowid)

    def due_reveals(self, now: int, reveal_after: float) -> List[sqlite3.Row]:
        with closing(self._conn()) as db, db:
            return db.execute(
                "SELECT * FROM pending WHERE revealed=0 AND status!='expired' "
                "AND committed_ts + ? <= ? AND reveal_deadline >= ? "
                "ORDER BY local_id ASC LIMIT 20",
                (int(reveal_after), now, now)).fetchall()

    def expire_stale(self, now: int) -> None:
        with closing(self._conn()) as db, db:
            db.execute(
                "UPDATE pending SET status='expired' WHERE revealed=0 "
                "AND reveal_deadline < ?", (now,))

    def mark_committed(self, local_id: int, commit_id: Optional[int],
                       commit_tx: str, status: str) -> None:
        """Upgrade a row to its post-send state once the chain commit outcome is
        known. The salt was already persisted by add(), so this only records the
        commit_id / tx / status the reveal path needs."""
        with closing(self._conn()) as db, db:
            db.execute(
                "UPDATE pending SET commit_id=?, commit_tx=?, status=? "
                "WHERE local_id=?", (commit_id, commit_tx, status, local_id))

    def bump_attempt(self, local_id: int) -> int:
        """Count one chain-reveal attempt and return the running total, so the
        loop can stop re-sending after a bounded number of failures."""
        with closing(self._conn()) as db, db:
            db.execute("UPDATE pending SET reveal_attempts = reveal_attempts + 1 "
                       "WHERE local_id=?", (local_id,))
            row = db.execute("SELECT reveal_attempts FROM pending WHERE local_id=?",
                             (local_id,)).fetchone()
            return int(row["reveal_attempts"]) if row else 0

    def mark_revealed(self, local_id: int, prediction_id: Optional[int],
                      reveal_tx: str, status: str = "revealed") -> None:
        with closing(self._conn()) as db, db:
            db.execute(
                "UPDATE pending SET revealed=1, prediction_id=?, reveal_tx=?, "
                "status=? WHERE local_id=?",
                (prediction_id, reveal_tx, status, local_id))

    def prune(self, before_ts: int) -> int:
        """Drop terminal rows (revealed or expired) committed before before_ts so
        the store cannot grow without bound over a multi-day live window. A row
        that is still pending (unrevealed and not expired) is always kept so an
        outstanding commitment can never be lost to pruning. Returns rows removed."""
        with closing(self._conn()) as db, db:
            cur = db.execute(
                "DELETE FROM pending WHERE committed_ts < ? AND "
                "(revealed=1 OR status='expired')", (before_ts,))
            n = cur.rowcount
            # Commit the delete before the checkpoint: TRUNCATE cannot run inside
            # the open write transaction (it would raise "database is locked").
            db.commit()
            # Reclaim the WAL after a bulk delete so the file does not creep.
            try:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            return max(0, int(n or 0))

    def recent(self, limit: int = 12) -> List[sqlite3.Row]:
        with closing(self._conn()) as db, db:
            return db.execute(
                "SELECT * FROM pending ORDER BY local_id DESC LIMIT ?",
                (limit,)).fetchall()


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    symbol: str
    timeframe: str
    action: str                # TRADE_LONG / TRADE_SHORT / SKIP
    direction: int             # +1 / -1 / 0
    conviction: float
    agreement: float
    coverage: float
    entry: float
    target: float
    stop: float
    leverage: float
    notional: float
    margin: float
    win_rate: float
    payoff: float
    reasons: List[str] = field(default_factory=list)
    security: Dict[str, Any] = field(default_factory=dict)
    proof: Dict[str, Any] = field(default_factory=dict)


def _signals_now(watchlist: List[str], tf: str) -> List[Dict[str, Any]]:
    """Latest buy/sell signal per watchlist symbol (read-only)."""
    out: List[Dict[str, Any]] = []
    try:
        db = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
    except Exception as exc:
        logger.warning("signal db open failed: %s", exc)
        return out
    try:
        for pair in watchlist:
            sym = pair if pair.endswith(".P") else f"{pair}.P"
            try:
                row = db.execute(
                    "SELECT signal, timestamp, price FROM signals "
                    "WHERE symbol=? AND timeframe=? ORDER BY id DESC LIMIT 1",
                    (sym, tf)).fetchone()
            except Exception:
                row = None
            if not row:
                continue
            side = str(row["signal"] or "").strip().lower()
            if side not in ("buy", "sell"):
                continue
            try:
                price = float(row["price"] or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                continue
            out.append({"pair": pair, "side": side, "price": price})
    finally:
        db.close()
    return out


class AgentLoop:
    def __init__(self, config: Optional[LoopConfig] = None) -> None:
        self.cfg = config or LoopConfig()
        self.store = PendingStore(PENDING_DB)
        self.pm = PositionManager(PositionStore(
            Path(os.getenv("BNBHACK_POSITION_DB",
                           str(_STATE_DIR / "positions.db")))))
        self.writer = chain_writer.get_writer()
        self.agent_name = agent_card.AGENT_NAME
        self.cycle = 0
        self.started = _now()
        self.peak_equity = self.cfg.equity
        self._stop = asyncio.Event()
        self._agent_id_cache: Optional[str] = None
        # Gas throttle bookkeeping for chain equity writes.
        self._last_equity_record_ts = 0.0
        self._last_equity_recorded: Optional[int] = None
        # Mark-to-market bookkeeping. _start_equity_usd pins the drawdown
        # reference; _last_equity_usd is the fail-safe fallback so a transient
        # balance read can never spuriously RAISE equity and mask a drawdown.
        self._start_equity_usd: Optional[float] = (
            self.cfg.start_equity_usd if self.cfg.start_equity_usd > 0 else None)
        if self._start_equity_usd is None:
            self._start_equity_usd = self._load_start_equity()
        if self._start_equity_usd is not None:
            self.peak_equity = self._start_equity_usd
        # Restore the persisted drawdown high-water mark so a restart cannot
        # forgive an accrued drawdown (it can only ever be the start baseline or
        # higher, never below an earlier peak).
        persisted_peak = self._load_peak_equity()
        if persisted_peak is not None and persisted_peak > self.peak_equity:
            self.peak_equity = persisted_peak
        self._last_equity_usd: Optional[float] = None
        # Wallet<->ledger reconciliation (live only). Advisory: a read-only
        # check that the wallet still holds a bag for every open ledger leg, so
        # a position closed out-of-band (manual sell, external fill) is surfaced
        # as an orphan instead of silently dragging equity toward the DQ line.
        # It never signs anything; resolving an orphan stays an explicit action.
        self._reconcile_note: str = "not yet run"
        self._orphans: List[Dict[str, Any]] = []

    # -- identity ------------------------------------------------------------
    def _agent_id(self) -> str:
        if self._agent_id_cache is None:
            try:
                self._agent_id_cache = self.writer.agent_id(self.agent_name)
            except Exception as exc:
                logger.warning("agent_id compute failed: %s", exc)
                self._agent_id_cache = ""
        return self._agent_id_cache

    # -- mark-to-market reference persistence --------------------------------
    @staticmethod
    def _load_start_equity() -> Optional[float]:
        try:
            with open(START_EQUITY_PATH, "r") as f:
                v = float(json.load(f).get("start_equity_usd"))
            return v if math.isfinite(v) and v > 0 else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _save_start_equity(usd: float) -> None:
        try:
            START_EQUITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(START_EQUITY_PATH.parent),
                                       suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump({"start_equity_usd": usd, "ts": _now()}, f)
            os.replace(tmp, str(START_EQUITY_PATH))
        except Exception as exc:
            logger.warning("start-equity persist failed: %s", exc)

    @staticmethod
    def _load_peak_equity() -> Optional[float]:
        try:
            with open(PEAK_EQUITY_PATH, "r") as f:
                v = float(json.load(f).get("peak_equity_usd"))
            return v if math.isfinite(v) and v > 0 else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _save_peak_equity(usd: float) -> None:
        try:
            PEAK_EQUITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(PEAK_EQUITY_PATH.parent),
                                       suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump({"peak_equity_usd": usd, "ts": _now()}, f)
            os.replace(tmp, str(PEAK_EQUITY_PATH))
        except Exception as exc:
            logger.warning("peak-equity persist failed: %s", exc)

    # -- equity / drawdown ---------------------------------------------------
    async def _read_equity(self, realized: float = 0.0,
                           unrealized: float = 0.0) -> float:
        # Paper baseline unless mark-to-market is enabled. In paper mode equity is
        # the static baseline plus realised PnL from closed positions plus the
        # live unrealised PnL of open positions, so the cockpit (and the drawdown
        # killswitch) track the managed book honestly without signing anything.
        # Live mode reads the wallet's USD value (twak totalUsd) so the drawdown
        # killswitch tracks real PnL. Any read failure falls back to the last
        # GOOD reading (never the static baseline) so a transient RPC hiccup
        # cannot raise equity and mask a real drawdown; the very first reading
        # seeds start + last + peak.
        if not self.cfg.mark_to_market:
            return self.cfg.equity + realized + unrealized
        try:
            res = await bsc_exec.balance()
            if res.ok:
                raw = res.data.get("totalUsd")
                usd = float(raw) if raw is not None else None
                if usd is not None and math.isfinite(usd) and usd > 0:
                    if self._start_equity_usd is None:
                        self._start_equity_usd = usd
                        self.peak_equity = usd
                        self._save_start_equity(usd)
                    self._last_equity_usd = usd
                    return usd
            logger.warning("mark-to-market read failed (%s); using last-good",
                           res.error or "missing totalUsd")
        except Exception as exc:
            logger.warning("mark-to-market exception (%s); using last-good", exc)
        if self._last_equity_usd is not None:
            return self._last_equity_usd
        # No good reading yet: hold at the configured start (or paper baseline)
        # so we neither halt nor reset on a cold-start RPC failure.
        return self._start_equity_usd or self.cfg.equity

    def _drawdown(self, equity: float) -> float:
        if equity > self.peak_equity:
            self.peak_equity = equity
            # Persist each new high so the drawdown budget survives a restart.
            self._save_peak_equity(equity)
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity)

    # -- wallet <-> ledger reconciliation (advisory, read-only) --------------
    @staticmethod
    def _wallet_token_amounts(data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Best-effort map of TOKEN SYMBOL (upper) -> held amount from a twak
        `wallet balance --json` payload, tolerant of a few shapes (a `tokens`
        list of {symbol/token/asset, balance/amount/qty}, or a flat symbol->amt
        dict). Returns None when no token-balance shape is recognised, so the
        caller can skip the check rather than raise a false orphan alarm."""
        if not isinstance(data, dict):
            return None
        out: Dict[str, float] = {}
        raw = data.get("tokens") or data.get("balances") or data.get("assets")
        if isinstance(raw, list):
            for t in raw:
                if not isinstance(t, dict):
                    continue
                sym = (t.get("symbol") or t.get("token") or t.get("asset")
                       or t.get("name"))
                amt = bsc_exec._amount_field(
                    t.get("balance", t.get("amount", t.get("qty"))))
                if isinstance(sym, str) and amt is not None:
                    out[sym.upper()] = amt
        elif isinstance(raw, dict):
            for sym, v in raw.items():
                amt = bsc_exec._amount_field(v)
                if isinstance(sym, str) and amt is not None:
                    out[sym.upper()] = amt
        return out or None

    async def _reconcile_positions(self) -> None:
        """Read-only: flag any open ledger leg the live wallet no longer backs.
        Paper mode has no real bag, so it is a no-op there. Never signs."""
        if not self.cfg.execute_trades:
            self._reconcile_note = "paper mode: no live wallet bag to reconcile"
            self._orphans = []
            return
        try:
            open_rows = self.pm.store.open_rows()
        except Exception as exc:
            self._reconcile_note = f"ledger read failed: {exc}"
            return
        if not open_rows:
            self._reconcile_note = "ok: no open legs"
            self._orphans = []
            return
        try:
            res = await bsc_exec.balance()
        except Exception as exc:
            self._reconcile_note = f"balance read failed: {exc}"
            return
        if not res.ok:
            self._reconcile_note = f"balance read failed: {res.error or 'no data'}"
            return
        held = self._wallet_token_amounts(res.data or {})
        if held is None:
            self._reconcile_note = "balance shape unknown; reconcile skipped"
            return
        orphans: List[Dict[str, Any]] = []
        for p in open_rows:
            tok = (p["token"] or "").upper()
            qty = float(p["qty_token"] or 0)
            if not tok or qty <= 0:
                continue
            have = held.get(tok, 0.0)
            # A leg is orphaned if the wallet holds materially less of the token
            # than the leg claims (closed out-of-band). 1% tolerance absorbs
            # dust / rounding so only a real shortfall trips the alert.
            if have < qty * 0.01:
                orphans.append({"symbol": p["symbol"], "token": tok,
                                "ledger_qty": qty, "wallet_qty": have})
        self._orphans = orphans
        if orphans:
            self._reconcile_note = f"{len(orphans)} orphaned leg(s) detected"
            logger.error("RECONCILE: wallet no longer backs %d open ledger "
                         "leg(s): %s", len(orphans),
                         ", ".join(o["symbol"] for o in orphans))
        else:
            self._reconcile_note = f"ok: {len(open_rows)} leg(s) backed by wallet"

    # -- one decision --------------------------------------------------------
    async def decide(self, sig: Dict[str, Any], equity: float,
                     drawdown: float) -> Decision:
        pair = sig["pair"]
        tf = self.cfg.timeframe
        entry = float(sig["price"])
        d = Decision(symbol=pair, timeframe=tf, action="SKIP", direction=0,
                     conviction=0.0, agreement=0.0, coverage=0.0, entry=entry,
                     target=0.0, stop=0.0, leverage=0.0, notional=0.0,
                     margin=0.0, win_rate=0.0, payoff=0.0)

        readings = await gather_readings(pair, tf, include_cmc=self.cfg.include_cmc)
        fr = fuse(readings)
        d.conviction = fr.conviction
        d.agreement = fr.agreement
        d.coverage = fr.coverage
        d.direction = fr.direction
        if fr.direction == 0:
            d.reasons.append("no directional consensus")
            return d
        if fr.conviction < self.cfg.conviction_min:
            d.reasons.append(
                f"conviction {fr.conviction:.0f} < min {self.cfg.conviction_min:.0f}")
            return d

        # Regime filter: in a risk-off regime stand aside on NEW longs. Reads the
        # CMC regime source directly off the fusion result (its contrarian F&G
        # gauge votes SHORT in extreme greed). Exits of already-open legs are
        # handled by the position manager and are unaffected by this gate.
        if self.cfg.regime_filter and fr.direction > 0:
            reg = next((s for s in fr.sources
                        if s.name == "CMC Regime" and s.available), None)
            if (reg is not None and reg.direction < 0
                    and reg.strength >= self.cfg.regime_block_strength):
                d.reasons.append(
                    f"regime risk-off ({reg.detail}); stand aside on new longs")
                return d

        horizon = (self.cfg.horizon if self.cfg.horizon in _VALID_HORIZONS
                   else _horizon_for_tf(tf))
        sz = size_position(SizingInput(
            symbol=pair, timeframe=tf, equity=equity, current_drawdown=drawdown,
            horizon=horizon, jury_cap=self.cfg.jury_cap,
            conviction=fr.conviction / 100.0))
        d.win_rate = sz.win_rate
        d.payoff = sz.payoff
        if not sz.approved:
            d.reasons.extend(sz.reasons[-2:] or ["sizer declined"])
            return d
        d.leverage = sz.leverage
        d.notional = sz.notional
        d.margin = sz.margin

        sd = sz.stop_distance
        rr = sz.payoff * sd
        if fr.direction > 0:
            d.stop = entry * (1.0 - sd)
            d.target = entry * (1.0 + rr)
        else:
            # Cap the reward fraction so a short target stays a positive price
            # (an unclamped payoff*sd > 1 would underflow the target to 0).
            rr = min(rr, 0.95)
            d.stop = entry * (1.0 + sd)
            d.target = entry * (1.0 - rr)

        # RiskGovernor pre-trade gate (read; honours a deployed halt). Offloaded
        # so the RPC call cannot block the event loop.
        ok, dd_bps, gdetail = await asyncio.to_thread(self.writer.can_trade)
        if not ok:
            d.action = "SKIP"
            d.reasons.append(gdetail)
            return d

        d.action = "TRADE_LONG" if fr.direction > 0 else "TRADE_SHORT"
        d.reasons.append(
            f"{fr.label} conv {fr.conviction:.0f} agree {fr.agreement:.2f} "
            f"lev {sz.leverage:.2f}x")
        return d

    # -- commit + execute + reveal ------------------------------------------
    async def _commit_and_act(self, d: Decision, equity: float,
                              mode: str) -> None:
        now = _now()
        bar = _TF_SECONDS.get(self.cfg.timeframe, 3600)
        expires_at = now + max(3 * bar, 3600)
        reveal_deadline = min(expires_at - 1,
                              now + int(max(2 * self.cfg.interval + 120,
                                            self.cfg.reveal_after + 120)))
        agent_id = self._agent_id()
        sig_enum = SIGNAL_BUY if d.direction > 0 else SIGNAL_SELL
        conf = int(max(0, min(100, round(d.conviction))))
        e_s = chain_writer.to_scaled_price(d.entry)
        t_s = chain_writer.to_scaled_price(d.target)
        s_s = chain_writer.to_scaled_price(d.stop)
        salt = chain_writer.new_salt()

        # Persist the salt-bearing commitment BEFORE signing. A crash in the
        # window between the chain send landing and the local write would
        # otherwise orphan an on-chain commit whose salt is gone (un-revealable
        # forever). The row starts as an honest 'dry' (we never claim a chain
        # proof we cannot yet back) and is upgraded to 'committed' only after the
        # send is confirmed. If the process dies mid-send the row survives with
        # its salt and settles as a paper reveal rather than vanishing.
        local_id: Optional[int] = None
        try:
            local_id = self.store.add({
                "agent_id": agent_id, "symbol": d.symbol,
                "timeframe": d.timeframe, "signal": sig_enum, "confidence": conf,
                "entry": e_s, "target": t_s, "stop": s_s,
                "expires_at": expires_at, "reveal_deadline": reveal_deadline,
                "salt": salt, "commit_id": None, "committed_ts": now,
                "status": "dry", "commit_tx": ""})
        except Exception as exc:
            logger.warning("pending store add failed: %s", exc)

        commit_id = None
        commit_tx = ""
        status = "dry"
        if agent_id:
            try:
                seal = self.writer.seal_of(agent_id, d.symbol, sig_enum, conf,
                                           e_s, t_s, s_s, expires_at, salt)
                out = await asyncio.to_thread(
                    self.writer.commit, agent_id, seal, expires_at,
                    reveal_deadline, execute=self.cfg.execute_chain)
                d.proof["commit"] = out.detail
                if out.executed and out.ok:
                    commit_id = out.extra.get("commit_id")
                    commit_tx = out.tx_hash
                    status = "committed"
                    d.proof["commit_tx"] = chain_writer.ChainWriter.tx_url(commit_tx)
            except Exception as exc:
                logger.warning("commit failed for %s: %s", d.symbol, exc)
                d.proof["commit"] = "commit error"

        # Upgrade the persisted row with the send outcome (commit_id + tx). The
        # salt is already safe on disk; this only records what the reveal needs.
        if local_id is not None and status != "dry":
            try:
                self.store.mark_committed(local_id, commit_id, commit_tx, status)
            except Exception as exc:
                logger.warning("pending store mark_committed failed: %s", exc)

        # Trade leg: a LONG is expressed directly on PancakeSwap spot. A SHORT
        # cannot be expressed on spot (no borrow), so a live short would need a
        # perp venue (ApolloX) which is not wired for signing; a live short is
        # therefore an honest no-go that records nothing, while a PAPER short is
        # simulated (signal_dir=-1, no swap) so the two-sided book earns in down
        # weeks too. 'open' starts a new ladder, 'add' fills the next rung of an
        # existing one; either way one rung = total size / ladder_rungs of
        # exposure this tick (so the full position is built over a few confirming
        # cycles and the total notional matches a single open). A blocked trade
        # ('') still keeps the verifiable commit above; it just takes no exposure.
        if d.action in ("TRADE_LONG", "TRADE_SHORT") and mode in ("open", "add"):
            base = _base_of(d.symbol)
            tok = _BSC_SPOT.get(base)
            if tok is None:
                d.security = {"go": False, "detail": f"no BSC spot token for {base}"}
            else:
                rungs = max(1, self.pm.ladder_rungs)
                # Free collateral = equity minus the notional already committed to
                # open legs, so capital sitting in a position is never re-bet
                # (sizing the new leg against TOTAL equity double-counts it).
                free_usd = max(0.0, equity - self.pm.deployed_usd())
                full_usd = max(0.0, min(d.margin, free_usd,
                                        bsc_exec.MAX_SWAP_USD))
                rung_usd = full_usd / rungs
                if rung_usd <= 0:
                    d.security = {"go": False,
                                  "detail": "trade size collapsed to 0 "
                                            "(no free collateral)"}
                else:
                    # H3: re-read the RiskGovernor immediately before signing the
                    # swap. can_trade was checked in decide(), but a drawdown
                    # halt could have landed in the interim; never sign past a
                    # halt that is now active.
                    g_ok, _g_bps, g_detail = await asyncio.to_thread(
                        self.writer.can_trade)
                    if not g_ok:
                        d.security = {"go": False,
                                      "detail": f"governor halt pre-swap: {g_detail}"}
                        return
                    if d.action == "TRADE_SHORT":
                        # Spot has no borrow leg. Live shorts require a perp venue
                        # (ApolloX) that is not wired for signing, so a live short
                        # is an honest no-go and records NOTHING (the live close
                        # path can never see a short leg). In PAPER the short leg
                        # is recorded with signal_dir=-1 and no swap so the
                        # two-sided book is exercised honestly without signing.
                        if self.cfg.execute_trades:
                            d.security = {"go": False, "executed": False,
                                          "detail": "live short requires perp venue "
                                                    "(ApolloX); paper-simulated only",
                                          "usd": round(rung_usd, 2), "mode": mode,
                                          "rungs": rungs}
                        else:
                            if mode == "open":
                                self.pm.record_open(
                                    symbol=d.symbol, base=base, token=tok,
                                    size_usd=rung_usd, entry=d.entry,
                                    target=d.target, stop=d.stop,
                                    signal_dir=d.direction,
                                    swap_result=None,
                                    max_positions=self.cfg.max_positions,
                                    rungs_total=rungs, size_target_usd=full_usd)
                            else:
                                self.pm.record_add(
                                    symbol=d.symbol, add_size_usd=rung_usd,
                                    fill_price=d.entry, swap_result=None)
                            d.security = {"go": True, "executed": False,
                                          "detail": "paper short leg "
                                                    "(perp venue required for live)",
                                          "usd": round(rung_usd, 2), "mode": mode,
                                          "rungs": rungs}
                        return
                    try:
                        sw = await bsc_exec.swap(
                            rung_usd, "USDT", tok,
                            slippage_pct=self.cfg.slippage_pct,
                            execute=self.cfg.execute_trades,
                            equity=equity,
                            equity_floor=equity * (1.0 - self.cfg.jury_cap),
                            approx_usd=rung_usd)
                        sc = getattr(sw.verdict, "score", None)
                        d.security = {"go": sw.go, "executed": sw.executed,
                                      "score": sc, "detail": sw.detail,
                                      "usd": round(rung_usd, 2), "mode": mode,
                                      "rungs": rungs}
                        # Record when the gate passed: live -> only if the swap
                        # actually executed; paper -> on a GO verdict (simulated)
                        # so the lifecycle is exercised honestly without signing.
                        record_it = (sw.executed if self.cfg.execute_trades
                                     else sw.go)
                        if record_it and mode == "open":
                            self.pm.record_open(
                                symbol=d.symbol, base=base, token=tok,
                                size_usd=rung_usd, entry=d.entry,
                                target=d.target, stop=d.stop,
                                signal_dir=d.direction,
                                swap_result=sw.result,
                                max_positions=self.cfg.max_positions,
                                rungs_total=rungs, size_target_usd=full_usd)
                        elif record_it and mode == "add":
                            self.pm.record_add(
                                symbol=d.symbol, add_size_usd=rung_usd,
                                fill_price=d.entry, swap_result=sw.result)
                    except Exception as exc:
                        logger.warning("spot swap failed for %s: %s", d.symbol, exc)
                        d.security = {"go": False, "detail": "swap error"}
        elif d.action in ("TRADE_LONG", "TRADE_SHORT"):
            d.security = {"go": False,
                          "detail": "position manager full / already built; "
                                    "commit only, no new trade leg"}

    async def _process_reveals(self) -> List[Dict[str, Any]]:
        now = _now()
        try:
            self.store.expire_stale(now)
        except Exception as exc:
            logger.warning("expire_stale failed: %s", exc)
        revealed: List[Dict[str, Any]] = []
        try:
            due = self.store.due_reveals(now, self.cfg.reveal_after)
        except Exception as exc:
            logger.warning("due_reveals failed: %s", exc)
            return revealed
        for r in due:
            if not r["agent_id"]:
                self.store.mark_revealed(r["local_id"], None, "",
                                         status="revealed-paper")
                continue
            try:
                # Only a commitment that actually landed on chain can be revealed
                # on chain; a dry (paper) commit reveals only as a paper record.
                want_chain = (self.cfg.execute_chain
                              and r["commit_id"] is not None)
                # Count the attempt before signing so a reveal that lands but is
                # never acknowledged (process died before mark) cannot re-send
                # indefinitely: after the cap it settles as a paper reveal.
                attempts = (self.store.bump_attempt(r["local_id"])
                            if want_chain else 0)
                out = await asyncio.to_thread(
                    self.writer.reveal,
                    r["commit_id"] if r["commit_id"] is not None else 0,
                    r["agent_id"], r["symbol"], int(r["signal"]),
                    int(r["confidence"]), int(r["entry"]), int(r["target"]),
                    int(r["stop"]), int(r["expires_at"]), bytes(r["salt"]),
                    execute=want_chain)
                pid = out.extra.get("prediction_id")
                tx = chain_writer.ChainWriter.tx_url(out.tx_hash) if out.tx_hash else ""
                if want_chain and not (out.executed and out.ok):
                    # Chain reveal attempt failed. Retry on the next cycle until
                    # the reveal deadline, but stop re-sending once the bounded
                    # attempt budget is spent so a permanently reverting reveal
                    # cannot keep burning gas; settle it as a paper reveal. A cap
                    # of <= 0 means unlimited (retry until the deadline only).
                    if (self.cfg.reveal_max_attempts > 0
                            and attempts >= self.cfg.reveal_max_attempts):
                        self.store.mark_revealed(r["local_id"], pid, out.tx_hash,
                                                 status="revealed-paper")
                    revealed.append({"symbol": r["symbol"], "detail": out.detail,
                                     "tx": tx})
                    continue
                rstatus = "revealed" if (out.executed and out.ok) else "revealed-paper"
                self.store.mark_revealed(r["local_id"], pid, out.tx_hash,
                                         status=rstatus)
                revealed.append({"symbol": r["symbol"], "detail": out.detail,
                                 "tx": tx})
            except Exception as exc:
                logger.warning("reveal failed (%s): %s", r["symbol"], exc)
        return revealed

    # -- one cycle -----------------------------------------------------------
    async def run_cycle(self) -> Dict[str, Any]:
        self.cycle += 1
        now = _now()

        reveals = await self._process_reveals()

        # Keep the pending store bounded over the multi-day live window. Runs
        # roughly hourly (every 60 cycles) and only ever drops finished rows
        # past the retention horizon, never a live commitment. Offloaded so the
        # DELETE + WAL checkpoint never blocks the event loop.
        if self.cfg.pending_retention_days > 0 and self.cycle % 60 == 1:
            try:
                cutoff = now - int(self.cfg.pending_retention_days * 86400)
                pruned = await asyncio.to_thread(self.store.prune, cutoff)
                if pruned:
                    logger.info("pruned %d finished pending rows", pruned)
            except Exception as exc:
                logger.warning("pending prune failed: %s", exc)

        try:
            sigs = _signals_now(self.cfg.watchlist, self.cfg.timeframe)
        except Exception as exc:
            logger.warning("signal scan failed: %s", exc)
            sigs = []
        # Freshest MEFAI side per symbol, so an open LONG exits on a sell flip.
        latest_side = {s["pair"]: s["side"] for s in sigs}

        # Manage (and possibly close) every open position FIRST, then read the
        # equity that reflects realised + unrealised PnL, so new sizing and the
        # drawdown gate see the freshly-marked book.
        try:
            closes = await self.pm.manage(latest_side=latest_side,
                                          execute=self.cfg.execute_trades)
        except Exception as exc:
            logger.warning("position manage failed: %s", exc)
            closes = []
        positions = await self.pm.snapshot()
        equity = await self._read_equity(
            realized=positions.get("realized_usd", 0.0),
            unrealized=positions.get("unrealized_usd", 0.0))
        drawdown = self._drawdown(equity)

        decisions: List[Decision] = []
        for sig in sigs:
            try:
                d = await self.decide(sig, equity, drawdown)
            except Exception as exc:
                logger.warning("decide failed (%s): %s", sig.get("pair"), exc)
                continue
            if d.action != "SKIP":
                # 'open' -> new ladder, 'add' -> next rung, '' -> blocked (cap
                # full / already scaling out). Both a long and a short take a
                # leg (the short is paper-only; see _commit_and_act).
                mode = (self.pm.entry_mode(d.symbol, self.cfg.max_positions)
                        if d.action in ("TRADE_LONG", "TRADE_SHORT") else "")
                try:
                    await self._commit_and_act(d, equity, mode)
                except Exception as exc:
                    logger.warning("commit/act failed (%s): %s", d.symbol, exc)
            decisions.append(d)

        # Record equity to the RiskGovernor (keeper). USD cents integer scale.
        # Chain reads/writes are offloaded so a slow RPC cannot block the loop.
        # Gas throttle: in live (execute_chain) mode the ledger write is rate
        # limited to chain_equity_interval so the keeper's gas budget lasts the
        # full live window. A new equity low (drawdown growing) always forces an
        # immediate write so the killswitch never lags a real drawdown; paper
        # (dry-run) mode is free and always records for an accurate state view.
        # Scale equity into the units the on-ledger vault was registered with. In
        # mark-to-market mode the live USD value is normalised to the registered
        # baseline (equity / start * baseline) so drawdown percent matches the
        # registered high-water mark exactly; paper mode keeps the cents scale.
        if self.cfg.mark_to_market and self._start_equity_usd:
            equity_units = int(round(
                self.cfg.chain_equity_baseline * equity / self._start_equity_usd))
        else:
            equity_units = int(round(equity * 100))
        if self.cfg.execute_chain:
            elapsed = now - self._last_equity_record_ts
            new_low = (self._last_equity_recorded is None
                       or equity_units < self._last_equity_recorded)
            do_record = new_low or elapsed >= self.cfg.chain_equity_interval
        else:
            do_record = True
        if do_record:
            gov_rec = await asyncio.to_thread(
                self.writer.record_equity, equity_units,
                execute=self.cfg.execute_chain)
            self._last_equity_record_ts = now
            self._last_equity_recorded = equity_units
        else:
            gov_rec = chain_writer.TxOutcome(
                executed=False, ok=True, tx_hash="",
                detail=("throttled (gas saver): last write %ds ago, next in %ds"
                        % (int(now - self._last_equity_record_ts),
                           int(max(0, self.cfg.chain_equity_interval
                                   - (now - self._last_equity_record_ts))))))
        gov_ok, gov_dd, gov_detail = await asyncio.to_thread(self.writer.can_trade)
        arena = await asyncio.to_thread(self.writer.arena_stats)
        vault = await asyncio.to_thread(self.writer.vault)

        cycle_closes = [{
            "symbol": c.symbol, "reason": c.reason,
            "exit_price": round(c.exit_price, 8), "pnl_usd": round(c.pnl_usd, 2),
            "pnl_pct": round(c.pnl_pct, 2), "executed": c.executed,
            "partial": c.partial, "detail": c.detail} for c in closes]
        state = self._build_state(now, equity, drawdown, decisions, reveals,
                                  {"ok": gov_ok, "dd_bps": gov_dd,
                                   "detail": gov_detail,
                                   "record": gov_rec.detail},
                                  arena, vault, positions, cycle_closes)
        self._publish(state)
        return state

    def _build_state(self, now: int, equity: float, drawdown: float,
                     decisions: List[Decision], reveals: List[Dict[str, Any]],
                     governor: Dict[str, Any], arena: Dict[str, Any],
                     vault: Dict[str, Any], positions: Dict[str, Any],
                     cycle_closes: List[Dict[str, Any]]) -> Dict[str, Any]:
        proofs: List[Dict[str, Any]] = []
        try:
            for r in self.store.recent(12):
                proofs.append({
                    "symbol": r["symbol"], "signal": int(r["signal"]),
                    "confidence": int(r["confidence"]),
                    "status": r["status"], "committed_ts": int(r["committed_ts"]),
                    "commit_tx": chain_writer.ChainWriter.tx_url(r["commit_tx"] or ""),
                    "reveal_tx": chain_writer.ChainWriter.tx_url(r["reveal_tx"] or ""),
                    "prediction_id": r["prediction_id"]})
        except Exception:
            pass
        return {
            "ts": now,
            "heartbeat": now,
            "cycle": self.cycle,
            "uptime_s": now - self.started,
            "mode": self.cfg.mode(),
            "agent": {
                "name": self.agent_name,
                "wallet": agent_card.AGENT_WALLET,
                "chain_address": self.writer.agent_address,
                "agent_id": self._agent_id(),
            },
            "equity": round(equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown": round(drawdown, 4),
            "jury_cap": self.cfg.jury_cap,
            "internal_cap": round(0.70 * self.cfg.jury_cap, 4),
            "governor": governor,
            "arena": arena,
            "vault": vault,
            "config": {
                "watchlist": self.cfg.watchlist,
                "timeframe": self.cfg.timeframe,
                "interval": self.cfg.interval,
                "conviction_min": self.cfg.conviction_min,
                "include_cmc": self.cfg.include_cmc,
                "max_positions": self.cfg.max_positions,
                "ladder_rungs": self.pm.ladder_rungs,
                "regime_filter": self.cfg.regime_filter,
                "max_hold_sec": self.pm.rules.max_hold_sec,
                "roundtrip_cost_pct": self.pm.rules.roundtrip_cost_pct,
            },
            "positions": positions,
            "reconcile": {"note": self._reconcile_note,
                          "orphans": self._orphans},
            "cycle_closes": cycle_closes,
            "reveals": reveals,
            "decisions": [{
                "symbol": d.symbol, "action": d.action, "direction": d.direction,
                "conviction": round(d.conviction, 1), "agreement": round(d.agreement, 2),
                "coverage": round(d.coverage, 2), "entry": d.entry,
                "target": round(d.target, 8), "stop": round(d.stop, 8),
                "leverage": round(d.leverage, 2), "win_rate": round(d.win_rate, 3),
                "payoff": round(d.payoff, 2), "reasons": d.reasons,
                "security": d.security, "proof": d.proof,
            } for d in decisions],
            "proofs": proofs,
        }

    def _publish(self, state: Dict[str, Any]) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(STATE_PATH.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, separators=(",", ":"))
            os.replace(tmp, str(STATE_PATH))
        except Exception as exc:
            logger.warning("state publish failed: %s", exc)

    # -- run loop ------------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("agent loop start mode=%s watchlist=%s tf=%s interval=%ss",
                    self.cfg.mode(), self.cfg.watchlist, self.cfg.timeframe,
                    self.cfg.interval)
        # Reconcile the ledger against the live wallet once at startup so a leg
        # closed while the agent was down is surfaced before the first decision.
        try:
            await self._reconcile_positions()
            logger.info("startup reconcile: %s", self._reconcile_note)
        except Exception as exc:
            logger.warning("startup reconcile failed: %s", exc)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                st = await self.run_cycle()
                logger.info("cycle %d: %d decisions, mode=%s dd=%.4f",
                            st["cycle"], len(st["decisions"]), st["mode"],
                            st["drawdown"])
            except Exception as exc:
                logger.exception("cycle error: %s", exc)
            elapsed = time.time() - t0
            wait = max(1.0, self.cfg.interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        logger.info("agent loop stopped")


async def _amain(one_shot: bool) -> None:
    loop = AgentLoop()
    if one_shot:
        st = await loop.run_cycle()
        print(json.dumps(st, indent=2))
        return
    running = asyncio.get_running_loop()
    for s in (_signal.SIGINT, _signal.SIGTERM):
        try:
            running.add_signal_handler(s, loop.request_stop)
        except NotImplementedError:
            pass
    await loop.run_forever()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("BNBHACK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="MEFAI BNB HACK autonomous loop")
    ap.add_argument("--once", action="store_true",
                    help="run a single cycle and print the state JSON")
    args = ap.parse_args()
    asyncio.run(_amain(args.once))


if __name__ == "__main__":
    main()
