# Meta-Strategy Composer · methodology

## Purpose

Fuse the four strategy skills into one decision so the agent answers, in a single
pass: what to trade, where to set TP/SL, whether the regime allows it now, and how
large to go, with the WHOLE portfolio inside one drawdown budget.

## Pipeline stages

### 1 · SELECT (narrative-rotation)

Rank symbols by verified expectancy over the labeled record (optionally tilted by
live narrative), take the top-N qualified symbols. This decides the universe.

### 2 · BRACKET (empirical-tp-sl-optimizer)

For each selected symbol, grid-search the TP/SL ladder on its
(symbol, timeframe, signal_type) slice and take the risk-honest recommended
bracket. A symbol with no significant edge is dropped here.

### 3 · GATE (regime-risk-governor)

Pass each bracket through the live regime overlay. The output is a deploy
decision, possibly a defensive bracket, and a `risk_scale` in [0, 1].

### 4 · SIZE (risk-budgeted-allocator)

For each deployed leg, size the position with the stop distance from its bracket,
the `risk_scale` as the `regime_gate`, and the remaining drawdown room `R`. Each
leg's worst-case loss is `notional * stop <= DD_BUDGET_K * R * equity`.

### 5 · BUDGET (compose)

The single account-level invariant the whole pipeline guarantees:

```
sum(leg.worst_case_loss for deployed legs) <= DD_BUDGET_K * R * equity
```

To enforce it, the per-leg budget is split across the deployed legs (equal split
by default), so the SUM of per-leg worst-case losses cannot exceed the account
budget ceiling. This makes the portfolio, not just each leg, respect the cap.

## Why this is the "union of all skills"

Each individual skill answers one question. The composer answers all of them in
order, with each stage's output constraining the next, and adds the one property
no single skill has: a portfolio-level drawdown budget. It is the single
backtestable pipeline that the cockpit and the live loop both call.

## Budget split

Default: split `DD_BUDGET_K * R * equity` equally across the `k` deployed legs, so
each leg sizes against `budget / k`. A conviction-weighted split (by each leg's
rank metric and regime scale) is available, but equal split is the safe default
because it bounds the worst case without assuming the edge estimates are exact.

## Conservatism note

The budget treats leg risks as additive (all stops hitting together), ignoring
correlation. Real diversified drawdown is usually below the ceiling, never above
it, so the bound is conservative. This is intentional: a max-drawdown breach is a
disqualification, so the pipeline errs toward under-risk.

## Forward measurement

With `since_ts` set to the submission-lock time, every stage keys off only
outcomes that resolved during the judged window: selection ranks fresh edge,
brackets re-optimize on fresh trades, and the resulting plan is a live decision,
not a replay of history.
