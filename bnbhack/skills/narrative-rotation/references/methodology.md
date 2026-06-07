# Narrative Rotation · methodology

## Layer 1 · verified ranking (backbone)

Each symbol is scored over the labeled outcome record at a chosen horizon
(default 24h, the near-fully-resolved window):

- `expectancy` mean realized PnL percent over resolved trades
- `win_rate` wins / resolved
- `brier_skill` directional skill vs a coin-flip climatology, in [-1, 1]
- `realized_pnl` summed realized PnL percent points
- `avg_drawdown` mean adverse excursion percent

Only symbols with `n_resolved >= min_samples` qualify. The order is deterministic:
primary rank metric, then sample count, then key, so ties resolve identically
regardless of row order.

Rank metric choice:

| rank_by | favors | use when |
| --- | --- | --- |
| expectancy | per-trade edge, size-neutral | default rotation |
| skill | directional accuracy | thin or noisy PnL |
| win_rate | hit rate | bracket strategies |
| pnl | total realized points | high-sample, size-aware |

## Layer 2 · narrative tilt (optional, live)

A live CoinMarketCap overlay turns "what is the market paying attention to" into a
per-symbol multiplier `m in [m_lo, 1 + m_hi]`, built from the CMC client methods:

- `trending_narratives()` presence -> attention score in [0, 1]
- `global_metrics_latest()` / `derivatives_metrics()` -> a global risk-on/off scalar
- 24h momentum sign (from `quotes_latest()`) agreeing with the symbol's dominant
  signal direction -> tilt up

The tilt multiplies the verified rank metric. It can only REWEIGHT an already
verified-qualified symbol; it can never introduce a symbol that lacks a verified
edge, so narrative noise cannot override the record. If the feed is unavailable,
`m = 1` for every symbol and the rotation is the pure verified ranking.

## Forming the basket

- Take the top-N qualified symbols after the (optional) tilt.
- Equal-weight is the default; a conviction-weighted variant scales each leg by
  its normalized rank metric (hand off to the Risk-Budgeted Allocator for the
  actual position sizes).

## Why a baseline comparison

A ranking is only useful if the top set beats the population. The backtest reports
the top-N basket expectancy against the global `overall` baseline and against a
bottom-N basket. A top set that does not separate from the baseline is noise and
should not be traded.

## Overfit guards

- `min_samples` floor removes thin buckets that rank high by luck.
- `since_ts` re-runs the ranking on the live forward window only.
- The skill is read-only and deterministic, so a claimed ranking is reproducible
  from a DB snapshot.
