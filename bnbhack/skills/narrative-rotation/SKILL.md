---
name: narrative-rotation
description: Select which crypto assets to rotate into based on verified outcome rankings and live market narrative. Ranks symbols by their realized expectancy / skill from labeled outcome history, then optionally tilts the shortlist with live CoinMarketCap narrative and momentum signals. Use when the user asks which coins to focus on, wants a rotation watchlist, asks to rank assets by proven edge, or wants narrative-aware asset selection rather than a single fixed pair.
license: MIT
metadata:
  version: "1.0.0"
  category: trading-strategy
  spec: skill.json
---

# Narrative Rotation

Choose the asset shortlist to trade by combining a verified expectancy ranking
with the live market narrative, instead of trading one fixed pair.

## When to reach for this

- "Which symbols should the agent rotate into this week?"
- "Rank assets by proven edge, then bias toward what is trending."
- "Build a rotation watchlist that updates as outcomes resolve."

## Two layers

1. Verified ranking (always available): symbols ranked by realized
   expectancy / win-rate / directional skill over the labeled outcome record.
   This is the trustworthy backbone and is fully deterministic.
2. Narrative tilt (optional): a live CoinMarketCap overlay (trending,
   gainers/losers, fear/greed regime) that reweights the verified shortlist
   toward what the market is paying attention to right now.

See [references/methodology.md](references/methodology.md) for the blend.

## Run it

Wraps two audited modules:
`bnbhack/agent/leaderboard.py` (verified ranking) and,
optionally, `bnbhack/agent/cmc_mcp.py` (live narrative).
Read-only.

```python
import sys
sys.path.insert(0, "bnbhack/agent")
from leaderboard import build_leaderboard

lb = build_leaderboard(group_by="symbol", rank_by="expectancy",
                       min_samples=50, horizon="24h")
top = lb.entries[:8]
for e in top:
    print(e.key, round(e.expectancy, 3), round(e.win_rate, 3),
          e.n_resolved)
```

To add the live narrative tilt, call the CMC client `trending_narratives()` for
attention and `global_metrics_latest()` / `derivatives_metrics()` for the risk
regime, map each symbol to a momentum/attention score in [0,1], and multiply it
into the verified rank. The tilt can only reweight an already verified-qualified
symbol; it can never introduce one that lacks a verified edge.

Inputs: `group_by="symbol"`, `rank_by` (expectancy/pnl/win_rate/skill),
`min_samples`, `horizon`, optional `since_ts` for the live forward window.

Outputs: a ranked `entries` list of `EntityStats` (expectancy, win_rate, skill,
realized_pnl, drawdown, sample counts) plus the global `overall` baseline.

## Live forward proof

Pass `since_ts` = submission-lock time to rank symbols on only the outcomes that
resolved during the judged window, so the rotation reflects current, not stale,
edge.

## Backtest / verify

```bash
python3 bnbhack/skills/narrative-rotation/backtest/backtest.py
```

Splits the labeled record by time: it ranks symbols on a TRAIN window, picks the
top-N and bottom-N there, then measures those baskets' realized expectancy on a
disjoint TEST holdout. Because selection never sees the window it is scored on,
a top basket that still beats both the test baseline and the bottom basket is
genuine out-of-sample signal, not the tautology of ranking and scoring on the
same record. The naive in-sample numbers are reported alongside, clearly labeled.

The CMC Agent Hub tools declared in `skill.json` (`trending_crypto_narratives`,
`get_crypto_quotes_latest`, `get_global_metrics_latest`) are `usage: live-only`:
the narrative tilt fetches them only in live mode. The deterministic backtest
above never makes a network call, so a no-key judge reproduces identical hashes.

## Limitations

- Selection is on the same labeled record it ranks, so an in-sample top set can
  overstate forward edge. The `min_samples` floor, the global baseline comparison,
  and the `since_ts` forward window are the guards. Walk-forward before trusting.
- The narrative tilt is advisory and live-fetched; if the CMC feed is
  unavailable the skill falls back to the verified ranking alone.
- Ranking by raw realized PnL favors high-sample symbols; prefer `expectancy` or
  `skill` for a size-neutral comparison.
