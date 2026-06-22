# Operations and honesty notes

This file records, in plain words, how the live agent is operated during the
judged window and what we do and do not claim. The wedge of this project is that
you do not have to trust us, so the operating choices are written down here as
openly as the on chain proofs.

## What the equity number means

The agent equity shown in the cockpit and fed to the RiskGovernor is the live
mark to market value of the real agent wallet, not a paper number. That choice is
deliberate: the judged drawdown must come from the real wallet, not a private
ledger we could massage.

A direct consequence: if the wallet holds a volatile asset it is not actively
trading (for example a large idle BNB or ETH balance), the equity rises and falls
with that asset price even on days the agent makes no trade. That is market
exposure, not a trading result. To keep the judged drawdown a clean reflection of
the agent's own decisions, the operator holds the wallet primarily in USDT and
keeps only a small BNB balance for gas. The agent then risks a small fixed size
per trade, so the equity curve tracks the trading, not the market value of idle
coins.

## Risk controls (enforced, not promised)

- Every spot leg is capped to a small fixed notional. A single trade cannot move
  the book materially.
- Stops are protective from entry. Once a position is up by a set amount the stop
  ratchets up behind the running high, so a winner is not handed back to a loss.
- The RiskGovernor contract enforces a drawdown cap. If realised drawdown reaches
  the cap the governor blocks new entries before the jury line is ever reached.
- A minimal daily compliance trade keeps the wallet at one trade per day so a quiet
  market never forfeits the day. It is sized minimally and flagged as a floor trade,
  separate from conviction trades.

## Liquidity discipline

Some assets are listed on the venue but route through a thin pool. A small buy can
fill while the matching sell trips the slippage guard, which would leave a position
that cannot be exited cleanly. When we observe that on an asset we remove it from
the traded set rather than route real size into a pool we cannot exit. The security
gate refusing a high slippage exit is the gate working, not a bug.

## What we do not claim

We do not claim a proven profit edge. An honest out of sample walk forward of the
signal set does not show a net of cost edge we could stand behind, and we say so on
the product pages too. The case this project makes is narrower and verifiable:
disciplined sizing, a drawdown that is structurally capped, and a record a stranger
can audit on chain rather than a screenshot they must believe. Placement should
rest on that, not on a profit claim.
