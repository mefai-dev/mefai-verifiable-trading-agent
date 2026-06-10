---
name: risk-budgeted-allocator
description: Size a crypto trade so it cannot breach a drawdown budget. Turns a (symbol, timeframe, equity, current drawdown) decision into a position notional, leverage and margin using drawdown-budget fractional-Kelly sizing driven by 181k labeled MEFAI signal outcomes. Use when the user needs position sizing, leverage selection, risk-budget allocation, or wants to know how large a trade may be without risking disqualification on a max-drawdown rule.
license: MIT
metadata:
  version: "1.0.0"
  category: trading-strategy
  spec: skill.json
---

# Risk-Budgeted Allocator

Convert a trade decision into a position size that, by construction, cannot push
peak-to-trough drawdown past a budget, while sizing each bet by its EMPIRICAL
edge rather than a guessed win rate.

## When to reach for this

- "How large should I go on BTCUSDT 1h with 10k equity and 4% current drawdown?"
- "What leverage keeps me inside a 20% max-drawdown DQ cap?"
- "Size every open signal so the book stays inside its risk budget."

## Model in one line

`worst_case_loss = notional * stop_distance <= DD_BUDGET_K * R * equity`, where
`R = 0.7*jury_cap - current_drawdown`. As `R -> 0` the size shrinks to zero, so
the allocator physically cannot trade past the cap. See
[references/methodology.md](references/methodology.md) for the full derivation.

## Run it

The skill wraps the audited module at
`bnbhack/agent/sizing.py`. It is read-only: it reads the
labeled outcome store and never trades, signs, or writes.

```python
import sys
sys.path.insert(0, "bnbhack/agent")
from sizing import SizingInput, size_position

r = size_position(SizingInput(
    symbol="BTCUSDT", timeframe="1h", equity=10_000.0,
    current_drawdown=0.04,        # 4% peak-to-trough so far
    jury_cap=0.20,                # max-drawdown DQ threshold
    regime_gate=1.0,              # 0..1 from a regime skill, 0 = stand aside
    conviction=1.0,               # 0..1 from a fusion/selection skill
))
print(r.approved, r.leverage, r.notional, r.worst_case_loss)
for line in r.reasons:
    print(" ", line)
```

Key inputs (all clamped at the boundary): `equity`, `current_drawdown`,
`jury_cap`, `stop_distance` (omit to use the empirical adverse-excursion stop),
`regime_gate`, `conviction`, `venue_max_leverage`, `horizon` (1h/4h/24h).

Key outputs: `approved`, `notional`, `leverage`, `margin`, `worst_case_loss`,
`risk_budget_rho`, `drawdown_room_R`, `win_rate`, `payoff`, `full_kelly`, and a
`reasons` transcript that explains every number for an audit panel.

## Backtest / verify

Two layers, both pinned inside the same reproducible hash-guard
(`bnbhack/skills/BACKTEST_REPORTS.json`):

1. **Invariant check** (`backtest/backtest.py`) proves the budget invariant
   across an equity x drawdown grid for several symbols and shows size collapsing
   to zero as drawdown approaches the cap.
2. **Walk-forward out-of-sample equity** (`backtest/walk_forward.py`) is the
   headline edge: it splits the labeled outcomes by time, estimates each bucket's
   edge on the train window only, then walks the held-out test window forward
   sizing with the same drawdown-budget fractional-Kelly model (train-window edge
   estimates, no shrinkage applied in the backtest). It reports max drawdown and
   net-of-cost return
   for the risk engine against a naive flat-leverage floor, so the value of the
   drawdown budget is explicit and falsifiable.

```bash
# invariant check
python3 bnbhack/skills/risk-budgeted-allocator/backtest/backtest.py
# walk-forward equity engine (writes output/equity_report.json + equity_curve.svg)
python3 bnbhack/skills/risk-budgeted-allocator/backtest/walk_forward.py
# both at once, fingerprinted into BACKTEST_REPORTS.json:
python3 bnbhack/skills/run_backtests.py risk-budgeted-allocator
```

The shipped `output/equity_report.json` runs on the **public synthetic sample
DB** (illustrative, reproducible from `bnbhack/data/make_sample_db.py`); its
figures demonstrate the engine's mechanics, not a live track record. Spans below
half a year report window metrics (return over max drawdown), not annualised
CAGR, so no displayed number is an annualisation artefact.

## Limitations

- Edge is estimated from past labeled outcomes; thin (symbol, timeframe) buckets
  are shrunk toward a global prior and flagged `shrunk`, but a regime break can
  still move the true win rate away from history.
- `current_drawdown` and `equity` are caller-supplied; the allocator trusts them.
  Wire them to a live equity feed or the on-chain RiskGovernor for an enforced,
  not advisory, cap.
- Leverage capping at the venue maximum only ever lowers realized risk; it never
  raises the budget.
