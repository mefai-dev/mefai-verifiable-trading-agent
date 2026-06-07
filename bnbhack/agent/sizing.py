"""
MEFAI BNB HACK · Drawdown-budget fractional-Kelly position sizing

The BNB HACK Track 1 judge scores returns, drawdown, risk-adjusted performance
(Sharpe) and rule adherence on a held-out live window. This module turns a trade
decision into a position size that, by construction, cannot breach the drawdown
budget, while sizing each bet by its EMPIRICAL edge from 181k labelled MEFAI
signal outcomes (signal_performance) rather than a guessed win-rate.

Model (documented so the cockpit can explain every number):
  s   = stop distance as a fraction of entry price (e.g. 0.02 = a 2 percent stop)
  p   = empirical win probability for this (symbol, timeframe), shrunk toward a
        global prior so thin buckets do not produce extreme Kelly values
  b   = empirical payoff ratio = avg_win / avg_loss (both as positive percents)
  f_k = win/loss Kelly fraction = p - (1 - p) / b          (>= 0)
  rho = per-trade risk budget = fraction of equity lost IF the stop is hit
        rho = min( quarter_kelly * f_k , k * R ) * regime_gate * conviction
  R   = internal_cap - current_drawdown ; internal_cap = 0.7 * jury_cap
  k   = drawdown-budget coefficient (~0.15)

  notional   = (rho * equity) / s     so that notional * s == rho * equity
  leverage   = notional / equity      (capped at the venue maximum; capping
                                       leverage only lowers risk, never raises it)
  margin     = notional / leverage

As R -> 0 the budget rho -> 0 and sizes shrink to zero, so the agent physically
cannot trade itself past the drawdown cap. This is the on-chain RiskGovernor's
off-chain twin.

READ-ONLY: this module only reads signal_performance. It never trades, signs or
writes anything.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("mefai.bnbhack.sizing")

SIGNAL_DB = os.getenv("MEFAI_SIGNAL_DB", "data/signal.db")

# --- model constants --------------------------------------------------------
QUARTER_KELLY = 0.25          # we never bet more than a quarter of full Kelly
DD_BUDGET_K = 0.15           # per-trade fraction of remaining drawdown room (R)
JURY_CAP_DEFAULT = 0.20      # assumed jury max-drawdown DQ threshold (20 percent)
INTERNAL_CAP_RATIO = 0.70    # we run to 70 percent of the jury cap, never to it
SHRINK_PSEUDO = 25.0         # Bayesian pseudo-count for win-rate shrinkage
PAYOFF_CAP = 20.0            # clamp on b=avg_win/avg_loss so thin buckets cannot
                             # produce a meaningless near-1 Kelly
MIN_STOP = 0.002             # floor on stop distance (0.2 percent) to bound lev
MAX_STOP = 0.50              # ceiling on stop distance sanity
DEFAULT_VENUE_MAX_LEV = 10.0 # default leverage cap if the venue gives none
STATS_TTL = 1800             # seconds to cache per-bucket empirical stats
STATS_CACHE_MAX = 512        # max distinct (symbol,tf,horizon) stat buckets

# --- net-of-cost edge gate --------------------------------------------------
# A positive win/loss Kelly is NOT enough: a bucket can win >50 percent and
# still LOSE money once the PancakeSwap round-trip is paid. The gate below only
# sizes a bet when the EMPIRICAL per-trade expectancy clears that round-trip
# cost with a statistical margin, so the agent never deploys into a bucket whose
# edge is an artefact of thin data.
# Cost basis: majors (BTCB/ETH/BNB vs USDT) route through PancakeSwap V3 0.05
# percent fee pools, so the round-trip fee is ~0.10 percent (2 x 0.05); adding a
# realistic deep-pool slippage and BSC gas buffer brings the modelled round-trip
# to ~0.20 percent. The out-of-sample walk-forward confirms that at this cost
# only the 24h holding horizon is net-profitable (1h and 4h lose to cost), which
# is why the live agent now prioritises the 24h horizon.
ROUNDTRIP_COST_PCT = float(os.getenv("BNBHACK_ROUNDTRIP_COST_PCT", "0.2"))
MIN_EDGE_SAMPLES = int(os.getenv("BNBHACK_MIN_EDGE_SAMPLES", "30"))
EDGE_STDERR_MULT = float(os.getenv("BNBHACK_EDGE_STDERR_MULT", "1.0"))


def _finite(x: float, default: float = 0.0) -> float:
    """Coerce a non-finite external float (NaN/inf) to a safe default."""
    x = float(x)
    return default if not math.isfinite(x) else x

# Valid horizons map to the labelled columns in signal_performance.
_HORIZON_COLS = {
    "1h": ("pnl_1h", "result_1h"),
    "4h": ("pnl_4h", "result_4h"),
    "24h": ("pnl_24h", "result_24h"),
}


def _now() -> float:
    return time.time()


def _feed_symbol(pair: str) -> str:
    s = pair.upper().strip()
    return s if s.endswith(".P") else f"{s}.P"


@contextmanager
def _ro_db():
    db = sqlite3.connect(f"file:{SIGNAL_DB}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Empirical edge from signal_performance
# ---------------------------------------------------------------------------
@dataclass
class EmpiricalStats:
    symbol: str
    timeframe: str
    horizon: str
    n: int                # completed samples in this bucket
    wins: int
    win_rate: float       # shrunk p
    raw_win_rate: float   # unshrunk, for display
    avg_win: float        # mean positive pnl percent (>0)
    avg_loss: float       # mean absolute negative pnl percent (>0)
    payoff: float         # b = avg_win / avg_loss
    avg_max_drawdown: float  # mean adverse excursion percent (>0), for stop hint
    expectancy: float     # mean NET pnl percent per trade (signed), pre-fee
    expectancy_stderr: float  # standard error of that mean (percent)
    shrunk: bool


@dataclass
class _GlobalPrior:
    win_rate: float
    avg_win: float
    avg_loss: float
    avg_max_drawdown: float
    expectancy: float
    n: int


_prior_cache: Dict[str, _GlobalPrior] = {}
_prior_ts: Dict[str, float] = {}
_stats_cache: Dict[str, EmpiricalStats] = {}
_stats_ts: Dict[str, float] = {}


def _global_prior(horizon: str) -> _GlobalPrior:
    if horizon not in _HORIZON_COLS:
        raise ValueError(f"invalid horizon: {horizon}")
    if horizon in _prior_cache and _now() - _prior_ts.get(horizon, 0) < STATS_TTL:
        return _prior_cache[horizon]
    pnl_col, res_col = _HORIZON_COLS[horizon]
    with _ro_db() as db:
        row = db.execute(
            f"""SELECT
                  COUNT(*) AS n,
                  SUM(CASE WHEN {res_col}='win' THEN 1 ELSE 0 END) AS wins,
                  AVG(CASE WHEN {pnl_col}>0 THEN {pnl_col} END) AS aw,
                  AVG(CASE WHEN {pnl_col}<0 THEN -{pnl_col} END) AS al,
                  AVG(ABS(max_drawdown_pct)) AS adv,
                  AVG({pnl_col}) AS ex
                FROM signal_performance
                WHERE status='completed' AND {res_col} IN ('win','loss')
                  AND {pnl_col} IS NOT NULL""",
        ).fetchone()
    n = int(row["n"] or 0)
    wins = int(row["wins"] or 0)
    wr = (wins / n) if n else 0.5
    aw = float(row["aw"] or 1.0)
    al = float(row["al"] or 1.0)
    adv = float(row["adv"] or 2.0)
    ex = float(row["ex"] or 0.0)
    prior = _GlobalPrior(win_rate=wr, avg_win=max(aw, 1e-6),
                         avg_loss=max(al, 1e-6), avg_max_drawdown=max(adv, 1e-6),
                         expectancy=ex, n=n)
    _prior_cache[horizon] = prior
    _prior_ts[horizon] = _now()
    return prior


def compute_stats(symbol: str, timeframe: str, horizon: str = "24h") -> EmpiricalStats:
    """Empirical win-rate / payoff for one (symbol, timeframe), shrunk toward the
    global prior so thin buckets cannot produce extreme Kelly values."""
    if horizon not in _HORIZON_COLS:
        raise ValueError(f"invalid horizon: {horizon}")
    sym = _feed_symbol(symbol)
    tf = str(timeframe)
    ckey = f"{sym}|{tf}|{horizon}"
    if ckey in _stats_cache and _now() - _stats_ts.get(ckey, 0) < STATS_TTL:
        return _stats_cache[ckey]

    prior = _global_prior(horizon)
    pnl_col, res_col = _HORIZON_COLS[horizon]
    with _ro_db() as db:
        row = db.execute(
            f"""SELECT
                  COUNT(*) AS n,
                  SUM(CASE WHEN {res_col}='win' THEN 1 ELSE 0 END) AS wins,
                  AVG(CASE WHEN {pnl_col}>0 THEN {pnl_col} END) AS aw,
                  AVG(CASE WHEN {pnl_col}<0 THEN -{pnl_col} END) AS al,
                  AVG(ABS(max_drawdown_pct)) AS adv,
                  AVG({pnl_col}) AS ex,
                  AVG({pnl_col}*{pnl_col}) AS ex2
                FROM signal_performance
                WHERE symbol=? AND timeframe=? AND status='completed'
                  AND {res_col} IN ('win','loss') AND {pnl_col} IS NOT NULL""",
            (sym, tf),
        ).fetchone()

    n = int(row["n"] or 0)
    wins = int(row["wins"] or 0)
    raw_wr = (wins / n) if n else prior.win_rate
    # Beta-style shrinkage toward the global prior.
    shrunk_wr = (wins + SHRINK_PSEUDO * prior.win_rate) / (n + SHRINK_PSEUDO)
    aw = float(row["aw"]) if row["aw"] is not None else prior.avg_win
    al = float(row["al"]) if row["al"] is not None else prior.avg_loss
    adv = float(row["adv"]) if row["adv"] is not None else prior.avg_max_drawdown
    ex = float(row["ex"]) if row["ex"] is not None else prior.expectancy
    ex2 = float(row["ex2"]) if row["ex2"] is not None else None
    # Shrink magnitudes too (sample-weighted).
    w = n / (n + SHRINK_PSEUDO)
    aw = w * aw + (1 - w) * prior.avg_win
    al = w * al + (1 - w) * prior.avg_loss
    adv = w * adv + (1 - w) * prior.avg_max_drawdown
    # Shrink the per-trade expectancy toward the global prior too, so a thin
    # bucket cannot show a large edge off a handful of lucky samples.
    expectancy = w * ex + (1 - w) * prior.expectancy
    # Standard error of the mean net pnl: sqrt(var / n). var = E[x^2]-E[x]^2 on
    # the raw bucket samples (un-shrunk), floored at 0 against float noise. With
    # no samples the error is large enough to fail the edge gate on its own.
    if n > 1 and ex2 is not None:
        var = max(0.0, ex2 - ex * ex)
        stderr = math.sqrt(var / n)
    else:
        # Effectively-infinite uncertainty, but a large FINITE value so the
        # result stays JSON-serialisable (the /sizing endpoint asdict()s it);
        # it fails the edge gate exactly as an infinite error would.
        stderr = 1.0e6
    aw = max(aw, 1e-6)
    al = max(al, 1e-6)

    payoff = min(aw / al, PAYOFF_CAP)
    stats = EmpiricalStats(
        symbol=sym, timeframe=tf, horizon=horizon, n=n, wins=wins,
        win_rate=min(max(shrunk_wr, 0.0), 1.0), raw_win_rate=min(max(raw_wr, 0.0), 1.0),
        avg_win=aw, avg_loss=al, payoff=payoff, avg_max_drawdown=max(adv, 1e-6),
        expectancy=expectancy, expectancy_stderr=stderr,
        shrunk=n < (3 * SHRINK_PSEUDO),
    )
    if len(_stats_cache) >= STATS_CACHE_MAX and ckey not in _stats_cache:
        # Drop the oldest cached bucket (bounded against symbol/timeframe flooding).
        oldest = min(_stats_ts, key=_stats_ts.get)
        _stats_cache.pop(oldest, None)
        _stats_ts.pop(oldest, None)
    _stats_cache[ckey] = stats
    _stats_ts[ckey] = _now()
    return stats


def kelly_fraction(p: float, b: float) -> float:
    """Win/loss Kelly: f* = p - (1-p)/b. Clamped to [0, 1]."""
    p = min(max(p, 0.0), 1.0)
    if b <= 0:
        return 0.0
    f = p - (1.0 - p) / b
    return min(max(f, 0.0), 1.0)


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
@dataclass
class SizingInput:
    """Everything the sizer needs for one trade decision. Fields beyond symbol/
    timeframe/equity have safe defaults; all are clamped at the boundary."""
    symbol: str
    timeframe: str
    equity: float                 # current account equity (quote ccy)
    current_drawdown: float       # current peak-to-trough drawdown as fraction (>=0)
    stop_distance: Optional[float] = None  # fraction of price; None -> empirical
    horizon: str = "24h"
    jury_cap: float = JURY_CAP_DEFAULT     # jury DQ drawdown threshold (fraction)
    regime_gate: float = 1.0      # [0,1] multiplier from regime (0 = stand aside)
    venue_max_leverage: float = DEFAULT_VENUE_MAX_LEV
    conviction: float = 1.0       # [0,1] from the Omni-Fusion core (optional)


@dataclass
class SizingResult:
    """The sized position plus every intermediate number, so the cockpit can
    explain exactly why the agent chose this leverage and size."""
    approved: bool
    symbol: str
    timeframe: str
    equity: float
    internal_cap: float
    drawdown_room_R: float
    win_rate: float
    payoff: float
    full_kelly: float
    expectancy: float             # empirical net pnl percent per trade (pre-fee)
    expectancy_stderr: float      # standard error of that expectancy (percent)
    net_edge: float               # expectancy minus the round-trip cost (percent)
    risk_budget_rho: float        # fraction of equity at risk if stop hits
    stop_distance: float
    notional: float
    leverage: float
    margin: float
    worst_case_loss: float        # absolute quote ccy
    reasons: List[str] = field(default_factory=list)


def size_position(inp: SizingInput) -> SizingResult:
    """Turn a trade decision into a drawdown-budget fractional-Kelly position.
    Guarantees worst_case_loss <= DD_BUDGET_K * R * equity in every branch, so
    the agent cannot size itself past the drawdown cap."""
    reasons: List[str] = []

    # Defensive bounds on inputs (system boundary). Non-finite floats (NaN/inf)
    # are coerced to a safe default BEFORE clamping (NaN defeats min/max clamps).
    equity = max(0.0, _finite(inp.equity, 0.0))
    cur_dd = min(max(_finite(inp.current_drawdown, 1.0), 0.0), 1.0)
    jury_cap = min(max(_finite(inp.jury_cap, JURY_CAP_DEFAULT), 0.01), 0.95)
    regime = min(max(_finite(inp.regime_gate, 0.0), 0.0), 1.0)
    conviction = min(max(_finite(inp.conviction, 0.0), 0.0), 1.0)
    venue_max_lev = max(1.0, _finite(inp.venue_max_leverage, DEFAULT_VENUE_MAX_LEV))

    internal_cap = INTERNAL_CAP_RATIO * jury_cap
    R = max(0.0, internal_cap - cur_dd)

    stats = compute_stats(inp.symbol, inp.timeframe, inp.horizon)
    f_kelly = kelly_fraction(stats.win_rate, stats.payoff)

    # Stop distance: explicit, else empirical adverse excursion, clamped.
    if inp.stop_distance is not None and _finite(inp.stop_distance, 0.0) > 0:
        stop = _finite(inp.stop_distance, MIN_STOP)
    else:
        stop = stats.avg_max_drawdown / 100.0  # column is a percent
    stop = min(max(stop, MIN_STOP), MAX_STOP)

    # Risk budget rho (fraction of equity lost if the stop hits).
    rho_kelly = QUARTER_KELLY * f_kelly
    rho_dd = DD_BUDGET_K * R
    rho = min(rho_kelly, rho_dd) * regime * conviction
    rho = max(0.0, rho)

    net_edge = stats.expectancy - ROUNDTRIP_COST_PCT
    result = SizingResult(
        approved=False, symbol=stats.symbol, timeframe=stats.timeframe,
        equity=equity, internal_cap=internal_cap, drawdown_room_R=R,
        win_rate=stats.win_rate, payoff=stats.payoff, full_kelly=f_kelly,
        expectancy=stats.expectancy, expectancy_stderr=stats.expectancy_stderr,
        net_edge=net_edge, risk_budget_rho=rho, stop_distance=stop,
        notional=0.0, leverage=0.0,
        margin=0.0, worst_case_loss=0.0, reasons=reasons,
    )

    if equity <= 0:
        reasons.append("no equity")
        return result
    if R <= 0:
        reasons.append("drawdown room exhausted (R<=0): RiskGovernor would block")
        return result
    if regime <= 0:
        reasons.append("regime gate closed (risk-off)")
        return result
    if f_kelly <= 0:
        reasons.append("empirical edge non-positive (Kelly<=0): no bet")
        return result
    # Net-of-cost edge gate: the bucket must have enough samples AND a per-trade
    # expectancy that clears the round-trip cost by a statistical margin, else a
    # nominally-positive Kelly would still bleed fees on a coin-flip edge.
    if stats.n < MIN_EDGE_SAMPLES:
        reasons.append(
            f"thin bucket n={stats.n} < min {MIN_EDGE_SAMPLES}: no bet")
        return result
    required = EDGE_STDERR_MULT * stats.expectancy_stderr
    if net_edge <= required:
        reasons.append(
            f"net edge {net_edge:.3f}% (exp {stats.expectancy:.3f}% - cost "
            f"{ROUNDTRIP_COST_PCT:.2f}%) <= {EDGE_STDERR_MULT:.1f} stderr "
            f"{required:.3f}%: edge not significant after fees")
        return result
    if rho <= 0:
        reasons.append("risk budget collapsed to zero")
        return result

    notional = (rho * equity) / stop
    leverage = notional / equity
    if leverage > venue_max_lev:
        # Cap leverage; this lowers notional and the realised risk (safe).
        leverage = venue_max_lev
        notional = leverage * equity
        reasons.append(
            f"leverage capped at venue max {venue_max_lev:.0f}x "
            f"(realised risk below budget)"
        )
    margin = notional / leverage if leverage > 0 else 0.0
    worst_case_loss = notional * stop

    result.notional = notional
    result.leverage = leverage
    result.margin = margin
    result.worst_case_loss = worst_case_loss
    result.approved = notional > 0
    reasons.append(
        f"p={stats.win_rate:.3f} b={stats.payoff:.2f} kelly={f_kelly:.3f} "
        f"R={R:.4f} rho={rho:.4f} stop={stop:.4f} -> lev={leverage:.2f}x"
    )
    if stats.shrunk:
        reasons.append(f"thin bucket (n={stats.n}): win-rate shrunk to prior")
    return result
