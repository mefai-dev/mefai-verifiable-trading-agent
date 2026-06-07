---
name: empirical-tp-sl-optimizer
description: Find the best take-profit / stop-loss bracket for a crypto strategy slice from labeled outcome history. Grid-searches a ladder of TP and SL levels over a (symbol, timeframe, signal_type) slice using pre-recorded barrier-touch times, returning the bracket with the best risk-honest expectancy plus the full grid and a significance gate. Use when the user asks where to set TP/SL, wants to optimize a bracket, compare reward:risk levels, or measure a strategy on a live forward window.
---

# Empirical TP/SL Optimizer

Pick the take-profit and stop-loss levels that historically gave the best
expectancy per unit of risk for a strategy slice, replayed exactly from recorded
barrier-touch times (no price re-simulation, no look-ahead).

## When to reach for this

- "Where should TP and SL sit for BTCUSDT 1h buy signals?"
- "Which reward:risk ratio actually paid on 15m shorts?"
- "Re-measure the bracket on only the signals that closed after lock."

## How it resolves a trade

For a chosen `(TP=t, SL=s)`: a trade is a WIN `+t` if its TP barrier was touched
before its SL barrier, a LOSS `-s` if the SL came first, a tie (same recorded
second) is charged pessimistically as a loss, and a trade that touched neither
closes at the realized horizon PnL CLAMPED into `(-s, +t)`. See
[references/methodology.md](references/methodology.md).

## Run it

Wraps the audited module at
`bnbhack/agent/tp_sl_optimizer.py`. Read-only, no network.

```python
import sys
sys.path.insert(0, "bnbhack/agent")
from tp_sl_optimizer import optimize

res = optimize(symbol="BTCUSDT", timeframe="1h", signal_type="buy")
print(res.note)
if res.recommend and res.best_per_risk:
    c = res.best_per_risk
    print(f"TP {c.tp}% / SL {c.sl}%  exp {c.expectancy:+.3f}%  "
          f"per-risk {c.expectancy_per_risk:+.3f}R  n={c.n}")
for c in res.grid[:5]:
    print(c.tp, c.sl, c.expectancy, c.expectancy_per_risk, c.n)
```

Inputs: `symbol`, `timeframe`, `signal_type` (any may be None to pool),
`since_ts` (unix seconds; restrict to the live forward window), `min_samples`.

Outputs: `recommend` (bool), `best_per_risk` (risk-honest pick), `best` (raw max
expectancy, for reference), full `grid` of cells sorted by per-risk expectancy,
and a human `note`.

## Live forward proof

Pass `since_ts` equal to the submission-lock timestamp to measure the same
ladder on only fresh, un-backfillable outcomes. This is what turns a historical
optimization into a live, judge-watchable result.

## Backtest / verify

```bash
python3 bnbhack/skills/empirical-tp-sl-optimizer/backtest/backtest.py
```

Runs several slices, prints the recommended bracket and grid head, and checks the
recommendation logic (recommend implies positive expectancy above one standard
error and enough samples).

## Limitations

- Only `status='completed'` rows are read, so any selection effect in how a
  signal is marked complete carries into the estimate.
- Raw expectancy drifts toward the widest stop (stops rarely trigger there); the
  recommendation keys off expectancy-per-unit-risk with a one-sigma gate to
  counter this. Treat a single backtest as a hypothesis, confirm on `since_ts`.
- Ties (both barriers in the same recorded second) are charged as losses; this is
  conservative and slightly understates wins on very fast timeframes.
