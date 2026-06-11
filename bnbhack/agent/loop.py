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
import notify
import perp_exec
import x402_feed
from chain_writer import SIGNAL_BUY, SIGNAL_SELL
from fusion_core import fuse
from fusion_providers import gather_readings
from position_manager import (PositionManager, PositionStore,
                               _amount_from_result, mark_price)
from sizing import SizingInput, size_position

logger = logging.getLogger("mefai.bnbhack.loop")

SIGNAL_DB = os.getenv("MEFAI_SIGNAL_DB",
                      "data/signal.db")

# Live-execution risk floors (the agent's own preference, separate from the
# backtested skill engine in sizing.py/tp_sl_optimizer.py which stay pinned for
# reproducibility): a real position is never opened with a stop or target
# tighter than these, so it is not whipsawed out inside intraday noise.
_LIVE_MIN_STOP = float(os.getenv("BNBHACK_LIVE_MIN_STOP", "0.015"))
_LIVE_MIN_TP = float(os.getenv("BNBHACK_LIVE_MIN_TP", "0.025"))
# Fixed TP1 (take-half) target as a fraction, e.g. 0.005 = +0.5%. When > 0 the
# committed target is this near level (the validated managed-mode TP1) instead of
# the payoff-scaled target; the runner then rides to the magnet. 0 = legacy.
_TP1_TARGET_PCT = float(os.getenv("BNBHACK_TP1_TARGET_PCT", "0")) / 100.0

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
# Persisted per-UTC-day executed-trade counter. Surviving a restart here is what
# stops a mid-day restart from re-arming the daily floor after the agent already
# traded earlier in the day (which would double up on fees for no benefit).
DAILY_TRADE_PATH = Path(os.getenv("BNBHACK_DAILY_TRADE_FILE",
                                  str(_STATE_DIR / "daily_trades.json")))

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "1w": 604800,
}

# Track 1 scores PnL ONLY on the fixed list of eligible BEP-20 tokens; a trade
# on any base outside it does not count toward the live ranking. This is the
# eligible-base allowlist (bare bases, as published on the competition token
# list). BTC and BNB are intentionally ABSENT: they are not on the eligible
# list, so longing them would earn zero counted PnL. The watchlist is hard
# filtered against this set at config load, and the spot map below only ever
# routes an eligible base.
_ELIGIBLE_BASES = frozenset({
    "ETH", "XRP", "TRX", "DOGE", "ZEC", "ADA", "LINK", "BCH", "TON", "LTC",
    "AVAX", "SHIB", "DOT", "UNI", "ASTER", "AAVE", "ATOM", "FIL", "INJ", "FET",
    "BONK", "PENGU", "CAKE", "ZRO", "BTT", "FLOKI", "LDO", "PENDLE", "AXS",
    "TWT", "RAY", "COMP", "APE", "SFP", "1INCH", "BANANAS31", "SNX", "YFI",
    "AIOZ", "ZIG", "ROSE", "BRETT", "KAVA", "SUSHI", "ZIL", "ZETA", "BABYDOGE",
})

# Bare base -> the BSC spot token the loop would actually buy for a LONG. ONLY
# eligible bases (see _ELIGIBLE_BASES) that also have liquid Binance-Peg BEP-20
# routing on PancakeSwap appear here; a base absent from this map gets a
# verifiable prediction but no spot leg. BTC/BNB/SOL are excluded by design:
# they are not eligible, so a spot leg there would risk capital on a trade the
# competition does not count.
_BSC_SPOT = {"ETH": "ETH", "XRP": "XRP", "ADA": "ADA", "DOGE": "DOGE",
             "CAKE": "CAKE", "LINK": "LINK", "AVAX": "AVAX", "AAVE": "AAVE",
             "ATOM": "ATOM", "LTC": "LTC"}

# Optional deep-pool allowlist for LIVE spot legs. Empty = trade any routable base
# (current behaviour). Set BNBHACK_SPOT_DEEP_BASES="ETH" (or "ETH,LINK,AVAX") to
# only ever route real capital into genuinely deep BSC pools during the judged
# window; thinner eligible bases still earn a verifiable on-chain prediction but
# take no spot leg, so a near-empty pool can never bleed the live notional.
_SPOT_DEEP_BASES = frozenset(
    b.strip().upper() for b in os.getenv("BNBHACK_SPOT_DEEP_BASES", "").split(",")
    if b.strip())

# Entry freshness gate: a stored signal row older than this many timeframe bars
# is never a NEW entry trigger. 8 bars matches the SIGNAL_DROP_BARS convention
# fusion_providers already uses to drop a stale MEFAI reading, so the row gate
# and the fusion source agree on what stale means; a tighter cutoff (for example
# 2 bars on a quiet 5m book) would starve both normal entries and the daily
# floor for hours after the last alert.
SIGNAL_MAX_AGE_BARS = int(os.getenv("BNBHACK_SIGNAL_MAX_AGE_BARS", "8"))

# Daily-floor last resort: liquidity preference order for the one minimal swap
# placed when the relaxed floor pass still found nothing late in the UTC day.
# This forced leg BYPASSES the net-of-cost edge gate (it exists only to keep the
# >=1-trade/day cadence), so it must route to the CHEAPEST, deepest pool to lose
# the least to fees: ETH first (V3 0.05% deep pool, ~0.2% round-trip), then the
# mid-tier majors. The thin alt pegs (XRP/ADA/DOGE) are intentionally NOT
# preferred here because their ~0.4 to 0.7% round-trip bleeds the floor notional.
_FLOOR_LASTRESORT_PREFERENCE = ("ETH", "LINK", "AVAX")
# Stop/target fraction applied to the last-resort leg (no sizer bucket backs
# it, so a fixed modest envelope bounds the risk on the tiny floor notional).
_FLOOR_LASTRESORT_STOP_FRAC = 0.02


def _now() -> int:
    return int(time.time())


def _tx_hash_from_result(result: Optional[Dict[str, Any]]) -> str:
    """Best-effort extract the on-chain tx hash from a twak swap result so the
    executed spot leg records a BscScan-linkable hash. Looks at the common hash
    keys, then falls back to parsing it out of an explorer URL. Returns '' when
    none is present (a paper or unconfirmed leg), never raises."""
    if not isinstance(result, dict):
        return ""
    for k in ("hash", "txHash", "tx_hash", "transactionHash", "txn_hash"):
        v = result.get(k)
        if isinstance(v, str) and v.startswith("0x") and len(v) >= 10:
            return v
    for k in ("explorer", "explorerUrl", "url", "tx"):
        v = result.get(k)
        if isinstance(v, str) and "/tx/" in v:
            tail = v.split("/tx/")[-1].split("?")[0].split("#")[0].strip()
            if tail.startswith("0x") and len(tail) >= 10:
                return tail
    return ""


def _live_fill(requested_usd: float, input_amount: Optional[float],
               qty_fill: Optional[float]) -> Tuple[float, Optional[float]]:
    """Resolve the REAL spend and fill price of an executed buy. The buy amount is
    clamped inside bsc_exec.swap to the live stable balance, so the source amount
    actually submitted (input_amount) can be far below the requested size; the
    ledger MUST use the real spend, never the request, or it back-computes a
    phantom entry (an $8 request that only filled $0.19 of USDT would otherwise
    record entry = 8/qty, tens of x the true price). Returns (spent_usd,
    fill_price | None); fill_price is None when no token amount is derivable, in
    which case the caller leaves the entry at the signal price."""
    spent = float(requested_usd)
    if input_amount and input_amount > 0:
        spent = float(input_amount)
    fill: Optional[float] = None
    if qty_fill and qty_fill > 0 and spent > 0:
        f = spent / qty_fill
        if math.isfinite(f) and f > 0:
            fill = f
    return spent, fill


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
    # Default universe = eligible BEP-20 majors that ALSO have live MEFAI signal
    # coverage and liquid PancakeSwap routing, so every decision the agent acts
    # on counts toward Track 1. BTC/BNB are deliberately NOT here (not on the
    # eligible token list). Any BNBHACK_WATCHLIST override is still hard filtered
    # against _ELIGIBLE_BASES in __post_init__, so a stray ineligible symbol can
    # never sneak a non-counting trade into the live window.
    watchlist: List[str] = field(default_factory=lambda: [
        s.strip().upper() for s in os.getenv(
            "BNBHACK_WATCHLIST",
            "ETHUSDT,XRPUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,DOGEUSDT,AAVEUSDT,"
            "ATOMUSDT,LTCUSDT"
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
    # Long-only: BSC spot can only be expressed as a LONG (buy a token), so the
    # agent does not risk capital on a short. A sell-direction signal is still
    # COMMITTED on chain as a verifiable PREDICT (zero capital), keeping the record
    # two-sided, but no short position is opened. Default on (on-chain spot reality).
    long_only: bool = os.getenv("BNBHACK_LONG_ONLY", "1") == "1"
    # Managed mode: size on the drawdown budget + conviction and let the validated
    # MANAGEMENT (near TP1 + magnet runner + wide stop) provide the edge, rather
    # than rejecting every signal whose RAW per-cell expectancy is non-positive.
    # The 1h long backtest (PF ~1.38, 4/6 walk-forward folds) validated this.
    managed_mode: bool = os.getenv("BNBHACK_MANAGED_MODE", "0") == "1"
    regime_block_strength: float = float(
        os.getenv("BNBHACK_REGIME_BLOCK_STRENGTH", "0.5"))
    interval: float = float(os.getenv("BNBHACK_LOOP_INTERVAL", "60"))
    reveal_after: float = float(os.getenv("BNBHACK_REVEAL_AFTER", "90"))
    # A chain reveal that keeps failing (e.g. the commit already revealed on a
    # send the process never saw acknowledged, or a node that keeps reverting)
    # is retried only this many times before the row is settled as a paper
    # reveal, so a stuck reveal cannot re-send (and burn gas) until its deadline.
    reveal_max_attempts: int = int(os.getenv("BNBHACK_REVEAL_MAX_ATTEMPTS", "4"))
    # Hard wall-clock ceiling for the reveal pass within one cycle. Each chain
    # reveal blocks on a receipt wait, so a backlog of due reveals could otherwise
    # stall the decision loop for minutes. Once this budget is spent the remaining
    # reveals defer to the next cycle (they stay due until their deadline).
    reveal_cycle_budget_sec: float = float(
        os.getenv("BNBHACK_REVEAL_CYCLE_BUDGET", "30"))
    # Terminal pending rows older than this are pruned so the proof store stays
    # bounded over a multi-day window (0 disables pruning). Unrevealed rows are
    # never pruned.
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
        os.getenv("BNBHACK_CHAIN_EQUITY_INTERVAL", "86400"))
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
    # Track 1 qualifies a wallet only when it makes at least one trade per UTC
    # day (7 over the trading week). The agent is selective by design, so on a
    # genuinely quiet day it could otherwise skip the day and forfeit ranking.
    # When the floor is on (live spot only), if no real trade has executed in the
    # current UTC day by the floor hour, the loop forces ONE minimal long: it
    # relaxes ONLY the selectivity gates (conviction floor + regime stand-aside)
    # and still passes every risk gate (sizer drawdown budget, RiskGovernor halt,
    # full security gate). It never fabricates a trade and never forces past a
    # drawdown halt (a halted agent is already out, so trading more is pointless).
    daily_floor: bool = os.getenv("BNBHACK_DAILY_TRADE_FLOOR", "1") == "1"
    daily_min_trades: int = int(os.getenv("BNBHACK_DAILY_MIN_TRADES", "1"))
    # Only force in the tail of the UTC day, after the agent has had the whole
    # day to find a real high-conviction entry on its own terms.
    daily_floor_hour_utc: int = int(os.getenv("BNBHACK_DAILY_FLOOR_HOUR_UTC", "21"))
    # The forced floor trade is sized down to this small notional (USD), so it
    # satisfies the rule with minimal capital at risk rather than a full bet.
    daily_floor_usd: float = float(os.getenv("BNBHACK_DAILY_FLOOR_USD", "8"))
    # True last resort for the >=1 trade/day rule. The relaxed floor pass above
    # still needs a fused LONG that clears the sizer's bucket-edge gate, so an
    # all-sell day (or a cold signal book) could retry until midnight and DQ
    # the wallet. From this UTC hour, if the floor is still unmet, the loop
    # places ONE minimal daily_floor_usd swap on the most liquid routable
    # eligible base, bypassing only the fusion-direction and bucket-edge
    # SELECTIVITY gates; the full security gate and the RiskGovernor halt check
    # still run, so it can never trade through a halt or a blocked token.
    daily_floor_lastresort_hour_utc: int = int(
        os.getenv("BNBHACK_DAILY_FLOOR_LASTRESORT_HOUR_UTC", "21"))
    # Native x402 consumption: the agent itself buys a premium verified-record
    # feed (the UVII trust index) over the x402 micropayment protocol as part of
    # its own cycle, proving it acts as an agentic-commerce CONSUMER and not only
    # a seller. It runs the full 402 -> EIP-3009 signed authorization -> verify ->
    # 200 handshake; settlement stays deferred to a facilitator, so no funds move
    # and no key is held (safe to leave on by default). Runs at a low cadence to
    # keep the cycle light; the consumed index is surfaced in the published state.
    x402_consume: bool = os.getenv("BNBHACK_X402_CONSUME", "1") == "1"
    x402_product: str = os.getenv("BNBHACK_X402_PRODUCT", "uvii-index")
    x402_consume_every: int = int(os.getenv("BNBHACK_X402_CONSUME_EVERY", "30"))

    def __post_init__(self) -> None:
        # Hard eligibility gate: keep only watchlist symbols whose base is on the
        # Track 1 eligible token list. A trade on an ineligible base earns zero
        # counted PnL, so it must never enter the live universe (whether it came
        # from the default or a BNBHACK_WATCHLIST override). Dropped symbols are
        # logged so a misconfiguration is loud, not silent.
        kept, dropped = [], []
        for pair in self.watchlist:
            if _base_of(pair) in _ELIGIBLE_BASES:
                kept.append(pair)
            else:
                dropped.append(pair)
        if dropped:
            logger.warning("watchlist: dropped ineligible (non-counting) "
                           "symbols %s; eligible set kept %s", dropped, kept)
        self.watchlist = kept

    def mode(self) -> str:
        if self.execute_trades or self.execute_chain:
            bits = []
            if self.execute_trades:
                bits.append("spot")
                if perp_exec.enabled():
                    bits.append("perp")
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
            # Migrate a DB that predates the on-chain outcome-grading flag. A
            # second run finds the column already present and ignores the error.
            try:
                db.execute("ALTER TABLE pending ADD COLUMN "
                           "verified INTEGER DEFAULT 0")
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

    def due_verifications(self, now: int) -> List[sqlite3.Row]:
        """Revealed predictions whose judged window has elapsed and that have
        not yet been graded on chain. These are the rows the oracle resolves to
        TARGET_HIT / STOP_HIT / EXPIRED so the on-chain correct/wrong tally
        stops reading 0/0. Oldest first, capped so one cycle never floods."""
        with closing(self._conn()) as db, db:
            return db.execute(
                "SELECT * FROM pending WHERE revealed=1 AND verified=0 "
                "AND prediction_id IS NOT NULL AND expires_at <= ? "
                "ORDER BY local_id ASC LIMIT 25", (now,)).fetchall()

    def mark_verified(self, prediction_id: int) -> None:
        with closing(self._conn()) as db, db:
            db.execute("UPDATE pending SET verified=1 WHERE prediction_id=?",
                       (int(prediction_id),))

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
    action: str                # TRADE_LONG / TRADE_SHORT / PREDICT / SKIP
                               # PREDICT = verifiable commit-reveal forecast with
                               # NO capital leg (conviction cleared but the sizer
                               # declined the net-of-cost edge, or a governor halt)
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
    is_floor: bool = False      # forced daily-floor trade (kept >=1 trade/day)


def _signal_fresh(ts_raw: Any, tf: str, now: float,
                  max_bars: Optional[int] = None) -> bool:
    """True when a signal row is fresh enough to act on: age at most max_bars
    timeframe bars (default SIGNAL_MAX_AGE_BARS). The signals table stores the
    timestamp as an epoch number; a row whose timestamp cannot be parsed is
    treated as STALE (fail closed: an unreadable age must never trigger a fresh
    entry). Pure so the freshness gate is unit-testable without a database."""
    bars = SIGNAL_MAX_AGE_BARS if max_bars is None else max_bars
    if bars <= 0:  # gate disabled
        return True
    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(ts) or ts <= 0:
        return False
    bar = _TF_SECONDS.get(tf, 3600)
    age = max(0.0, float(now) - ts)
    return age <= bars * bar


def _pick_lastresort_base(spot_map: Dict[str, str], unroutable: Any = (),
                          excluded: Any = ()) -> Optional[Tuple[str, str]]:
    """Pick the base for the daily-floor last-resort swap: the most liquid
    routable eligible base, preference order ETH then XRP then ADA, then the
    remaining spot-map bases alphabetically. `unroutable` is the audit result
    from bsc_exec (bases with no token route); `excluded` removes bases the
    book already holds. Returns (base, token) or None when nothing qualifies.
    Pure so the selection is unit-testable without the chain adapter."""
    bad = {str(b).upper() for b in (unroutable or ())}
    bad |= {str(b).upper() for b in (excluded or ())}
    ordered = [b for b in _FLOOR_LASTRESORT_PREFERENCE if b in spot_map]
    ordered += sorted(b for b in spot_map
                      if b not in _FLOOR_LASTRESORT_PREFERENCE)
    for base in ordered:
        if base not in bad and spot_map.get(base):
            return base, spot_map[base]
    return None


def _signals_now(watchlist: List[str], tf: str) -> List[Dict[str, Any]]:
    """Latest FRESH buy/sell signal per watchlist symbol (read-only). A row
    older than SIGNAL_MAX_AGE_BARS timeframe bars is skipped: acting on a
    days-old stored price would enter at a level the market has long left.
    The daily-floor last resort (see _daily_floor_lastresort) intentionally
    does NOT depend on these rows, so this gate cannot starve the floor."""
    out: List[Dict[str, Any]] = []
    try:
        db = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
    except Exception as exc:
        logger.warning("signal db open failed: %s", exc)
        return out
    now = time.time()
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
            if not _signal_fresh(row["timestamp"], tf, now):
                continue
            try:
                price = float(row["price"] or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                continue
            out.append({"pair": pair, "side": side, "price": price,
                        "ts": row["timestamp"]})
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
        # Raw (pre-normalisation) equity at the last ledger write. A raw drawdown
        # that rounds to the same integer vault units must still force a write so
        # the killswitch tracks real PnL, not the quantised value.
        self._last_equity_raw: Optional[float] = None
        # Debounce for a SHARP single-cycle equity drop. A transient partial
        # wallet read (twak momentarily omits a held token) looks like a large
        # one-cycle loss and would latch the on-chain RiskGovernor halt. We
        # require such a sharp drop to persist across two consecutive reads
        # before it is written on-chain; a real drawdown persists (writes within
        # a cycle), a transient artifact recovers and is discarded.
        self._sharp_drop_streak: int = 0
        # Rolling equity history for the live equity curve. Seeded from the last
        # published snapshot so a restart continues the same curve rather than
        # resetting it. Each entry is [ts, equity] and the ring is capped.
        self._equity_hist: List[List[float]] = self._load_equity_hist()
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
        # Per-UTC-day executed-trade counter for the daily-trade floor, restored
        # so a mid-day restart does not re-arm the floor after an earlier trade.
        self._trade_day, self._trades_today = self._load_daily_trades()
        self._floor_note: str = ""
        # PREDICT-only commit dedup: one verifiable forecast per distinct signal
        # event (symbol, direction, signal timestamp). A signal stays "fresh" for
        # several bars, so without this a PREDICT-only call would re-commit (and
        # spend gas) every cycle the same alert is still fresh. Bounded; resets on
        # restart (at worst one extra forecast for a still-fresh signal). The
        # capital TRADE path keeps its own position/ladder dedup and is untouched.
        self._predicted_keys: set = set()
        # Native x402 consumption bookkeeping: the last consumed feed result and
        # the cycle it was bought on, surfaced in the published state. The buyer
        # config is the deployer's published terms (recipient + asset + network),
        # read once from the same env the public feed endpoint uses.
        self._x402_last: Optional[Dict[str, Any]] = None
        self._x402_cfg = x402_feed.RequirementsConfig(
            # The 0x..0001 default is a deliberate deferred-settlement
            # placeholder (settlement is deferred to a facilitator, no funds
            # move), not a real recipient; a live deployment sets BNBHACK_X402_PAYTO.
            pay_to=os.getenv("BNBHACK_X402_PAYTO", "0x" + "00" * 19 + "01"),
            asset=os.getenv("BNBHACK_X402_ASSET",
                            "0x55d398326f99059fF775485246999027B3197955"),
            network=os.getenv("BNBHACK_X402_NETWORK", "bsc"),
            asset_name=os.getenv("BNBHACK_X402_ASSET_NAME", "BSC-USD"),
            asset_version=os.getenv("BNBHACK_X402_ASSET_VERSION", "1"))

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

    # -- daily-trade floor ---------------------------------------------------
    @staticmethod
    def _utc_day(now: int) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(now))

    @staticmethod
    def _load_daily_trades() -> Tuple[str, int]:
        try:
            with open(DAILY_TRADE_PATH, "r") as f:
                d = json.load(f)
            day = str(d.get("day") or "")
            cnt = int(d.get("count") or 0)
            return day, max(0, cnt)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return "", 0

    def _save_daily_trades(self) -> None:
        try:
            DAILY_TRADE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(DAILY_TRADE_PATH.parent),
                                       suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump({"day": self._trade_day,
                           "count": self._trades_today, "ts": _now()}, f)
            os.replace(tmp, str(DAILY_TRADE_PATH))
        except Exception as exc:
            logger.warning("daily-trade persist failed: %s", exc)

    def _roll_daily(self, now: int) -> None:
        """Reset the per-day counter when the UTC date rolls over."""
        day = self._utc_day(now)
        if day != self._trade_day:
            self._trade_day = day
            self._trades_today = 0
            self._save_daily_trades()

    def _record_executed_trades(self, n: int) -> None:
        if n > 0:
            self._trades_today += n
            self._save_daily_trades()

    def _floor_due(self, now: int) -> bool:
        """True when the daily floor should force a qualifying trade: live spot,
        floor enabled, still short of the daily minimum, and in the tail of the
        UTC day so the agent had the whole day to enter on its own terms."""
        if not (self.cfg.execute_trades and self.cfg.daily_floor):
            return False
        if self._trades_today >= self.cfg.daily_min_trades:
            return False
        return time.gmtime(now).tm_hour >= self.cfg.daily_floor_hour_utc

    def _floor_lastresort_due(self, now: int) -> bool:
        """True when the floor is due AND the day is so late that waiting for a
        signal-driven candidate risks the daily-minimum DQ outright."""
        return (self._floor_due(now)
                and time.gmtime(now).tm_hour
                >= self.cfg.daily_floor_lastresort_hour_utc)

    def _unroutable_bases(self, bases: List[str]) -> List[str]:
        """Bases the bsc_exec token registry cannot route to a spot token.
        Prefers the adapter's own assert_routable audit when present; falls
        back to resolving each base's mapped spot token through the registry.
        Best-effort: an adapter fault returns [] and never blocks the loop."""
        ups = sorted({str(b).upper() for b in bases if b})
        try:
            fn = getattr(bsc_exec, "assert_routable", None)
            if callable(fn):
                return sorted({str(b).upper() for b in (fn(ups) or [])})
            return [b for b in ups
                    if bsc_exec._resolve_token(_BSC_SPOT.get(b, b)) is None]
        except Exception as exc:
            logger.warning("routability audit failed: %s", exc)
            return []

    def _audit_routability(self) -> None:
        """Startup audit: LOUDLY flag every configured base (spot map plus
        watchlist) that has no route in the bsc_exec token registry, so a
        symbol that can only ever produce commit-only decisions (and can never
        satisfy the daily floor) is visible on day one, not on the night the
        floor fails. Advisory only; the loop never crashes over it."""
        bases = sorted(set(_BSC_SPOT)
                       | {_base_of(p) for p in self.cfg.watchlist})
        bad = self._unroutable_bases(bases)
        if bad:
            logger.error(
                "ROUTABILITY WARNING: %d configured base(s) have NO spot route "
                "in the bsc_exec token registry and can never take a live spot "
                "leg (decisions there stay commit-only): %s",
                len(bad), ", ".join(bad))
        else:
            logger.info("routability audit: all %d configured bases route",
                        len(bases))

    async def _daily_floor_trade(self, equity: float, drawdown: float,
                                 sigs: List[Dict[str, Any]]) -> Decision:
        """Force ONE minimal long to keep the wallet at >=1 trade/day. Relaxes
        only the selectivity gates (conviction floor + regime stand-aside);
        every risk gate (sizer drawdown budget, RiskGovernor, security gate)
        still applies. Picks the highest-conviction long available this cycle.
        Returns the floor Decision (action SKIP if none is eligible this tick;
        the loop retries on the next cycle inside the window)."""
        # COMPLIANCE PATH (the competition's min-1-trade-per-day rule). This is
        # NOT a conviction trade: it deliberately relaxes the selectivity gates
        # to keep the wallet's cadence and avoid the no-trade-day forfeit. Every
        # leg it opens is flagged is_floor=True so it is disclosed in /loop/state,
        # on the open position record, and in the broadcast, and is kept separate
        # from edge-driven trades. It is sized minimally (clamped to
        # daily_floor_usd in decide(), see the force-clamp block).
        best: Optional[Decision] = None
        for sig in sigs:
            try:
                d = await self.decide(sig, equity, drawdown, force=True)
            except Exception as exc:
                logger.warning("floor decide failed (%s): %s",
                               sig.get("pair"), exc)
                continue
            # Only a real spot LONG is an executable on-chain trade (a short is
            # paper-only without a perp venue, so it would not satisfy the rule).
            if d.action == "TRADE_LONG" and (best is None
                                             or d.conviction > best.conviction):
                best = d
        if best is None:
            d = Decision(symbol="-", timeframe=self.cfg.timeframe, action="SKIP",
                         direction=0, conviction=0.0, agreement=0.0, coverage=0.0,
                         entry=0.0, target=0.0, stop=0.0, leverage=0.0,
                         notional=0.0, margin=0.0, win_rate=0.0, payoff=0.0,
                         is_floor=True)
            d.reasons.append("daily floor: no eligible long this cycle; retrying")
            self._floor_note = d.reasons[-1]
            return d
        best.is_floor = True
        mode = self.pm.entry_mode(best.symbol, self.cfg.max_positions)
        if mode not in ("open", "add"):
            best.action = "SKIP"
            best.security = {"go": False,
                             "detail": "daily floor: position cap full "
                                       "(book already deployed, day is active)"}
            self._floor_note = best.security["detail"]
            return best
        try:
            await self._commit_and_act(best, equity, mode)
        except Exception as exc:
            logger.warning("daily floor commit/act failed (%s): %s",
                           best.symbol, exc)
            self._floor_note = "daily floor: execution error"
            return best
        executed = isinstance(best.security, dict) and best.security.get("executed")
        self._floor_note = (
            f"daily floor executed {best.symbol}" if executed
            else f"daily floor attempted {best.symbol}: "
                 f"{(best.security or {}).get('detail', 'no fill')}")
        return best

    async def _daily_floor_lastresort(self, equity: float) -> Optional[Decision]:
        """TRUE last resort for the >=1 trade/day rule, run only after the
        relaxed floor pass kept failing into the final UTC hours. The relaxed
        pass still needs a fused LONG that clears the sizer's bucket-edge gate,
        so an all-sell day would otherwise retry until midnight and forfeit the
        wallet's ranking. This branch places ONE minimal daily_floor_usd swap
        on the most liquid routable eligible base (preference ETH, LINK, AVAX),
        with NO dependency on signal rows. It bypasses ONLY the
        fusion-direction and bucket-edge selectivity gates; the RiskGovernor
        halt check runs here and again pre-swap, and the swap goes through
        bsc_exec.swap, i.e. the exact tx_security_solver evaluate path every
        normal leg runs. It is exempt from the position cap (one extra minimal
        leg; the position manager then manages and time-stops it like any
        other), and the commit-reveal proof path runs for it like any trade."""
        # COMPLIANCE PATH (the competition's min-1-trade-per-day rule), TRUE last
        # resort. NOT a conviction trade: it bypasses ONLY the fusion-direction
        # and bucket-edge selectivity gates to keep the wallet's cadence and
        # avoid the no-trade-day forfeit; the security gate and RiskGovernor stay
        # enforced. The leg it opens is flagged is_floor=True so it is disclosed
        # in /loop/state, on the open position record, and in the broadcast, and
        # is kept separate from edge-driven trades. It is sized minimally (exactly
        # one daily_floor_usd swap).
        usd = max(0.0, self.cfg.daily_floor_usd)
        if usd <= 0:
            self._floor_note = "daily floor last resort: floor size is 0"
            return None
        # Never trade through a halt: check the RiskGovernor BEFORE quoting.
        g_ok, _bps, g_detail = await asyncio.to_thread(self.writer.can_trade)
        if not g_ok:
            self._floor_note = f"daily floor last resort blocked: {g_detail}"
            logger.warning(self._floor_note)
            return None
        # Candidate bases the book does not already hold (a held base needs an
        # 'add', whose rung ledger may be full) and that are NOT manual-hold (a
        # manual-hold base would open a leg the auto-exit can never close), in
        # preference order then alphabetical. We iterate and try EACH candidate's
        # quote until one fills, so a single thin/transient route failure falls
        # through to the next base instead of forfeiting the whole day (DQ).
        try:
            held = {b for b in _BSC_SPOT if self.pm.has_open(f"{b}USDT")}
        except Exception:
            held = set()
        held |= {b for b in _BSC_SPOT
                 if f"{b}USDT".upper() in self.pm.rules.manual_hold}
        unroutable = set(self._unroutable_bases(list(_BSC_SPOT)))
        ordered = [b for b in _FLOOR_LASTRESORT_PREFERENCE if b in _BSC_SPOT]
        ordered += sorted(b for b in _BSC_SPOT if b not in ordered)
        candidates = [b for b in ordered if b not in held and b not in unroutable]
        if not candidates:
            self._floor_note = ("daily floor last resort: no routable free "
                                "base available")
            logger.error(self._floor_note)
            return None
        # Live entry mark from a fresh quote (usd in / token out), so the commit
        # and the stop/target envelope reflect the market now, not a stale price.
        base = tok = None
        entry = 0.0
        for cand in candidates:
            ctok = _BSC_SPOT[cand]
            try:
                q = await bsc_exec.quote(usd, "USDT", ctok, self.cfg.slippage_pct)
            except Exception as exc:
                logger.warning("daily floor last resort quote failed (%s): %s",
                               cand, exc)
                continue
            out_amt = (bsc_exec._amount_field((q.data or {}).get("output"))
                       if q is not None and q.ok else None)
            if out_amt and out_amt > 0:
                base, tok, entry = cand, ctok, usd / out_amt
                break
        if base is None:
            self._floor_note = ("daily floor last resort: no candidate quote "
                                "available across the eligible deep pools")
            logger.warning(self._floor_note)
            return None
        symbol = f"{base}USDT"
        d = Decision(
            symbol=symbol, timeframe=self.cfg.timeframe, action="TRADE_LONG",
            direction=1, conviction=0.0, agreement=0.0, coverage=0.0,
            entry=entry, target=entry * (1.0 + _FLOOR_LASTRESORT_STOP_FRAC),
            stop=entry * (1.0 - _FLOOR_LASTRESORT_STOP_FRAC), leverage=1.0,
            notional=usd, margin=usd, win_rate=0.0, payoff=0.0, is_floor=True)
        d.reasons.append("daily floor last resort: minimal qualifying swap "
                         "(selectivity gates bypassed; security gate and "
                         "RiskGovernor still enforced)")
        try:
            await self._commit_and_act(d, equity, "open", cap_exempt=True)
        except Exception as exc:
            logger.warning("daily floor last resort commit/act failed (%s): %s",
                           symbol, exc)
            self._floor_note = "daily floor last resort: execution error"
            return d
        executed = isinstance(d.security, dict) and d.security.get("executed")
        self._floor_note = (
            f"daily floor last resort executed {symbol}" if executed
            else f"daily floor last resort attempted {symbol}: "
                 f"{(d.security or {}).get('detail', 'no fill')}")
        return d

    # -- equity / drawdown ---------------------------------------------------
    # Stablecoins twak holds at face value. twak's totalUsd omits any token it
    # cannot price (it returns usd=None for them), so a wallet that swaps native
    # gas into USDT would otherwise read as a phantom ~50% drawdown. We add the
    # face value of any held stablecoin twak left unpriced.
    _STABLES = ("USDT", "USDC", "BUSD", "FDUSD", "DAI", "USD1", "TUSD", "USDD")

    @classmethod
    def _unpriced_stable_usd(cls, data: Dict[str, Any]) -> float:
        """Sum balances of held stablecoins twak did NOT already value (usd
        missing/None), so each is counted once and only once."""
        if not isinstance(data, dict):
            return 0.0
        raw = data.get("tokens") or data.get("balances") or data.get("assets")
        if not isinstance(raw, list):
            return 0.0
        total = 0.0
        for t in raw:
            if not isinstance(t, dict):
                continue
            sym = (t.get("symbol") or t.get("token") or t.get("asset") or "")
            if not isinstance(sym, str) or sym.upper() not in cls._STABLES:
                continue
            priced = t.get("usd", t.get("valueUsd", t.get("usdValue")))
            if priced is not None:
                continue  # already in totalUsd, do not double count
            amt = bsc_exec._amount_field(
                t.get("balance", t.get("amount", t.get("qty"))))
            if amt is not None and math.isfinite(amt) and amt > 0:
                total += amt
        return total

    @classmethod
    def _unpriced_position_usd(cls, data: Dict[str, Any],
                               open_positions: List[Dict[str, Any]]) -> float:
        """Value open LONG-position tokens that twak's totalUsd did NOT price
        (usd None/absent), at qty x mark. A held tradeable asset (e.g. ETH after
        a spot buy) is otherwise dropped from equity and reads as a phantom
        drawdown that would trip the killswitch. Skips tokens twak already priced
        (no double count) and stablecoins (counted by _unpriced_stable_usd)."""
        if not isinstance(data, dict) or not open_positions:
            return 0.0
        priced: set = set()
        raw = data.get("tokens") or data.get("balances") or data.get("assets")
        if isinstance(raw, list):
            for t in raw:
                if not isinstance(t, dict):
                    continue
                sym = (t.get("symbol") or t.get("token") or t.get("asset") or "")
                pv = t.get("usd", t.get("valueUsd", t.get("usdValue")))
                if isinstance(sym, str) and pv is not None:
                    priced.add(sym.upper())
        total = 0.0
        for p in open_positions:
            if (p.get("side") or "long") != "long":
                continue  # a short holds no spot token
            base = str(p.get("symbol") or "").upper()
            for q in ("USDT", "USDC", "BUSD", "FDUSD"):
                if base.endswith(q):
                    base = base[: -len(q)]
                    break
            base = base.replace(".P", "")
            if not base or base in priced or base in cls._STABLES:
                continue  # already in totalUsd, or a stablecoin counted elsewhere
            qty = float(p.get("qty") or 0.0)
            mark = float(p.get("mark") or 0.0)
            v = qty * mark
            if math.isfinite(v) and v > 0:
                total += v
        return total

    def _equity_rpc_sync(self, bnb_px: float,
                         open_positions: List[Dict[str, Any]]) -> Optional[float]:
        """Total portfolio USD straight from chain RPC, independent of twak's
        flaky (and token-blind) balance endpoint: native BNB at its mark, idle
        stablecoins at face (balanceOf), and open long-position tokens at
        qty x mark. Sync (web3 HTTP); run in a worker thread. None on failure."""
        try:
            w3 = self.writer._w3
            if w3 is None:
                self.writer._ensure()
                w3 = self.writer._w3
            if w3 is None:
                return None
            from web3 import Web3
            addr = Web3.to_checksum_address(bsc_exec.AGENT_WALLET)
            total = (w3.eth.get_balance(addr) / 1e18) * (bnb_px or 0.0)
            for sym in ("USDT", "USDC", "BUSD"):
                taddr = bsc_exec.BSC_TOKENS.get(sym)
                if not taddr:
                    continue
                data = "0x70a08231" + addr[2:].lower().rjust(64, "0")
                raw = w3.eth.call({"to": Web3.to_checksum_address(taddr),
                                   "data": data})
                bal = int(raw.hex() or "0x0", 16) / 1e18
                if math.isfinite(bal) and bal > 0:
                    total += bal  # stablecoin at face value
            for p in (open_positions or []):
                if (p.get("side") or "long") != "long":
                    continue
                qty = float(p.get("qty") or 0.0)
                mark = float(p.get("mark") or 0.0)
                v = qty * mark
                if math.isfinite(v) and v > 0:
                    total += v
            return total if math.isfinite(total) and total > 0 else None
        except Exception as exc:
            logger.warning("rpc equity read failed: %s", exc)
            return None

    async def _read_equity(self, realized: float = 0.0,
                           unrealized: float = 0.0,
                           open_positions: Optional[List[Dict[str, Any]]] = None
                           ) -> float:
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
        # PRIMARY: value the portfolio straight from chain RPC (native BNB at
        # mark + idle stablecoins at face + open long-position tokens at mark).
        # This is reliable and token-complete, unlike twak's balance endpoint
        # which is intermittently killed and prices neither USDT nor freshly
        # bought tokens (which would read as a phantom drawdown). twak is the
        # fallback only if RPC is unavailable.
        try:
            bnb_px = await mark_price("BNBUSDT", fallback=0.0) or 0.0
            rpc_usd = await asyncio.to_thread(self._equity_rpc_sync, bnb_px,
                                              open_positions or [])
            if rpc_usd is not None and math.isfinite(rpc_usd) and rpc_usd > 0:
                if perp_exec.enabled():
                    pe = await perp_exec.account_equity_usd()
                    if pe is not None:
                        rpc_usd += pe
                if self._start_equity_usd is None:
                    self._start_equity_usd = rpc_usd
                    self.peak_equity = rpc_usd
                    self._save_start_equity(rpc_usd)
                self._last_equity_usd = rpc_usd
                return rpc_usd
        except Exception as exc:
            logger.warning("rpc equity primary failed (%s); trying twak", exc)
        try:
            res = await bsc_exec.balance()
            if res.ok:
                raw = res.data.get("totalUsd")
                # twak's totalUsd is the native + priced-token total; it OMITS
                # unpriced tokens (e.g. USDT), so we add held stablecoins at face
                # value on top. A None/non-finite totalUsd means the read itself
                # failed (NOT an empty wallet): treat it as untrustworthy and fall
                # through to last-good below, because computing stablecoins-only
                # would drop the native BNB and look like a phantom drawdown. A
                # real trading wallet always holds BNB gas, so a healthy read is a
                # positive number that the stablecoin add then augments.
                usd = float(raw) if raw is not None else None
                if usd is not None and math.isfinite(usd):
                    usd += self._unpriced_stable_usd(res.data)
                    # value held long-position tokens twak did not price (e.g.
                    # ETH after a spot buy) so a real holding is never read as a
                    # phantom drawdown that trips the killswitch.
                    usd += self._unpriced_position_usd(res.data,
                                                       open_positions or [])
                else:
                    usd = None
                if usd is not None and math.isfinite(usd) and usd > 0:
                    # Fold the perp venue's account equity (margin + open uPnL)
                    # into the mark so a live short's risk is VISIBLE to the
                    # drawdown governor. If the perp leg is enabled but its equity
                    # read fails this cycle, hold last-good rather than publish a
                    # total that omits the short (which would look like a phantom
                    # drawdown / recovery and could mis-fire the killswitch).
                    if perp_exec.enabled():
                        pe = await perp_exec.account_equity_usd()
                        if pe is None:
                            logger.warning(
                                "perp equity unavailable; using last-good combined")
                            if self._last_equity_usd is not None:
                                return self._last_equity_usd
                        else:
                            usd += pe
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
        except Exception:
            logger.exception("reconcile: ledger read failed")
            self._reconcile_note = "ledger read failed"
            return
        if not open_rows:
            self._reconcile_note = "ok: no open legs"
            self._orphans = []
            return
        # RPC-primary balance: the twak balance read is flaky and a transient
        # zero would false-orphan a real leg and wrongly skip its exit, so each
        # leg's token balance is read straight from the chain and a leg is never
        # orphaned on an unavailable read.
        orphans: List[Dict[str, Any]] = []
        unknown = 0
        for p in open_rows:
            # Short legs are backed by the perp venue, not a spot token in the
            # BSC wallet, so the wallet-balance reconcile does not apply to them.
            try:
                if int(p["signal_dir"] or 1) < 0:
                    continue
            except (TypeError, ValueError, IndexError):
                pass
            tok = (p["token"] or "")
            qty = float(p["qty_token"] or 0)
            if not tok or qty <= 0:
                continue
            have = bsc_exec._wallet_token_balance(
                bsc_exec._resolve_token(tok) or tok)
            if have is None:
                unknown += 1
                continue  # unknown read: never orphan on a miss
            # A leg is orphaned only if the chain shows materially less of the
            # token than the leg claims. 1% tolerance absorbs dust / rounding.
            if have < qty * 0.01:
                orphans.append({"symbol": p["symbol"], "token": tok,
                                "ledger_qty": qty, "wallet_qty": have})
        self._orphans = orphans
        if orphans:
            self._reconcile_note = f"{len(orphans)} orphaned leg(s) detected"
            logger.error("RECONCILE: chain no longer backs %d open ledger "
                         "leg(s): %s", len(orphans),
                         ", ".join(o["symbol"] for o in orphans))
        elif unknown:
            self._reconcile_note = "balance read unavailable; reconcile deferred"
        else:
            self._reconcile_note = f"ok: {len(open_rows)} leg(s) backed by wallet"

    # -- one decision --------------------------------------------------------
    def _market_regime_dir(self) -> int:
        """Higher-timeframe market regime from the latest 4h BTC signal: +1 if it
        is a fresh BUY (long favourable), -1 if a fresh SELL, 0 if none or stale.
        Cached ~5 min. Read-only; never raises (a fault yields 0 = no bias)."""
        now = time.time()
        cached = getattr(self, "_regime_cache", None)
        if cached and now - cached[0] < 300:
            return cached[1]
        d = 0
        try:
            tf = os.getenv("BNBHACK_REGIME_TF", "4h")
            sym = os.getenv("BNBHACK_REGIME_SYMBOL", "BTCUSDT")
            sym = sym if sym.endswith(".P") else sym + ".P"
            con = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=5)
            try:
                row = con.execute(
                    "SELECT signal, timestamp FROM signals WHERE symbol=? AND "
                    "timeframe=? ORDER BY id DESC LIMIT 1", (sym, tf)).fetchone()
            finally:
                con.close()
            if row:
                # A 4h regime is a STANCE that holds until the next 4h signal
                # flips it, so it is valid far longer than an entry trigger. Use a
                # generous regime age (default 5 days); only a long signal outage
                # drops it to neutral.
                try:
                    age = now - float(row[1])
                except (TypeError, ValueError):
                    age = 0.0  # unparseable -> treat the latest as the stance
                max_age = float(os.getenv("BNBHACK_REGIME_MAX_AGE_H", "120")) * 3600
                if 0 <= age <= max_age:
                    side = str(row[0] or "").strip().lower()
                    d = 1 if side == "buy" else -1 if side == "sell" else 0
        except Exception:
            d = 0
        self._regime_cache = (now, d)
        return d

    async def decide(self, sig: Dict[str, Any], equity: float,
                     drawdown: float, force: bool = False) -> Decision:
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
        # conviction floor and the regime stand-aside are SELECTIVITY gates: a
        # forced daily-floor trade relaxes only these (never a risk gate) so the
        # wallet keeps >=1 trade/day on an otherwise-quiet day.
        if not force and fr.conviction < self.cfg.conviction_min:
            d.reasons.append(
                f"conviction {fr.conviction:.0f} < min {self.cfg.conviction_min:.0f}")
            return d

        # Regime filter: in a risk-off regime stand aside on NEW longs. Reads the
        # CMC regime source directly off the fusion result (its contrarian F&G
        # gauge votes SHORT in extreme greed). Exits of already-open legs are
        # handled by the position manager and are unaffected by this gate.
        if not force and self.cfg.regime_filter and fr.direction > 0:
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
            conviction=fr.conviction / 100.0,
            require_edge=not self.cfg.managed_mode,
            # Managed mode pins the stop to the configured fixed distance (the
            # validated 3%) so the sizer's notional and the committed stop agree.
            stop_distance=(_LIVE_MIN_STOP if self.cfg.managed_mode else None)))
        d.win_rate = sz.win_rate
        d.payoff = sz.payoff

        # Verifiable prediction envelope. The sizer populates stop_distance and
        # payoff even when it DECLINES the capital leg, so the directional
        # entry/target/stop forecast is always well-defined. The live floors keep
        # it sane and reproducible. This is the call the agent commits and reveals
        # on chain regardless of whether it then risks capital on it.
        sd = max(sz.stop_distance, _LIVE_MIN_STOP)
        # Committed target = the TP1 level. In managed mode this is a fixed NEAR
        # level (BNBHACK_TP1_TARGET_PCT, the validated +0.5% take-half point); TP1
        # closes 50% there, then the runner rides to the magnet. Otherwise it is
        # the payoff-scaled target with the live floor.
        if _TP1_TARGET_PCT > 0:
            rr = _TP1_TARGET_PCT
        else:
            rr = max(sz.payoff * sd, _LIVE_MIN_TP)
        if fr.direction > 0:
            d.stop = entry * (1.0 - sd)
            d.target = entry * (1.0 + rr)
        else:
            # Cap the reward fraction so a short target stays a positive price
            # (an unclamped payoff*sd > 1 would underflow the target to 0).
            rr = min(rr, 0.95)
            d.stop = entry * (1.0 + sd)
            d.target = entry * (1.0 - rr)

        # PREDICTION vs CAPITAL are now decoupled. Conviction (above) already
        # cleared, so this is a forecast the agent publishes. It only ADDITIONALLY
        # risks capital when the sizer approves a positive net-of-cost edge AND the
        # RiskGovernor is not halted. Otherwise it is committed and revealed on
        # chain as a PREDICT-only call: a verifiable, graded forecast with ZERO
        # capital, no spot/perp leg and no position. This keeps the verifiable
        # protocol record flowing on the high-conviction calls whose measured edge
        # does not clear the fee hurdle (the common case on this thin-edge data).
        if not sz.approved:
            d.action = "PREDICT"
            d.reasons.extend(sz.reasons[-2:] or ["sizer declined; prediction only"])
            return d

        d.leverage = sz.leverage
        d.notional = sz.notional
        d.margin = sz.margin
        # Directional capital bias: lean INTO the higher-timeframe market regime.
        # When the 4h BTC signal favours this trade's direction we deploy full
        # size; when it OPPOSES we still take the (verifiable) trade but with less
        # capital. Forced daily-floor trades are exempt (compliance, not edge).
        if not force:
            reg = self._market_regime_dir()
            if reg != 0 and reg != fr.direction:
                sc = max(0.0, min(1.0, float(
                    os.getenv("BNBHACK_REGIME_OPPOSED_SCALE", "0.5"))))
                d.notional *= sc
                d.margin *= sc
                d.reasons.append(
                    f"counter to 4h regime ({'long' if reg > 0 else 'short'}); "
                    f"capital x{sc:g}")
        if (force and self.cfg.daily_floor_usd > 0
                and d.notional > self.cfg.daily_floor_usd):
            # Shrink the forced trade to the daily floor so keeping the cadence
            # never spends meaningful budget; risk gates below still apply. The
            # clamp is on NOTIONAL (the USD the spot leg actually spends, see
            # _commit_and_act); margin scales with it so both stay consistent.
            scale = self.cfg.daily_floor_usd / d.notional
            d.notional = self.cfg.daily_floor_usd
            d.margin = d.margin * scale
            d.is_floor = True
            d.reasons.append(
                "daily floor (forced past selectivity to keep >=1 trade/day)")

        # RiskGovernor pre-trade gate (read; honours a deployed halt). Offloaded
        # so the RPC call cannot block the event loop. A halt blocks the CAPITAL
        # leg but not the forecast, so it downgrades to PREDICT (committed and
        # revealed, zero capital) rather than a silent SKIP.
        ok, dd_bps, gdetail = await asyncio.to_thread(self.writer.can_trade)
        if not ok:
            d.action = "PREDICT"
            d.reasons.append(f"{gdetail}; prediction only (no capital)")
            return d

        if self.cfg.long_only and fr.direction < 0:
            # Long-only: record the short as a verifiable on-chain forecast, never
            # a capital short (BSC spot cannot express one without a perp venue).
            d.action = "PREDICT"
            d.reasons.append("long-only: short recorded as forecast, no capital")
            return d
        d.action = "TRADE_LONG" if fr.direction > 0 else "TRADE_SHORT"
        d.reasons.append(
            f"{fr.label} conv {fr.conviction:.0f} agree {fr.agreement:.2f} "
            f"lev {sz.leverage:.2f}x")
        return d

    # -- commit + execute + reveal ------------------------------------------
    async def _commit_and_act(self, d: Decision, equity: float,
                              mode: str, cap_exempt: bool = False) -> None:
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
        # cannot be expressed on spot (no borrow), so the live short routes
        # through the gated USDT-M futures adapter (perp_exec, Binance-first)
        # when BNBHACK_EXECUTE_PERP=1 and venue keys are present; it is OFF by
        # default, so a live short is an honest no-go that records nothing until
        # enabled, while a PAPER short is simulated (signal_dir=-1, no swap) so
        # the two-sided book earns in down weeks too. 'open' starts a new ladder,
        # 'add' fills the next rung of an existing one; either way one rung =
        # total size / ladder_rungs of
        # exposure this tick (so the full position is built over a few confirming
        # cycles and the total notional matches a single open). A blocked trade
        # ('') still keeps the verifiable commit above; it just takes no exposure.
        if d.action in ("TRADE_LONG", "TRADE_SHORT") and mode in ("open", "add"):
            base = _base_of(d.symbol)
            tok = _BSC_SPOT.get(base)
            # Deep-pool-only mode (optional): when BNBHACK_SPOT_DEEP_BASES is set,
            # only those bases take a live spot leg; any other base gets the
            # verifiable on-chain prediction but no capital, so the agent never
            # routes real size into a thin BSC pool that would bleed to slippage.
            if tok is not None and _SPOT_DEEP_BASES and base.upper() not in _SPOT_DEEP_BASES:
                tok = None
            if tok is None:
                d.security = {"go": False, "detail": f"no BSC spot token for {base}"}
            else:
                rungs = max(1, self.pm.ladder_rungs)
                # Free collateral = equity minus the notional already committed to
                # open legs, so capital sitting in a position is never re-bet
                # (sizing the new leg against TOTAL equity double-counts it).
                free_usd = max(0.0, equity - self.pm.deployed_usd())
                # The unlevered spot leg spends its NOTIONAL: that is the USD
                # the sizer budgeted so notional * stop == rho * equity. The
                # old d.margin here was algebraically the WHOLE equity (sizing
                # defined leverage = notional / equity, so notional / leverage
                # == equity), which made the Kelly/drawdown budget a no-op and
                # spent the full free balance on every leg.
                full_usd = max(0.0, min(d.notional, free_usd,
                                        bsc_exec.MAX_SWAP_USD))
                # The daily-floor cap-exempt leg lets ONE extra minimal
                # position past the book cap (see _daily_floor_lastresort).
                max_pos = self.cfg.max_positions + (1 if cap_exempt else 0)
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
                        # Spot has no borrow leg, so a SHORT routes through the
                        # live perp venue: Binance USDT-M futures via the gated
                        # perp_exec adapter (see perp_exec). When perps are ENABLED
                        # (BNBHACK_EXECUTE_PERP
                        # plus venue keys) a live short is signed there and the leg
                        # is recorded with signal_dir<0 at the real fill so the
                        # close path can exit it on the same venue. When perps are
                        # DISABLED (the default) a LIVE short stays an honest no-go
                        # that records nothing, and a PAPER short is simulated
                        # (signal_dir<0, no swap) so the two-sided book is honest
                        # without signing anything.
                        if self.cfg.execute_trades and perp_exec.enabled():
                            po = await perp_exec.open_short(
                                d.symbol, rung_usd, equity=equity)
                            if po.go and po.executed:
                                entry_px = po.price or d.entry
                                if mode == "open":
                                    self.pm.record_open(
                                        symbol=d.symbol, base=base, token=tok,
                                        size_usd=rung_usd, entry=entry_px,
                                        target=d.target, stop=d.stop,
                                        signal_dir=d.direction,
                                        swap_result=None,
                                        max_positions=max_pos,
                                        rungs_total=rungs,
                                        size_target_usd=full_usd,
                                        is_floor=getattr(d, "is_floor", False))
                                else:
                                    self.pm.record_add(
                                        symbol=d.symbol, add_size_usd=rung_usd,
                                        fill_price=entry_px, swap_result=None)
                                d.security = {"go": True, "executed": True,
                                              "detail": po.detail,
                                              "usd": round(rung_usd, 2),
                                              "mode": mode, "rungs": rungs,
                                              "venue": "perp"}
                            else:
                                d.security = {"go": po.go, "executed": False,
                                              "detail": po.detail,
                                              "usd": round(rung_usd, 2),
                                              "mode": mode, "rungs": rungs,
                                              "venue": "perp"}
                            return
                        if self.cfg.execute_trades:
                            d.security = {"go": False, "executed": False,
                                          "detail": "live short requires a perp "
                                                    "venue (BNBHACK_EXECUTE_PERP); "
                                                    "paper-simulated only",
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
                                    max_positions=max_pos,
                                    rungs_total=rungs, size_target_usd=full_usd,
                                    is_floor=getattr(d, "is_floor", False))
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
                        # Independent per-unit mark (Binance) so the swap can
                        # refuse a dead/thin-pool quote whose implied price is far
                        # off the real market (the LTC-class dead-pool backstop).
                        _mk = await mark_price(d.symbol, fallback=0.0)
                        sw = await bsc_exec.swap(
                            rung_usd, "USDT", tok,
                            slippage_pct=self.cfg.slippage_pct,
                            execute=self.cfg.execute_trades,
                            equity=equity,
                            equity_floor=equity * (1.0 - self.cfg.jury_cap),
                            approx_usd=rung_usd,
                            mark_price=(_mk if _mk and _mk > 0 else None))
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
                        # Live fill rebase: an executed swap reports BOTH the
                        # source amount actually spent (sw.input_amount, after the
                        # live-balance clamp inside bsc_exec.swap) AND the token
                        # amount actually received, so the REAL fill price is
                        # spent / qty. The requested rung_usd is NOT the spend
                        # when a buy is clamped to a thin stable balance: using it
                        # back-computes a phantom entry (e.g. an $8 request that
                        # only filled $0.19 of USDT would record entry = 8/qty,
                        # tens of x the true price). So both the recorded size and
                        # the fill price are taken from the actual spend; the
                        # stop/target are rebuilt from the decision's ORIGINAL
                        # price fractions (the ratios stop/entry, target/entry are
                        # preserved). Paper legs keep the signal price + rung_usd.
                        spent_usd = rung_usd
                        if sw.executed and d.entry > 0 and rung_usd > 0:
                            qty_fill = _amount_from_result(sw.result or {})
                            spent_usd, fill = _live_fill(
                                rung_usd, sw.input_amount, qty_fill)
                            if spent_usd < rung_usd * 0.95:
                                logger.warning(
                                    "spot swap under-filled for %s: spent $%.4g "
                                    "of $%.2f requested (low USDT balance); "
                                    "recording the real spend",
                                    d.symbol, spent_usd, rung_usd)
                                d.reasons.append(
                                    f"swap under filled to ${spent_usd:.4g} "
                                    f"(low USDT balance)")
                            if fill is not None:
                                d.target = fill * (d.target / d.entry)
                                d.stop = fill * (d.stop / d.entry)
                                d.entry = fill
                                d.reasons.append("entry rebased to live fill")
                        if record_it and mode == "open":
                            self.pm.record_open(
                                symbol=d.symbol, base=base, token=tok,
                                size_usd=spent_usd, entry=d.entry,
                                target=d.target, stop=d.stop,
                                signal_dir=d.direction,
                                swap_result=sw.result,
                                # Record the executed swap's tx hash so the
                                # cockpit can link the real spot leg on BscScan
                                # (empty for a paper leg).
                                open_tx=(_tx_hash_from_result(sw.result)
                                         if sw.executed else ""),
                                max_positions=max_pos,
                                rungs_total=rungs, size_target_usd=full_usd,
                                is_floor=getattr(d, "is_floor", False))
                        elif record_it and mode == "add":
                            self.pm.record_add(
                                symbol=d.symbol, add_size_usd=spent_usd,
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
        deadline = time.monotonic() + max(1.0, self.cfg.reveal_cycle_budget_sec)
        for r in due:
            # A chain reveal blocks on a receipt wait; once the per-cycle budget
            # is spent, leave the rest due and let the next cycle drain them so
            # the decision loop is never wedged behind a reveal backlog.
            if self.cfg.execute_chain and time.monotonic() >= deadline:
                logger.info("reveal pass hit cycle budget; deferring %d reveal(s)",
                            len(due) - len(revealed))
                break
            if not r["agent_id"]:
                self.store.mark_revealed(r["local_id"], None, "",
                                         status="revealed-paper")
                continue
            try:
                # Only a commitment that actually landed on chain can be revealed
                # on chain; a dry (paper) commit reveals only as a paper record.
                want_chain = (self.cfg.execute_chain
                              and r["commit_id"] is not None)
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
                    # Count the attempt ONLY when the raw tx actually broadcast.
                    # A pre-broadcast fault (RPC down, build error) never reached
                    # the network, so it must not consume the bounded attempt
                    # budget and prematurely waive a reveal that could still land.
                    attempts = (self.store.bump_attempt(r["local_id"])
                                if out.broadcast else 0)
                    # Stop re-sending once the bounded attempt budget is spent so a
                    # permanently reverting reveal cannot keep burning gas; settle
                    # it as a paper reveal. A cap of <= 0 means unlimited (retry
                    # until the reveal deadline only).
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

    async def _verify_due_outcomes(self) -> None:
        """Grade every revealed prediction whose judged window has closed,
        recording TARGET_HIT / STOP_HIT / EXPIRED on chain (onlyOracle), so the
        registry's correct/wrong tally reflects the real track record instead of
        sitting at 0/0 forever. The verdict is DETERMINISTIC from a fresh mark
        and the committed (and already revealed) entry/target/stop, so the graded
        outcome is exactly what the disclosed seal predicted. Signs only in live
        chain mode; one faulty row is logged and swallowed, never raised."""
        if not self.cfg.execute_chain:
            return  # dry mode never signs
        try:
            due = self.store.due_verifications(_now())
        except Exception as exc:
            logger.warning("due_verifications failed: %s", exc)
            return
        if not due:
            return
        # Reuse the reveal pass's per-cycle wall-clock budget so a backlog of
        # grading calls (each blocks on a receipt wait) can never wedge the loop.
        deadline = time.monotonic() + max(1.0, self.cfg.reveal_cycle_budget_sec)
        for r in due:
            if time.monotonic() >= deadline:
                logger.info("verify pass hit cycle budget; deferring %d grade(s)",
                            len(due))
                break
            try:
                pid = int(r["prediction_id"])
                symbol = str(r["symbol"] or "")
                base = symbol if symbol.upper().endswith("USDT") else f"{symbol}USDT"
                mark = await mark_price(base, fallback=0.0)
                if not (mark and math.isfinite(mark) and mark > 0):
                    continue  # no fresh mark this cycle; grade on a later one
                # Compare in the contract's SCALED integer space: the stored
                # entry/target/stop are already to_scaled_price(...) integers and
                # the on-chain exitPrice arg is the same uint64 scale, so scale the
                # fresh mark identically and compare/record without unscaling.
                mark_s = chain_writer.to_scaled_price(mark)
                target_s = int(r["target"])
                stop_s = int(r["stop"])
                d = 1 if int(r["signal"]) == SIGNAL_BUY else -1
                if d > 0:
                    if mark_s >= target_s:
                        outcome = chain_writer.OUTCOME_TARGET
                    elif mark_s <= stop_s:
                        outcome = chain_writer.OUTCOME_STOP
                    else:
                        outcome = chain_writer.OUTCOME_EXPIRED
                else:
                    if mark_s <= target_s:
                        outcome = chain_writer.OUTCOME_TARGET
                    elif mark_s >= stop_s:
                        outcome = chain_writer.OUTCOME_STOP
                    else:
                        outcome = chain_writer.OUTCOME_EXPIRED
                out = await asyncio.to_thread(
                    self.writer.verify_outcome, pid, outcome, mark_s,
                    execute=True)
                if out.ok and out.executed:
                    self.store.mark_verified(pid)
                    logger.info("graded prediction %d %s outcome=%d exit=%d tx=%s",
                                pid, symbol, outcome, mark_s,
                                chain_writer.ChainWriter.tx_url(out.tx_hash))
            except Exception as exc:
                logger.warning("verify outcome failed (%s): %s",
                               r["symbol"], exc)

    async def _broadcast_cycle(self, decisions: List["Decision"],
                               closes: List[Any]) -> None:
        """Announce this cycle's taken legs and closes to the transparency feed.
        Best-effort: a formatting or send fault is logged and swallowed so the
        loop is never affected. Only legs that actually took exposure (a passed
        gate with an open/add rung) are announced, never blocked commit-only
        decisions."""
        try:
            for d in decisions:
                sec = d.security if isinstance(d.security, dict) else {}
                if not (sec.get("go") and sec.get("mode") in ("open", "add")):
                    continue
                msg = notify.format_open(
                    sec, d.symbol, d.direction, d.entry, d.target, d.stop,
                    is_floor=getattr(d, "is_floor", False))
                if msg:
                    await notify.broadcast(msg)
            for c in closes:
                msg = notify.format_close({
                    "symbol": c.symbol, "reason": c.reason,
                    "exit_price": c.exit_price, "pnl_usd": c.pnl_usd,
                    "pnl_pct": c.pnl_pct, "executed": c.executed,
                    "partial": c.partial})
                if msg:
                    await notify.broadcast(msg)
        except Exception as exc:
            logger.debug("broadcast cycle failed: %s", exc)

    async def _consume_x402(self) -> None:
        """Buy the configured verified-record feed over x402 and cache the result
        for the published state. Off the event loop, best-effort: a failed buy
        keeps the previous good result and never disturbs the cycle."""
        try:
            res = await asyncio.to_thread(
                x402_feed.consume_feed, self.cfg.x402_product, self._x402_cfg,
                feed_params={"group_by": "symbol", "horizon": "auto"},
                db_path=SIGNAL_DB)
            res["consumed_cycle"] = self.cycle
            res["consumed_ts"] = _now()
            self._x402_last = res
            if res.get("ok"):
                logger.info("x402 consume ok: product=%s payer=%s deferred=%s",
                            res.get("product_id"), res.get("payer"),
                            res.get("settlement_deferred"))
            else:
                logger.warning("x402 consume not verified: %s",
                               res.get("error") or "see result")
        except Exception as exc:
            logger.debug("x402 consume failed: %s", exc)

    # -- one cycle -----------------------------------------------------------
    async def run_cycle(self) -> Dict[str, Any]:
        self.cycle += 1
        now = _now()
        self._roll_daily(now)

        reveals = await self._process_reveals()

        # Grade every revealed prediction whose judged window has closed, so the
        # on-chain correct/wrong tally reflects the real track record (signs only
        # in live chain mode; best-effort, never wedges the cycle).
        await self._verify_due_outcomes()

        # Keep the proof store bounded over a multi-day live window. Runs off the
        # event loop (a delete + WAL checkpoint can briefly block) and only every
        # 60th cycle; unrevealed commitments are never pruned.
        if self.cfg.pending_retention_days > 0 and self.cycle % 60 == 1:
            try:
                cutoff = now - int(self.cfg.pending_retention_days * 86400)
                pruned = await asyncio.to_thread(self.store.prune, cutoff)
                if pruned:
                    logger.info("pending store pruned %d terminal rows", pruned)
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
            unrealized=positions.get("unrealized_usd", 0.0),
            open_positions=positions.get("open", []))
        drawdown = self._drawdown(equity)

        decisions: List[Decision] = []
        for sig in sigs:
            try:
                d = await self.decide(sig, equity, drawdown)
            except Exception as exc:
                logger.warning("decide failed (%s): %s", sig.get("pair"), exc)
                continue
            # A PREDICT-only call commits a verifiable forecast but risks no
            # capital. Dedup it per distinct signal event so a still-fresh alert
            # is not re-committed (gas) every cycle; the capital TRADE path is
            # unaffected and keeps its own position/ladder dedup.
            if d.action == "PREDICT":
                pkey = (d.symbol, d.direction, sig.get("ts"))
                if pkey in self._predicted_keys:
                    decisions.append(d)
                    continue
                if len(self._predicted_keys) > 4000:
                    self._predicted_keys.clear()
                self._predicted_keys.add(pkey)
            if d.action != "SKIP":
                # 'open' -> new ladder, 'add' -> next rung, '' -> blocked (cap
                # full / already scaling out). Both a long and a short take a
                # leg (the short is paper-only; see _commit_and_act). A PREDICT
                # passes mode='' so _commit_and_act records the commit + reveal
                # but never opens a trade leg.
                mode = (self.pm.entry_mode(d.symbol, self.cfg.max_positions)
                        if d.action in ("TRADE_LONG", "TRADE_SHORT") else "")
                try:
                    await self._commit_and_act(d, equity, mode)
                except Exception as exc:
                    logger.warning("commit/act failed (%s): %s", d.symbol, exc)
            decisions.append(d)

        # Count real swaps this cycle (executed opens/adds + executed closes) so
        # the daily-floor cadence guard knows whether the wallet already traded
        # today. Paper mode never sets executed=True, so the count stays 0 and
        # the floor never fires (it is gated on execute_trades anyway).
        executed_now = sum(1 for c in closes if getattr(c, "executed", False))
        executed_now += sum(
            1 for d in decisions
            if isinstance(d.security, dict) and d.security.get("executed"))
        self._record_executed_trades(executed_now)

        # Daily-floor cadence: if live and still short of the daily minimum late
        # in the UTC day, force ONE minimal qualifying long. This relaxes only
        # the selectivity gates (conviction floor + regime stand-aside); every
        # risk gate (sizer drawdown budget, RiskGovernor, security gate) still
        # applies, so it never trades through a halt. Records nothing if no long
        # is eligible this tick (it retries next cycle inside the window).
        floor_decision: Optional[Decision] = None
        if self._floor_due(now):
            floor_decision = await self._daily_floor_trade(equity, drawdown, sigs)
            decisions.append(floor_decision)
            floor_executed = (isinstance(floor_decision.security, dict)
                              and floor_decision.security.get("executed"))
            if floor_executed:
                self._record_executed_trades(1)
            # True last resort: very late in the UTC day the signal-driven
            # floor may STILL have nothing executable (all-sell day, cold
            # signal book, every bucket failing the edge gate). Rather than
            # retry into a guaranteed daily-minimum DQ, place ONE minimal
            # routable swap that bypasses only the selectivity gates; the
            # security gate and the RiskGovernor halt check still apply.
            if not floor_executed and self._floor_lastresort_due(now):
                lr = await self._daily_floor_lastresort(equity)
                if lr is not None:
                    decisions.append(lr)
                    if (isinstance(lr.security, dict)
                            and lr.security.get("executed")):
                        self._record_executed_trades(1)

        # Transparency feed: announce every trade leg the agent actually takes
        # (and every close) to the optional Telegram broadcast channel, so the
        # judged window is observable in real time. Best-effort and gated on a
        # configured bot token; a no-op (and never an exception) otherwise. It
        # signs nothing and carries no secret · only public trade facts.
        if notify.enabled():
            await self._broadcast_cycle(decisions, closes)

        # Native x402 consumption: on a low cadence the agent buys a premium
        # verified-record feed over x402 (full 402 -> signed EIP-3009 auth ->
        # verify -> 200), proving it acts as an agentic-commerce consumer. Runs
        # off the event loop (the feed reads signal.db) and is best-effort: a
        # failed purchase only leaves the last good result in place.
        if (self.cfg.x402_consume
                and self.cycle % max(1, self.cfg.x402_consume_every) == 1):
            await self._consume_x402()

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
            # A new low in the quantised vault units, OR any raw equity decrease
            # (even one that rounds to the same units), forces an immediate write
            # so the drawdown killswitch never lags a real drawdown.
            new_low = (self._last_equity_recorded is None
                       or equity_units < self._last_equity_recorded
                       or (self._last_equity_raw is not None
                           and equity < self._last_equity_raw))
            # Debounce a SHARP drop (>8% below the last recorded units) before it
            # reaches the killswitch: a real drawdown persists for >=2 reads and
            # then writes; a transient partial-read artifact recovers next cycle
            # and is discarded, so it can never latch the halt. Normal/gradual
            # lows (<=8%) write immediately, keeping the killswitch responsive.
            sharp = (self._last_equity_recorded is not None
                     and self._last_equity_recorded > 0
                     and equity_units
                     < self._last_equity_recorded * 0.92)
            hold_suspect = False
            if sharp:
                self._sharp_drop_streak += 1
                if self._sharp_drop_streak < 2:
                    hold_suspect = True
                    logger.warning(
                        "suspect sharp equity drop %s -> %s units; holding "
                        "last-good (debounce %d/2)", self._last_equity_recorded,
                        equity_units, self._sharp_drop_streak)
            else:
                self._sharp_drop_streak = 0
            # A held suspect reading is written by NEITHER the new-low nor the
            # interval path, so a one-cycle artifact can never reach the ledger.
            do_record = ((new_low or elapsed >= self.cfg.chain_equity_interval)
                         and not hold_suspect)
        else:
            do_record = True
        if do_record:
            gov_rec = await asyncio.to_thread(
                self.writer.record_equity, equity_units,
                execute=self.cfg.execute_chain)
            self._last_equity_record_ts = now
            self._last_equity_recorded = equity_units
            self._last_equity_raw = equity
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

    # Cap the rolling equity curve so the published snapshot stays small. At a
    # 60s cycle this holds roughly a full day of points; older points roll off.
    EQUITY_HIST_MAX = 1440

    def _load_equity_hist(self) -> List[List[float]]:
        """Seed the equity curve from the last published snapshot so a restart
        continues the same curve. Returns [] on any read/parse failure."""
        try:
            with open(STATE_PATH, "r") as f:
                prev = json.load(f)
            hist = prev.get("equity_history")
            if isinstance(hist, list):
                out: List[List[float]] = []
                for p in hist[-self.EQUITY_HIST_MAX:]:
                    if isinstance(p, (list, tuple)) and len(p) == 2:
                        out.append([float(p[0]), float(p[1])])
                return out
        except Exception:
            pass
        return []

    def _build_state(self, now: int, equity: float, drawdown: float,
                     decisions: List[Decision], reveals: List[Dict[str, Any]],
                     governor: Dict[str, Any], arena: Dict[str, Any],
                     vault: Dict[str, Any], positions: Dict[str, Any],
                     cycle_closes: List[Dict[str, Any]]) -> Dict[str, Any]:
        proofs: List[Dict[str, Any]] = []
        try:
            # Surface only proofs the jury would expect: an eligible-base symbol
            # (drops legacy BTC/BNB paper rows that predate the eligibility gate)
            # with a real confidence (drops a conf=0 legacy artifact). Pull a
            # wider window then take the freshest 12 that pass.
            for r in self.store.recent(40):
                if _base_of(r["symbol"]) not in _ELIGIBLE_BASES:
                    continue
                if int(r["confidence"] or 0) <= 0:
                    continue
                proofs.append({
                    "symbol": r["symbol"], "signal": int(r["signal"]),
                    "confidence": int(r["confidence"]),
                    "status": r["status"], "committed_ts": int(r["committed_ts"]),
                    "commit_tx": chain_writer.ChainWriter.tx_url(r["commit_tx"] or ""),
                    "reveal_tx": chain_writer.ChainWriter.tx_url(r["reveal_tx"] or ""),
                    "prediction_id": r["prediction_id"]})
                if len(proofs) >= 12:
                    break
        except Exception:
            pass
        # Append this cycle to the rolling equity curve (capped ring).
        self._equity_hist.append([now, round(equity, 2)])
        if len(self._equity_hist) > self.EQUITY_HIST_MAX:
            self._equity_hist = self._equity_hist[-self.EQUITY_HIST_MAX:]
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
            "equity_history": self._equity_hist,
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
                # Surface the execution posture so the cockpit can state plainly
                # whether spot swaps and chain proofs are signing live.
                "execute_trades": self.cfg.execute_trades,
                "execute_chain": self.cfg.execute_chain,
            },
            "daily": {
                "day": self._trade_day,
                "trades_today": self._trades_today,
                "min_required": self.cfg.daily_min_trades,
                "floor_enabled": bool(self.cfg.execute_trades and self.cfg.daily_floor),
                "floor_hour_utc": self.cfg.daily_floor_hour_utc,
                "note": self._floor_note,
            },
            "x402_consumed": self._x402_last,
            "perp": perp_exec.status(),
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
                "security": d.security, "proof": d.proof, "is_floor": d.is_floor,
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

    async def _ensure_vault_registered(self) -> None:
        """Until the RiskGovernor vault is registered, canTrade returns (false,0)
        and recordEquity reverts, so the agent would commit but never be cleared
        to trade. On startup (chain mode only) register the vault if it is missing,
        and fail loudly if it stays unregistered so the operator notices."""
        if not self.cfg.execute_chain:
            return
        try:
            vault = await asyncio.to_thread(self.writer.vault)
        except Exception as exc:
            logger.warning("vault read failed at startup: %s", exc)
            return
        if not vault:
            # Governor not configured (paper-shaped chain); nothing to register.
            return
        if vault.get("registered"):
            return
        logger.warning("RiskGovernor vault not registered; registering with "
                       "baseline equity %d", self.cfg.chain_equity_baseline)
        try:
            out = await asyncio.to_thread(
                self.writer.register_vault, self.cfg.chain_equity_baseline,
                None, execute=True)
        except Exception as exc:
            logger.error("vault registration raised: %s", exc)
            return
        if not (out.executed and out.ok):
            logger.error("vault registration did not land (%s); the agent will "
                         "commit but cannot trade until the vault is registered",
                         out.detail)

    async def run_forever(self) -> None:
        logger.info("agent loop start mode=%s watchlist=%s tf=%s interval=%ss",
                    self.cfg.mode(), self.cfg.watchlist, self.cfg.timeframe,
                    self.cfg.interval)
        # Routability audit: loudly flag any configured base with no spot route
        # before the first decision (advisory; never crashes the loop).
        try:
            self._audit_routability()
        except Exception as exc:
            logger.warning("startup routability audit failed: %s", exc)
        # Reconcile the ledger against the live wallet once at startup so a leg
        # closed while the agent was down is surfaced before the first decision.
        try:
            await self._reconcile_positions()
            logger.info("startup reconcile: %s", self._reconcile_note)
        except Exception as exc:
            logger.warning("startup reconcile failed: %s", exc)
        # Register the RiskGovernor vault before the first decision so the
        # pre-trade gate can actually clear (chain mode only; idempotent).
        await self._ensure_vault_registered()
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
