"""
MEFAI BNB HACK · TP/SL Optimizer (data-driven, pre-computed barriers)

Track 2 backtest asset. The MEFAI signal pipeline already records, for every
labeled signal, whether each of a fixed ladder of take-profit and stop-loss
barriers was touched and HOW MANY SECONDS AFTER ENTRY it was touched. That lets
us replay any (TP, SL) bracket exactly without re-simulating price: for a chosen
TP level t and SL level s a trade is a WIN (+t%) if its TP barrier was hit before
its SL barrier, a LOSS (-s%) if the SL came first, and otherwise it closes at the
realized horizon PnL clamped into the (-s, +t) band (a trade that touched neither
barrier must by definition have stayed inside it, so the clamp keeps every outcome
consistent with the bracket and stops a wide stop from importing out-of-band gains).

This module grids over the available barrier ladder for a (symbol, timeframe,
signal_type) slice and returns the bracket with the best expectancy, plus the
full grid for inspection. It is data-driven and deterministic: read-only DB, no
network. The barrier columns come from a fixed whitelist so user-supplied
symbol/timeframe/signal_type are always bound parameters.

A `since_ts` filter lets the same optimizer run on the LIVE forward segment
(signals that closed after submission lock) so the judged window is measured on
fresh, un-backfillable outcomes rather than only the historical book.

Caveats the caller should keep in mind: only rows with status='completed' are
read, so any selection effect in how the pipeline marks a signal completed would
carry into the estimate; trades whose chosen horizon PnL is still NULL are
unresolved and dropped (counted per cell as n_unresolved); and the recommendation
keys off expectancy-per-unit-risk with a one-sigma significance gate, because raw
expectancy alone drifts toward the widest stop.
"""

from __future__ import annotations

import math
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

SIGNAL_DB = os.getenv("MEFAI_SIGNAL_DB", "data/signal.db")

# Take-profit ladder: (percent, hit-column). Columns are a FIXED whitelist; the
# percent is the realized gain when that barrier is the one that triggers.
TP_LEVELS: List[Tuple[float, str]] = [
    (0.5, "tp_05"),
    (1.0, "tp_1"),
    (1.5, "tp_15"),
    (2.0, "tp_2"),
    (3.0, "tp_3"),
    (5.0, "tp_5"),
    (10.0, "tp_10"),
]

# Stop-loss ladder: (percent, hit-column).
SL_LEVELS: List[Tuple[float, str]] = [
    (0.2, "sl_02"),
    (0.3, "sl_03"),
    (0.5, "sl_05"),
    (0.7, "sl_07"),
    (0.9, "sl_09"),
    (1.0, "sl_1"),
    (1.5, "sl_15"),
    (2.0, "sl_2"),
    (3.0, "sl_3"),
    (4.0, "sl_4"),
    (5.0, "sl_5"),
    (7.0, "sl_7"),
    (10.0, "sl_10"),
]

# Horizon PnL column used when neither barrier was touched (trade left open).
# Short timeframes resolve on the 1h column, mid on 4h, slow on 24h.
_HORIZON_BY_TF: Dict[str, Tuple[str, str]] = {
    "1m": ("pnl_1h", "1h"),
    "5m": ("pnl_1h", "1h"),
    "15m": ("pnl_1h", "1h"),
    "30m": ("pnl_1h", "1h"),
    "1h": ("pnl_4h", "4h"),
    "4h": ("pnl_24h", "24h"),
    "1d": ("pnl_24h", "24h"),
}
_DEFAULT_HORIZON: Tuple[str, str] = ("pnl_24h", "24h")

MIN_SAMPLES = 100         # a (TP,SL) cell below this is reported but not recommended
PAYOFF_CAP = 50.0         # clamp avg_win/avg_loss so a near-zero avg_loss can't blow up
# A recommended bracket must use a stop at least this wide. The raw
# expectancy-per-risk objective divides a COST-BLIND gross expectancy by the
# stop, so it drifts monotonically to the TIGHTEST stop (e.g. 0.2 percent) where
# the round-trip fee is ~100 percent of the risked amount and same-second TP/SL
# ties are charged as losses. Out of sample that tuned tight-stop bracket is
# net-NEGATIVE while the fixed wide-stop bracket is net-positive. The floor (set
# at a few times the round-trip cost) keeps a fee-dominated rung from ever being
# recommended; the recommendation now ranks NET expectancy per risk, not gross.
MIN_SL_RUNG = float(os.getenv("BNBHACK_MIN_SL_RUNG", "1.0"))
DEFAULT_COST_PCT = float(os.getenv("BNBHACK_ROUNDTRIP_COST_PCT", "0.2"))


def _finite(x: object, default: float = 0.0) -> float:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _hit(flag: object) -> bool:
    """A barrier is hit when its flag coerces to 1. The column is an integer in
    the table, but coercing defends against a stray '1'/1.0/None value."""
    try:
        return int(flag or 0) == 1
    except (TypeError, ValueError):
        return False


def _clamp(x: float, lo: float, hi: float) -> float:
    if x != x:  # NaN
        return lo
    return lo if x < lo else hi if x > hi else x


def _norm_symbol(symbol: Optional[str]) -> Optional[str]:
    """signal_performance stores perp symbols with a .P suffix. Accept either
    form and normalize so callers can pass BTCUSDT or BTCUSDT.P."""
    if not symbol:
        return None
    s = symbol.strip().upper()
    if not s:
        return None
    return s if s.endswith(".P") else s + ".P"


def _horizon_for_tf(timeframe: Optional[str]) -> Tuple[str, str]:
    if not timeframe:
        return _DEFAULT_HORIZON
    return _HORIZON_BY_TF.get(timeframe.strip().lower(), _DEFAULT_HORIZON)


def _ro_connect(path: str = SIGNAL_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class GridCell:
    tp: float
    sl: float
    rr: float                 # reward:risk ratio tp/sl
    n: int                    # resolved trades in this cell
    n_unresolved: int         # open trades dropped for a NULL horizon PnL
    barrier_wins: int         # terminated at the TP barrier
    barrier_losses: int       # terminated at the SL barrier (excludes ties)
    ties: int                 # both barriers same second, charged as a loss
    open_closes: int          # neither barrier hit, closed at clamped horizon
    win_rate: float           # fraction of resolved trades with positive return
    avg_win: float            # mean return of positive-return trades (+)
    avg_loss: float           # mean return of negative-return trades (negative)
    payoff: float             # avg_win / |avg_loss|, clamped to PAYOFF_CAP
    expectancy: float         # mean signed return % per trade (gross, pre-cost)
    expectancy_stderr: float  # standard error of the mean return
    expectancy_per_risk: float  # gross expectancy / sl (kept for reference only)
    total_return: float       # summed signed return % over all trades
    net_expectancy: float = 0.0       # expectancy minus the round-trip cost
    net_expectancy_per_risk: float = 0.0  # net_expectancy / sl (the ranked field)


@dataclass
class OptimizeResult:
    symbol: Optional[str]
    timeframe: Optional[str]
    signal_type: Optional[str]
    horizon: str
    since_ts: Optional[int]
    n_total: int              # rows pulled for the slice
    n_unresolved: int         # unresolved trades of the RECOMMENDED bracket
                              # (cell-dependent: see each GridCell.n_unresolved)
    min_samples: int          # eligibility threshold applied to each cell's n
    best: Optional[GridCell]            # max expectancy (>= min_samples)
    best_per_risk: Optional[GridCell]   # max expectancy_per_risk (>= min_samples)
    grid: List[GridCell] = field(default_factory=list)
    recommend: bool = False   # best_per_risk clears samples + 1-sigma edge > 0
    note: str = ""


def _load_rows(
    conn: sqlite3.Connection,
    symbol: Optional[str],
    timeframe: Optional[str],
    signal_type: Optional[str],
    since_ts: Optional[int],
    horizon_col: str,
) -> List[sqlite3.Row]:
    """Pull only the barrier hit/time columns + horizon PnL for the slice.

    All filter values are bound parameters; only the whitelisted barrier and
    horizon column names are interpolated into the SELECT list."""
    cols = ["entry_time", horizon_col]
    for _pct, c in TP_LEVELS:
        cols += [f"{c}_hit", f"{c}_time"]
    for _pct, c in SL_LEVELS:
        cols += [f"{c}_hit", f"{c}_time"]
    select = ", ".join(cols)

    where = ["status = 'completed'"]
    params: List[object] = []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol)
    if timeframe:
        where.append("LOWER(timeframe) = ?")
        params.append(timeframe.strip().lower())
    if signal_type:
        where.append("LOWER(signal_type) = ?")
        params.append(signal_type.strip().lower())
    if since_ts is not None:
        where.append("entry_time >= ?")
        params.append(int(since_ts))

    sql = f"SELECT {select} FROM signal_performance WHERE {' AND '.join(where)}"
    return conn.execute(sql, params).fetchall()


def _resolve_trade(
    row: sqlite3.Row,
    tp_pct: float,
    tp_col: str,
    sl_pct: float,
    sl_col: str,
    horizon_col: str,
) -> Optional[Tuple[str, float]]:
    """Resolve one trade under a (TP, SL) bracket.

    Returns (outcome, signed_return_pct) where outcome is 'win' | 'loss' | 'tie'
    | 'open', or None if the trade cannot be resolved (open with no horizon PnL).
    A 'tie' is economically a loss (return -sl) but kept as its own label so the
    caller can see how much of a cell's loss mass is intrabar ambiguity.

    Tie-break: if both barriers were touched in the SAME recorded second we
    cannot know intrabar order, so we assume the STOP filled first (pessimistic,
    risk-honest) rather than crediting the win."""
    tp_hit = _hit(row[f"{tp_col}_hit"])
    sl_hit = _hit(row[f"{sl_col}_hit"])

    if tp_hit and sl_hit:
        tp_t = row[f"{tp_col}_time"]
        sl_t = row[f"{sl_col}_time"]
        # Times are seconds-from-entry; both present when both hit.
        if tp_t is not None and sl_t is not None:
            if tp_t < sl_t:
                return ("win", tp_pct)
            if sl_t < tp_t:
                return ("loss", -sl_pct)
            return ("tie", -sl_pct)  # same second, assume stop filled first
        # Defensive: both hit but a time is missing -> we cannot prove the TP
        # came first, so default to the loss to honor the pessimistic policy.
        return ("loss", -sl_pct)

    if tp_hit:
        return ("win", tp_pct)
    if sl_hit:
        return ("loss", -sl_pct)

    # Neither barrier touched: the price path stayed inside the bracket, so the
    # trade closes at the realized horizon PnL clamped into the (-sl, +tp) band.
    # The clamp guarantees the open return is consistent with "no barrier hit"
    # and prevents a wide stop from crediting an out-of-band horizon move.
    pnl = row[horizon_col]
    if pnl is None:
        return None
    return ("open", _clamp(_finite(pnl, 0.0), -sl_pct, tp_pct))


def _eval_cell(rows: List[sqlite3.Row], tp: float, tp_col: str,
               sl: float, sl_col: str, horizon_col: str,
               cost: float = 0.0) -> GridCell:
    barrier_wins = barrier_losses = ties = open_closes = 0
    unresolved = 0
    pos_n = neg_n = 0
    sum_win = sum_loss = total = sum_sq = 0.0
    n = 0
    # All statistics (win_rate, avg_win/avg_loss, payoff, expectancy) bucket by
    # the realized return SIGN over the SAME resolved population, so the numbers
    # reconcile. The barrier/tie/open counts are a separate, descriptive view of
    # HOW each trade terminated. Open returns are already clamped to the bracket
    # band in _resolve_trade, so no out-of-band value can enter these sums.
    for row in rows:
        res = _resolve_trade(row, tp, tp_col, sl, sl_col, horizon_col)
        if res is None:
            unresolved += 1
            continue
        outcome, ret = res
        n += 1
        total += ret
        sum_sq += ret * ret
        if outcome == "win":
            barrier_wins += 1
        elif outcome == "loss":
            barrier_losses += 1
        elif outcome == "tie":
            ties += 1
        else:
            open_closes += 1
        # An exactly flat trade (ret == 0) counts toward n and expectancy but is
        # neither a win nor a loss, so pos_n + neg_n can be < n.
        if ret > 0:
            pos_n += 1
            sum_win += ret
        elif ret < 0:
            neg_n += 1
            sum_loss += ret

    win_rate = (pos_n / n) if n else 0.0
    avg_win = (sum_win / pos_n) if pos_n else 0.0
    avg_loss = (sum_loss / neg_n) if neg_n else 0.0
    if avg_loss < 0:
        payoff = min(PAYOFF_CAP, avg_win / abs(avg_loss)) if avg_win > 0 else 0.0
    else:
        payoff = PAYOFF_CAP if avg_win > 0 else 0.0
    expectancy = (total / n) if n else 0.0
    # Standard error of the mean return (sample variance / n).
    if n > 1:
        var = max(0.0, (sum_sq - n * expectancy * expectancy) / (n - 1))
        stderr = math.sqrt(var / n)
    else:
        stderr = 0.0
    per_risk = (expectancy / sl) if sl > 0 else 0.0
    # NET of the round-trip cost: the fee is paid once per round-trip regardless
    # of the stop width, so subtracting it BEFORE dividing by sl is what stops the
    # objective from rewarding a fee-dominated tight stop. This is the field the
    # recommendation ranks; the gross per_risk is kept only for inspection.
    net_expectancy = expectancy - cost
    net_per_risk = (net_expectancy / sl) if sl > 0 else 0.0

    return GridCell(
        tp=tp, sl=sl, rr=round(tp / sl, 3) if sl > 0 else 0.0,
        n=n, n_unresolved=unresolved,
        barrier_wins=barrier_wins, barrier_losses=barrier_losses,
        ties=ties, open_closes=open_closes,
        win_rate=round(win_rate, 4),
        avg_win=round(avg_win, 4), avg_loss=round(avg_loss, 4),
        payoff=round(payoff, 4),
        expectancy=round(expectancy, 5),
        expectancy_stderr=round(stderr, 5),
        expectancy_per_risk=round(per_risk, 5),
        total_return=round(total, 3),
        net_expectancy=round(net_expectancy, 5),
        net_expectancy_per_risk=round(net_per_risk, 5),
    )


def optimize(
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    signal_type: Optional[str] = None,
    since_ts: Optional[int] = None,
    min_samples: int = MIN_SAMPLES,
    db_path: str = SIGNAL_DB,
    cost_pct: Optional[float] = None,
    min_sl: float = MIN_SL_RUNG,
) -> OptimizeResult:
    """Grid-search the barrier ladder for the best (TP, SL) bracket.

    symbol/timeframe/signal_type narrow the slice (any may be None to pool).
    since_ts (unix seconds) restricts to signals entered at or after that time
    so the optimizer can measure the live forward window. Returns the bracket
    with the highest expectancy and the highest expectancy-per-unit-risk, plus
    the full grid. A bracket is only `recommend`ed when it clears min_samples
    and has positive expectancy."""
    horizon_col, horizon_label = _horizon_for_tf(timeframe)
    norm_symbol = _norm_symbol(symbol)
    # Round-trip cost subtracted from every cell's gross expectancy. Prefer the
    # per-symbol liquidity-tier cost (same basis as the sizer) when a symbol is
    # given; fall back to the supplied cost or the deep-pool default. Lazy import
    # keeps this module importable without the sizing module.
    if cost_pct is not None:
        cost = float(cost_pct)
    elif symbol:
        try:
            from sizing import roundtrip_cost  # local, no import cycle
            cost = roundtrip_cost(symbol)
        except Exception:
            cost = DEFAULT_COST_PCT
    else:
        cost = DEFAULT_COST_PCT

    conn = _ro_connect(db_path)
    try:
        rows = _load_rows(conn, norm_symbol, timeframe, signal_type,
                          since_ts, horizon_col)
    finally:
        conn.close()

    n_total = len(rows)
    if n_total == 0:
        return OptimizeResult(
            symbol=norm_symbol, timeframe=timeframe, signal_type=signal_type,
            horizon=horizon_label, since_ts=since_ts, n_total=0,
            n_unresolved=0, min_samples=min_samples, best=None,
            best_per_risk=None, grid=[], recommend=False,
            note="no completed signals for this slice",
        )

    grid: List[GridCell] = []
    for tp_pct, tp_col in TP_LEVELS:
        for sl_pct, sl_col in SL_LEVELS:
            grid.append(_eval_cell(rows, tp_pct, tp_col, sl_pct, sl_col,
                                   horizon_col, cost))

    # Eligible to be RECOMMENDED: enough samples AND a stop at least min_sl wide.
    # The stop floor is what removes the fee-dominated tight-stop cells the gross
    # per-risk objective used to drift toward; cells below it are still kept in
    # the grid for inspection, just never recommended.
    eligible = [c for c in grid if c.n >= min_samples and c.sl >= min_sl]
    # best = raw max GROSS expectancy (reference only; it drifts to the widest
    # stop). best_per_risk now ranks NET expectancy per unit risk, so a bracket
    # cannot win the ranking by hiding the round-trip fee inside a tiny stop.
    best = max(eligible, key=lambda c: c.expectancy) if eligible else None
    best_per_risk = (max(eligible, key=lambda c: c.net_expectancy_per_risk)
                     if eligible else None)
    # Recommend only when the risk-honest bracket has a positive NET expectancy
    # (after the round-trip cost) that also clears one standard error (a light
    # t > 1 gate), so a near-zero or fee-eaten edge is never advertised.
    recommend = (
        best_per_risk is not None
        and best_per_risk.net_expectancy > 0
        and best_per_risk.net_expectancy > best_per_risk.expectancy_stderr
    )
    rec_cell = best_per_risk if recommend else None
    n_unresolved = rec_cell.n_unresolved if rec_cell else (
        best_per_risk.n_unresolved if best_per_risk else 0)

    if not eligible:
        note = (f"no (TP,SL) bracket reached min_samples={min_samples} with a "
                f"stop >= {min_sl:.2f}% (largest cell "
                f"{max((c.n for c in grid), default=0)} trades)")
    elif not recommend:
        note = ("no bracket clears a significant positive edge net of the "
                f"{cost:.2f}% round-trip cost on this slice (direction edge is "
                "negative, flat, or inside the noise band after fees)")
    else:
        note = (f"recommend TP {rec_cell.tp}% / SL {rec_cell.sl}% -> net "
                f"expectancy {rec_cell.net_expectancy:+.3f}% "
                f"(gross {rec_cell.expectancy:+.3f}% - cost {cost:.2f}%, "
                f"+/-{rec_cell.expectancy_stderr:.3f}) net-per-risk "
                f"{rec_cell.net_expectancy_per_risk:+.3f}R over {rec_cell.n} trades")

    grid.sort(key=lambda c: c.net_expectancy_per_risk, reverse=True)
    return OptimizeResult(
        symbol=norm_symbol, timeframe=timeframe, signal_type=signal_type,
        horizon=horizon_label, since_ts=since_ts, n_total=n_total,
        n_unresolved=n_unresolved, min_samples=min_samples, best=best,
        best_per_risk=best_per_risk, grid=grid, recommend=recommend, note=note,
    )


_BUY_WORDS = {"buy", "long", "bull"}
_SELL_WORDS = {"sell", "short", "bear"}
# Above this regime conviction a directly opposed regime blocks the trade.
HOSTILE_BLOCK = 0.8


def _signal_direction(signal_type: Optional[str]) -> int:
    """Map the slice's signal_type to a trade direction: +1 long, -1 short, 0
    when the slice is pooled / direction-agnostic."""
    if not signal_type:
        return 0
    s = signal_type.strip().lower()
    if s in _BUY_WORDS:
        return 1
    if s in _SELL_WORDS:
        return -1
    return 0


@dataclass
class RegimeDecision:
    deploy: bool
    bracket: Optional[GridCell]   # the bracket to use if deploying
    risk_scale: float             # [0,1] size multiplier for the live regime
    alignment: int                # +1 regime backs the trade, -1 opposes, 0 neutral
    reason: str


def regime_overlay(
    result: OptimizeResult,
    regime_direction: int,
    regime_strength: float = 0.0,
) -> RegimeDecision:
    """Gate the backtested bracket against the LIVE market regime.

    The optimizer measures a bracket on history; this overlay decides whether to
    deploy it RIGHT NOW given the current regime (e.g. the CMC fear/greed and
    altcoin-rotation gate). The historical slice carries no stored regime, so the
    regime is supplied live by the caller and applied as a forward gate:

    - regime_direction: +1 risk-on / long-favorable, -1 risk-off / short-favorable,
      0 neutral. regime_strength in [0,1] is the regime conviction.
    - When the regime BACKS the slice's trade direction, deploy the recommended
      (risk-honest) bracket and scale size up with conviction.
    - When the regime OPPOSES it, fall back to the tightest-stop bracket that
      still shows a significant positive edge and cut size; if conviction is
      extreme (>= HOSTILE_BLOCK) or no defensive bracket exists, do not deploy.
    - When neutral or the slice is direction-agnostic, deploy at a moderate size.

    Returns a RegimeDecision; never raises."""
    if not result.recommend or result.best_per_risk is None:
        return RegimeDecision(
            deploy=False, bracket=None, risk_scale=0.0, alignment=0,
            reason="no significant backtested edge to deploy",
        )

    rd = _finite(regime_direction, 0.0)
    rdir = 1 if rd > 0 else -1 if rd < 0 else 0
    strength = _clamp(_finite(regime_strength, 0.0), 0.0, 1.0)
    sdir = _signal_direction(result.signal_type)
    alignment = sdir * rdir  # +1 aligned, -1 opposed, 0 neutral/unknown
    base = result.best_per_risk

    if alignment > 0:
        scale = _clamp(0.6 + 0.4 * strength, 0.0, 1.0)
        return RegimeDecision(
            deploy=True, bracket=base, risk_scale=round(scale, 3),
            alignment=1,
            reason=(f"regime backs {result.signal_type}; deploy recommended "
                    f"TP {base.tp}%/SL {base.sl}% at {scale:.0%} size"),
        )

    if alignment == 0:
        return RegimeDecision(
            deploy=True, bracket=base, risk_scale=0.6, alignment=0,
            reason=("regime neutral or slice direction-agnostic; deploy "
                    f"recommended TP {base.tp}%/SL {base.sl}% at 60% size"),
        )

    # Opposed regime: block on extreme conviction, else take the tightest-stop
    # bracket that still clears the same significance gate and cut size.
    if strength >= HOSTILE_BLOCK:
        return RegimeDecision(
            deploy=False, bracket=None, risk_scale=0.0, alignment=-1,
            reason=(f"regime strongly opposes {result.signal_type} "
                    f"(strength {strength:.2f}); stand aside"),
        )
    defensive = [
        c for c in result.grid
        if c.n >= result.min_samples
        and c.sl >= MIN_SL_RUNG
        and c.net_expectancy > 0
        and c.net_expectancy > c.expectancy_stderr
    ]
    if not defensive:
        return RegimeDecision(
            deploy=False, bracket=None, risk_scale=0.0, alignment=-1,
            reason="regime opposes and no defensive bracket has a significant edge",
        )
    # Tightest eligible stop first, break ties by the better NET per-risk edge.
    defensive.sort(key=lambda c: (c.sl, -c.net_expectancy_per_risk))
    pick = defensive[0]
    scale = _clamp(0.5 * (1.0 - strength), 0.0, 0.5)
    return RegimeDecision(
        deploy=True, bracket=pick, risk_scale=round(scale, 3), alignment=-1,
        reason=(f"regime opposes {result.signal_type}; defensive "
                f"TP {pick.tp}%/SL {pick.sl}% at {scale:.0%} size"),
    )
