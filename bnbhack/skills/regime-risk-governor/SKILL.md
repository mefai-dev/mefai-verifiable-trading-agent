---
name: regime-risk-governor
description: Decide whether to deploy a strategy right now and at what size, given the live market regime and remaining drawdown room. Gates a backtested TP/SL bracket against the current regime direction and strength, and against the drawdown-budget room, returning deploy / stand-aside plus a size scale. Use when the user asks if it is safe to trade now, wants a risk-off killswitch, needs regime-aware position scaling, or asks how much drawdown room is left before trading must stop.
license: MIT
metadata:
  version: "1.0.0"
  category: trading-strategy
  spec: skill.json
---

# Regime Risk Governor

A two-gate decision layer: deploy a strategy only when the live market regime
backs it AND there is drawdown room left, otherwise scale down or stand aside.

## When to reach for this

- "Is it safe to deploy the BTC long bracket in this regime?"
- "Cut size when the market turns against the trade."
- "How much drawdown room is left before the agent must halt?"

## Two gates

1. Regime gate: takes a backtested bracket and the live regime
   (direction +1/-1/0, strength 0..1). When the regime backs the trade it deploys
   the recommended bracket and scales size up with conviction; when it opposes it
   falls back to the tightest defensive bracket and cuts size, or stands aside on
   extreme opposition.
2. Drawdown gate: mirrors the on-chain RiskGovernor. As current drawdown
   approaches the budget, the remaining room `R` shrinks the allowed size to zero,
   a hard killswitch that the regime gate cannot override.

See [references/methodology.md](references/methodology.md).

## Run it

Wraps the audited `regime_overlay` in
`bnbhack/agent/tp_sl_optimizer.py` and the drawdown room
from `bnbhack/agent/sizing.py`. Read-only.

```python
import sys
sys.path.insert(0, "bnbhack/agent")
from tp_sl_optimizer import optimize, regime_overlay

res = optimize(symbol="BTCUSDT", timeframe="1h", signal_type="buy")
# Live regime: +1 risk-on backs the long, strength 0.7
decision = regime_overlay(res, regime_direction=1, regime_strength=0.7)
print(decision.deploy, decision.risk_scale, decision.reason)
```

Drawdown gate (room that scales size to zero near the cap):

```python
from sizing import INTERNAL_CAP_RATIO
internal_cap = INTERNAL_CAP_RATIO * 0.20      # 0.7 * jury_cap
R = max(0.0, internal_cap - current_drawdown) # 0 -> must halt
```

Inputs: an `OptimizeResult` (from the TP/SL Optimizer), `regime_direction`,
`regime_strength`, and the current drawdown for the room gate.

Outputs: `deploy` (bool), `bracket` (which TP/SL to use), `risk_scale` (0..1
multiplier, feed it as `regime_gate` to the Risk-Budgeted Allocator), `alignment`
(+1/-1/0), and a human `reason`.

## Backtest / verify

```bash
python3 bnbhack/skills/regime-risk-governor/backtest/backtest.py
```

Sweeps regime direction x strength for a slice and confirms the monotone
properties: aligned size rises with conviction, opposed size falls, extreme
opposition stands aside, and the drawdown gate forces size to zero at the cap.

## Limitations

- The regime is supplied live by the caller (e.g. from a CMC fear/greed +
  rotation read); the overlay does not fetch it, so a wrong regime input yields a
  wrong gate. Wire it to a real regime source.
- The historical slice carries no stored regime, so the gate is a forward overlay,
  not a backtested regime model. It scales a proven bracket, it does not prove the
  regime call itself.
- The drawdown gate trusts the caller's `current_drawdown`; for an enforced halt,
  pair it with the on-chain RiskGovernor.
