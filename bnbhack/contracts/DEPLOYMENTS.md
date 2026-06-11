# Verified deployments

The verifiable layer is live on **BSC mainnet** (chain 56). The result ledger,
the agent's ERC-8004 identity, the commit-reveal registry, the RiskGovernor and
its equity keeper all sit on mainnet, matching the agent's chain writer, which
is pinned to chain 56 in production.

Every address below is a real deployment a reviewer can open and read. None of
them require trust: the registry's commitments and reveals, the governor's
equity records and halts, and the ledger's results are all public reads.

## BSC mainnet · chain 56

| Contract | Address | Explorer |
| --- | --- | --- |
| Result ledger | `0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744` | https://bscscan.com/address/0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744 |
| ERC-8004 Identity Registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` | https://bscscan.com/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432 |
| CommitRevealPredictionRegistry | `0xcA9499a2d20cFAa98f9Bc3b2F1386A70f51c2FEB` | https://bscscan.com/address/0xcA9499a2d20cFAa98f9Bc3b2F1386A70f51c2FEB#code |
| RiskGovernor · `maxDrawdownBps=1400` | `0xFACBc0a9b5a7dd34BfD0B91e1102dF4E72b9e43f` | https://bscscan.com/address/0xFACBc0a9b5a7dd34BfD0B91e1102dF4E72b9e43f#code |
| Equity keeper · feeds the governor | `0x064Af3880d562720963bba400B51F95d45AF91d3` | https://bscscan.com/address/0x064Af3880d562720963bba400B51F95d45AF91d3 |
| Agent wallet (holds the identity, authors commits) | `0xD5df700Ed5355f0c778159592a072B8773faE1CC` | https://bscscan.com/address/0xD5df700Ed5355f0c778159592a072B8773faE1CC |

Two distinct identifiers are in play; do not conflate them:

- **ERC-8004 token id (agentId): `131181`** · the numeric NFT id minted to the
  agent wallet in the ERC-8004 Identity Registry above.
- **Commit-reveal / Arena agentId:
  `0x7069f5fdcd64bcfa682ebd4d6654229c39b40753dc81f609fb6e9c34c4a246d4`** · the
  keccak256 of the agent name packed with its wallet, used by the
  CommitRevealPredictionRegistry / Arena. This is not the ERC-8004 token id.

## Build, test and deploy from source

```bash
cd bnbhack/contracts
npm install          # hardhat + toolbox, pinned in package.json
npm run build        # solc 0.8.24, optimizer on (runs=200)
npm test             # 15 tests across the registry and the governor

# A real deploy needs a funded key and is never run by default. The agent
# stays in paper mode; chain writes are gated behind their own env flag.
# deploy:testnet is the safe default (BSC testnet, free faucet funds).
DEPLOYER_PRIVATE_KEY=0x... npm run deploy:testnet
```

The live addresses listed above were deployed with `npm run deploy:mainnet`
(chain 56), which needs a funded mainnet key:

```bash
DEPLOYER_PRIVATE_KEY=0x... npm run deploy:mainnet   # requires a funded mainnet key
```

`npm test` runs entirely on the in-process Hardhat network and needs no key, no
RPC and no funds. The two BSC networks in `hardhat.config.ts` only activate for a
real deploy, when `DEPLOYER_PRIVATE_KEY` is present in the environment.
