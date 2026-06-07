# Risk-Budgeted Allocator · methodology

## Goal

Produce a position size that cannot breach a drawdown budget and is scaled by the
empirical edge of the specific (symbol, timeframe), not a guessed win rate.

## Symbols

- `s` stop distance as a fraction of entry price (e.g. 0.02 = a 2% stop)
- `p` empirical win probability for the (symbol, timeframe), shrunk toward a
  global prior so thin buckets do not produce extreme Kelly values
- `b` empirical payoff ratio = avg_win / avg_loss (both positive percents)
- `f_k` win/loss Kelly fraction = `p - (1 - p) / b`, floored at 0
- `rho` per-trade risk budget = fraction of equity lost IF the stop is hit
- `R` remaining drawdown room
- `k` drawdown-budget coefficient (default 0.15)

## Derivation

```
internal_cap = INTERNAL_CAP_RATIO * jury_cap        # default 0.7 * 0.20 = 0.14
R            = max(0, internal_cap - current_drawdown)
f_k          = max(0, p - (1 - p) / b)
rho          = min(QUARTER_KELLY * f_k, k * R) * regime_gate * conviction
notional     = (rho * equity) / s                   # so notional * s == rho*equity
leverage     = min(notional / equity, venue_max)
margin       = notional / leverage
worst_case_loss = notional * s = rho * equity
```

Because `rho <= k * R`, the worst-case loss is at most `k * R * equity`. As
`current_drawdown -> internal_cap`, `R -> 0`, so `rho -> 0` and the size collapses
to zero. The agent cannot trade itself past the cap. This is the off-chain twin of
the on-chain RiskGovernor killswitch.

## Empirical edge (shrinkage)

`p`, `avg_win`, `avg_loss` are read from the labeled outcome store per
(symbol, timeframe) at the chosen horizon. Each is Beta/sample shrunk toward the
global prior with pseudo-count 25, so a bucket with few samples leans on the
population estimate and is flagged `shrunk`. Payoff `b` is clamped (default 20) so
a near-zero avg_loss cannot manufacture a meaningless near-1 Kelly.

## Why quarter-Kelly

Full Kelly maximizes long-run growth but has punishing variance and assumes the
estimated edge is exact. Quarter-Kelly trades a small amount of growth for a large
reduction in drawdown variance, which matters when a single max-drawdown breach is
a disqualification.

## Constants (defaults)

| constant | value | meaning |
| --- | --- | --- |
| QUARTER_KELLY | 0.25 | cap at a quarter of full Kelly |
| DD_BUDGET_K | 0.15 | per-trade fraction of remaining room R |
| JURY_CAP_DEFAULT | 0.20 | assumed max-drawdown DQ threshold |
| INTERNAL_CAP_RATIO | 0.70 | run to 70% of the cap, never to it |
| SHRINK_PSEUDO | 25 | pseudo-count for win-rate shrinkage |
| PAYOFF_CAP | 20 | clamp on avg_win/avg_loss |
| MIN_STOP / MAX_STOP | 0.002 / 0.50 | stop-distance bounds |

## Failure modes and guards

- Non-finite inputs (NaN/inf) are coerced to safe defaults BEFORE clamping, since
  NaN defeats min/max.
- `equity <= 0`, `R <= 0`, closed regime gate, non-positive Kelly, or collapsed
  budget each return `approved=False` with a stated reason rather than a guess.
