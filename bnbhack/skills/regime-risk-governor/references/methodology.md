# Regime Risk Governor · methodology

## Gate 1 · regime overlay

Inputs: a backtested `OptimizeResult` (with a recommended risk-honest bracket),
the live `regime_direction` (+1 risk-on / long-favorable, -1 risk-off /
short-favorable, 0 neutral), and `regime_strength` in [0, 1].

The slice's own trade direction is read from its `signal_type` (buy/long -> +1,
sell/short -> -1, pooled -> 0). `alignment = signal_dir * regime_dir`.

| alignment | action | size scale |
| --- | --- | --- |
| +1 backs | deploy the recommended bracket | `0.6 + 0.4 * strength` |
| 0 neutral / pooled | deploy the recommended bracket | `0.6` |
| -1 opposes, strength < 0.8 | deploy tightest defensive bracket | `0.5 * (1 - strength)` |
| -1 opposes, strength >= 0.8 | stand aside | `0` |

A "defensive bracket" is the tightest-stop cell that still clears the same
samples + one-sigma positive-edge gate as the recommendation. If no defensive
bracket clears the gate, the overlay stands aside.

Monotone properties (verified by the backtest):

- aligned size is non-decreasing in `strength`
- opposed size is non-increasing in `strength`
- opposition at or above 0.8 always stands aside
- no significant backtested edge -> never deploy

## Gate 2 · drawdown room (killswitch)

Mirrors the on-chain RiskGovernor. With `internal_cap = 0.7 * jury_cap`:

```
R = max(0, internal_cap - current_drawdown)
```

`R` is fed as the budget room to the Risk-Budgeted Allocator, where the per-trade
risk `rho <= DD_BUDGET_K * R`. As `current_drawdown -> internal_cap`, `R -> 0` and
the allowed size collapses to zero. This gate is a hard floor: the regime gate can
scale size DOWN further, but it can never lift size above what `R` permits.

## Composition order

1. TP/SL Optimizer produces the bracket and its edge.
2. Regime gate decides deploy / scale / stand-aside and which bracket.
3. Drawdown gate caps the size via `R`.
4. The resulting `risk_scale` and `R` feed the Risk-Budgeted Allocator for the
   final notional/leverage.

## What this is and is not

- It IS a forward overlay that scales a proven bracket by live conditions and
  enforces a drawdown floor.
- It is NOT a backtested regime model; the historical slice has no stored regime,
  so the regime call's own accuracy is the caller's responsibility (supply it from
  a real regime source such as a CMC fear/greed + rotation read).
