# Verified deployments

The verifiable layer is live on BNB Chain. The result ledger and the agent's
ERC-8004 identity sit on **BSC mainnet** (chain 56). The commit-reveal registry,
the RiskGovernor and its equity keeper run on **BSC testnet** (chain 97) for the
contest window, matching the agent's chain writer, which spends only test value
while the agent trades in paper mode by default.

Every address below is a real deployment a reviewer can open and read. None of
them require trust: the registry's commitments and reveals, the governor's
equity records and halts, and the ledger's results are all public reads.

## BSC mainnet · chain 56

| Contract | Address | Explorer |
| --- | --- | --- |
| Result ledger | `0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744` | https://bscscan.com/address/0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744 |
| ERC-8004 Identity Registry | `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` | https://bscscan.com/address/0x8004A169FB4a3325136EB29fA0ceB6D2e539a432 |
| Agent wallet (holds the identity) | `0xD5df700Ed5355f0c778159592a072B8773faE1CC` | https://bscscan.com/address/0xD5df700Ed5355f0c778159592a072B8773faE1CC |

## BSC testnet · chain 97

| Contract | Address | Explorer |
| --- | --- | --- |
| CommitRevealPredictionRegistry | `0x48E9Dcb1f0F12367041Bbe5f2FE1f66D0D830558` | https://testnet.bscscan.com/address/0x48E9Dcb1f0F12367041Bbe5f2FE1f66D0D830558 |
| RiskGovernor · `maxDrawdownBps=1400` | `0xf751366159446894D6fce783A9eB1bd5B6df25Be` | https://testnet.bscscan.com/address/0xf751366159446894D6fce783A9eB1bd5B6df25Be |
| Equity keeper · feeds the governor | `0x064Af3880d562720963bba400B51F95d45AF91d3` | https://testnet.bscscan.com/address/0x064Af3880d562720963bba400B51F95d45AF91d3 |

The agent's identity id (keccak256 of the agent name packed with its wallet) is
`0x7069f5fdcd64bcfa682ebd4d6654229c39b40753dc81f609fb6e9c34c4a246d4`.

## Build, test and deploy from source

```bash
cd bnbhack/contracts
npm install          # hardhat + toolbox, pinned in package.json
npm run build        # solc 0.8.24, optimizer on (runs=200)
npm test             # 15 tests across the registry and the governor

# A real deploy needs a funded key and is never run by default. The agent
# stays in paper mode; chain writes are gated behind their own env flag.
DEPLOYER_PRIVATE_KEY=0x... npm run deploy:testnet
```

`npm test` runs entirely on the in-process Hardhat network and needs no key, no
RPC and no funds. The two BSC networks in `hardhat.config.ts` only activate for a
real deploy, when `DEPLOYER_PRIVATE_KEY` is present in the environment.
