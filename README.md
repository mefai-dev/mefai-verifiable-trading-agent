# MEFAI · The Verifiable Trading Agent

> An autonomous on-chain trading agent that proves every call **before** the
> outcome is known, sizes each position against a drawdown budget it cannot
> breach, and writes its entire record to a public ledger. Built for the
> **BNB HACK · AI Trading Agent Edition**.

A trading track record is normally something you have to *believe*. A screenshot,
a Telegram message, a curve that could have been drawn after the fact. MEFAI
takes the opposite stance: the agent **commits to a sealed prediction on-chain
before the move happens**, reveals it after, and anchors its equity to a contract
that halts trading the moment a drawdown limit is crossed. The result is a record
a stranger can audit instead of one they must trust.

---

## What it does

MEFAI fuses many independent market signals into a single conviction score,
sizes a position with a drawdown-budgeted fractional-Kelly engine, clears every
spend through a security gate, and publishes a verifiable proof for each
decision. It runs three things at once:

| Pillar | What it is |
| --- | --- |
| **Autonomous Trading Agent** | A self-driving decision loop that turns market data into one conviction, sizes it under a hard drawdown cap, and seals each trade as a commit-reveal proof. |
| **CMC Strategy Skills** | Five backtested strategy skills (allocation, TP/SL optimization, narrative rotation, regime governing, meta-composition) powered by 181k labeled outcomes and the CoinMarketCap Agent Hub. |
| **Verifiable Protocol** | A commit-reveal prediction registry, a chain-anchored drawdown circuit breaker, a unified intelligence index, and an x402 machine-payable signal feed. |

### Ships in paper mode by default

The agent decides, gates, sizes, plans and publishes its live state but
**signs nothing** until you explicitly opt in. Going live is gated behind two
separate environment flags (`BNBHACK_EXECUTE_TRADES` for spot,
`BNBHACK_EXECUTE_CHAIN` for verifiable writes), and each still requires its own
key to be present. You can run the full pipeline end to end without ever
touching a private key.

---

## How a decision is made

```
market data ─▶ signal fusion ─▶ expert council ─▶ net-of-cost edge gate
                                                          │
                       drawdown-budgeted Kelly sizing ◀───┘
                                  │
                       security gate (6 checks) ─▶ commit-reveal proof ─▶ trade
```

1. **Signal fusion** blends every source (CoinMarketCap regime, the MEFAI signal
   feed, a machine-learning ensemble, a technical composite) into one direction
   and conviction.
2. **The expert council** has six agents debate the same asset from different
   lenses and resolve to a consensus with a measured agreement level.
3. **The net-of-cost edge gate** only sizes a trade when the cell's *measured*
   expectancy clears the full round-trip cost beyond its own error bar. It would
   rather skip a marginal trade than bleed fees on a coin flip.
4. **Drawdown-budgeted sizing** fits real win rates and payoffs from labeled
   history and never lets exposure breach the equity floor.
5. **The security gate** runs six go / no-go checks on the exact spend before
   anything is signed.
6. **The commit-reveal proof** seals the prediction on-chain before the move, so
   the record cannot be backfilled.

The engine is **direction-aware**: a long is expressed directly on a DEX; a short
is simulated honestly in the paper book and routes through a perpetual venue
behind the execute flag when live, so the book earns in falling weeks as well as
rising ones.

---

## Repository layout

```
bnbhack/
  agent/          The autonomous loop and its engine
    loop.py             decision + commit-reveal + lifecycle driver
    fusion_core.py      signal fusion into one conviction
    fusion_providers.py per-source readers (signals, ML, technical, CMC)
    sizing.py           drawdown-budgeted fractional-Kelly + edge gate
    position_manager.py direction-aware position lifecycle (entries, TP/SL, trail)
    tp_sl_optimizer.py  empirical TP/SL brackets from labeled outcomes
    leaderboard.py      per-source realized-expectancy ranking
    chain_writer.py     commit-reveal + equity anchoring with RPC failover
    bsc_exec.py         DEX execution adapter and spend caps
    tx_security_solver.py the pre-spend security gate
    agent_card.py       ERC-8004 agent identity document
    erc8004_identity.py identity registration helpers
    cmc_mcp.py          CoinMarketCap Agent Hub client
    x402_feed.py        HTTP 402 machine-payable signal feed
  api/
    backend.py          FastAPI service exposing the live cockpit + skills
  skills/           Five CMC strategy skills, each with its own backtest
    risk-budgeted-allocator/
    empirical-tp-sl-optimizer/
    narrative-rotation/
    regime-risk-governor/
    meta-strategy-composer/
  contracts/        Solidity for the verifiable layer
    src/CommitRevealPredictionRegistry.sol
    src/RiskGovernor.sol
frontend/
  compete/          The jury-facing presentation sub-site (React + TypeScript)
```

---

## Quickstart

```bash
# 1. Install dependencies and configure
pip install -r requirements.txt
cp .env.example .env      # fill in your own values; defaults run in paper mode

# 2. Generate a synthetic sample book so the engine has data to fit
#    (the production book of labeled outcomes is private and gitignored).
#    Point every component at it with one env var (default is data/signal.db).
python3 bnbhack/data/make_sample_db.py
export MEFAI_SIGNAL_DB="$PWD/bnbhack/data/signal.db"

# 3. Verify the engine: drawdown-budget guarantee + direction-aware PnL
python3 -m unittest discover -s bnbhack/tests

# 4. Run one cycle of the autonomous loop (paper mode, signs nothing)
python3 bnbhack/agent/loop.py --once

# 5. Serve the live cockpit API
python3 -m uvicorn backend:app --app-dir bnbhack/api --host 127.0.0.1 --port 8401

# 6. Run a strategy-skill walk-forward backtest
python3 bnbhack/skills/risk-budgeted-allocator/backtest/walk_forward.py

# 7. Build and test the verifiable layer (needs no key, no RPC, no funds)
cd bnbhack/contracts && npm install && npm test   # 15 tests, all green
```

The backtests are out-of-sample walk-forward simulations: each cell learns its
edge from a training window and is tested on a later window it never saw, with
equity compounded net of cost under the same drawdown budget the live engine
uses.

### A note on the data and the frontend

- **The labeled-outcome book is private.** The 181k resolved outcomes are real
  account data, excluded by `.gitignore`. `bnbhack/data/` ships the exact table
  schema and a seeded, clearly-synthetic sample generator so anyone can run the
  full pipeline locally without it. See `bnbhack/data/README.md`.
- **`frontend/compete/` is an excerpt, not a standalone app.** It is the
  jury-facing presentation that lives inside the larger MEFAI terminal, included
  here as source for review. It reads from the cockpit API in step 5 and is not
  meant to be built in isolation.

---

## The edge

The strategy is grounded on a base of **181k labeled outcomes across forty
assets**. Every signal the agent reads has been resolved against what the market
actually did, which is what lets the sizing engine fit real win rates and payoffs
rather than guesses, and what lets the leaderboard rank each source by realized
expectancy. A win rate near fifty percent is not weak when the reward-to-risk
ratio carries positive expectancy.

---

## The sponsor stack

- **BNB Chain** · the settlement and proof layer. PancakeSwap and a perpetual
  venue for execution; the registry, governor, ledger and identity for verification.
- **CoinMarketCap Agent Hub** · twelve MCP tools that gate global metrics,
  derivatives, narratives, market cap, technicals and macro events into the
  regime read.
- **Trust Wallet Agent Kit** · execution and self-custody safety. The approval
  guard and the security solver run from this kit.
- **ERC-8004** · the agent's portable on-chain identity.
- **x402** · the machine-payable feed standard that lets agents pay agents for
  proven alpha with no human in the loop.

---

## Security

MEFAI can move money, so it is built to fail safe. It signs nothing until two
separate flags are set, clears every spend through a fail-closed security gate,
talks only to a loopback proxy and an allowlisted set of RPC hosts, and anchors
its equity to a contract that halts trading when a drawdown budget is breached.
The full posture, threat model and disclosure process are in
[`SECURITY.md`](SECURITY.md). Verified contract addresses are in
[`bnbhack/contracts/DEPLOYMENTS.md`](bnbhack/contracts/DEPLOYMENTS.md).

---

## License

Released under the MIT License. See `LICENSE`.
