---
name: meta-strategy-composer
description: One end-to-end crypto strategy pipeline that fuses asset selection, bracket optimization, regime gating and risk-budgeted sizing into a single backtestable decision. Chains the Narrative Rotation, Empirical TP/SL Optimizer, Regime Risk Governor and Risk-Budgeted Allocator skills so the agent picks what to trade, where to set TP/SL, whether the regime allows it, and how large to go, all inside one drawdown budget. Use when the user wants a complete trade plan, a full portfolio allocation across signals, or to combine the individual strategy skills into one workflow.
---

# Meta-Strategy Composer

The union of all the strategy skills as one pipeline. Given an account equity, a
current drawdown, and a live regime, it produces a complete, sized, bracketed,
gated trade plan across the best assets, inside a single drawdown budget.

## When to reach for this

- "Give me a full trade plan for 10k with 4% drawdown in a risk-on regime."
- "Allocate the whole book across the best signals right now."
- "Run selection, bracket, regime and sizing together, not one at a time."

## The pipeline

```
1. SELECT   narrative-rotation        -> top-N assets by verified expectancy
2. BRACKET  empirical-tp-sl-optimizer -> best risk-honest TP/SL per asset
3. GATE     regime-risk-governor      -> deploy? defensive bracket? size scale?
4. SIZE     risk-budgeted-allocator   -> notional / leverage inside the budget
5. BUDGET   compose                   -> sum risk stays within the account budget
```

Each stage hands its output to the next; the final stage enforces that the SUM of
per-trade worst-case losses stays inside `DD_BUDGET_K * R * equity`, so the whole
portfolio, not just each leg, respects the drawdown cap. See
[references/methodology.md](references/methodology.md).

## Run it

Wraps all four audited modules under
`bnbhack/agent/`. Read-only: it never trades or signs.

```python
import sys
sys.path.insert(0, "bnbhack/skills/meta-strategy-composer/backtest")
from backtest import compose_plan

plan = compose_plan(
    equity=10_000.0, current_drawdown=0.04, jury_cap=0.20,
    regime_direction=1, regime_strength=0.7,
    timeframe="1h", signal_type="buy", top_n=5,
)
print(plan["portfolio_worst_case_loss"], plan["budget_ceiling"])
for leg in plan["legs"]:
    print(leg["symbol"], leg["deploy"], leg["tp"], leg["sl"],
          leg["leverage"], leg["worst_case_loss"])
```

Inputs: `equity`, `current_drawdown`, `jury_cap`, `regime_direction`,
`regime_strength`, `timeframe`, `signal_type`, `top_n`, optional `since_ts`.

Outputs: a per-leg plan (selected symbol, chosen TP/SL, deploy decision, regime
scale, leverage, notional, worst-case loss) plus the portfolio-level budget check.

## Live forward proof

Pass `since_ts` = submission-lock time. Every stage then keys off only outcomes
that resolved during the judged window: selection ranks fresh edge, brackets are
re-optimized on fresh trades, and the plan is a genuinely live decision.

## Backtest / verify

The pipeline IS the backtest entry point. Run:

```bash
python3 bnbhack/skills/meta-strategy-composer/backtest/backtest.py
```

It composes plans across a sweep of account states and verifies, in every
scenario, both the portfolio budget invariant (sum of leg worst-case losses <=
budget ceiling) and the per-leg bound (each deployed leg <= its equal split of the
budget). A run that deploys nothing in every scenario is reported as not-passing,
since an empty plan proves nothing.

## Limitations

- It inherits every component limitation: in-sample selection bias, the regime
  input being caller-supplied, and edge estimated from past outcomes. The guards
  (min_samples, one-sigma gate, baseline comparison, `since_ts` forward window,
  drawdown floor) are inherited too.
- The portfolio budget treats leg risks as additive (worst case all stops hit
  together); it does not model correlation, so the real expected drawdown is
  usually below the budget ceiling, never above it. This is conservative by design.
- It does not place orders. Sizing and gating are advisory until wired to a live
  executor and the on-chain RiskGovernor.
