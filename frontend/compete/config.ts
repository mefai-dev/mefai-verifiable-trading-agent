/* Static facts for the BNB HACK presentation. Contract / wallet addresses are
   the project's verified BSC deployments: the result ledger and ERC-8004 identity
   on BSC mainnet, the commit reveal registry, RiskGovernor and keeper on BSC
   testnet for the judged window. Edit GITHUB_URL / DOCS links in one place. */

// Open-source repository. Update to the exact public repo before submission.
export const GITHUB_URL = 'https://github.com/mefai-dev'
export const TERMINAL_URL = 'https://mefai.io'
// The live ERC-8004 registration-v1 document the agent's identity points its
// agentURI at. Serving it from the same origin keeps the minted identity and the
// served card from drifting, so it doubles as the agent's public registration.
export const AGENT_CARD_URL = 'https://mefai.io/bnbhack-api/agent-card'
export const COMPETITION = 'BNB HACK: AI Trading Agent Edition'

/* Verified BSC deployments + identities. The result ledger and the ERC-8004
   identity live on BSC mainnet (chain 56). The live judged commit reveal
   registry, the RiskGovernor and its equity keeper run on BSC testnet (chain 97)
   for the contest window, matching the agent's chain writer (it spends only
   testnet gas there, so the judged record stays un backfillable). */
export const ADDR = {
  registry:  '0x48E9Dcb1f0F12367041Bbe5f2FE1f66D0D830558', // CommitRevealPredictionRegistry (testnet)
  governor:  '0xf751366159446894D6fce783A9eB1bd5B6df25Be', // RiskGovernor, maxDrawdownBps=1400 (testnet)
  agent:     '0xD5df700Ed5355f0c778159592a072B8773faE1CC', // agent wallet (holds the mainnet identity)
  keeper:    '0x064Af3880d562720963bba400B51F95d45AF91d3', // oracle/keeper, feeds the governor (testnet)
  ledger:    '0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744', // result ledger (mainnet)
  erc8004:   '0x8004A169FB4a3325136EB29fA0ceB6D2e539a432', // ERC-8004 Identity Registry (mainnet)
}
export const AGENT_ID = '0x7069f5fdcd64bcfa682ebd4d6654229c39b40753dc81f609fb6e9c34c4a246d4'

/* Which chain each address is meaningfully active on, so the explorer link and
   the chain label never claim mainnet for a testnet deployment. */
const TESTNET_ADDR = new Set<string>([
  ADDR.registry.toLowerCase(),
  ADDR.governor.toLowerCase(),
  ADDR.keeper.toLowerCase(),
])
export const chainOf = (addr: string): 56 | 97 =>
  TESTNET_ADDR.has(addr.toLowerCase()) ? 97 : 56
export const chainLabel = (addr: string): string =>
  chainOf(addr) === 97 ? 'BSC testnet' : 'BSC mainnet'
export const scan = (addr: string) =>
  `https://${chainOf(addr) === 97 ? 'testnet.bscscan.com' : 'bscscan.com'}/address/${addr}`

/* Sponsor / technology stack. Real brand marks (served from /stack) where one
   exists; the two protocol standards (ERC-8004, x402) fall back to our own
   custom SVG marks since they have no brand image. */
export const SPONSORS: { name: string; tone: string; img?: string }[] = [
  { name: 'BNB Chain', tone: '#F0B90B', img: '/stack/bnb.png' },
  { name: 'Trust Wallet', tone: '#3375BB', img: '/stack/trust.png?v=2' },
  { name: 'CoinMarketCap', tone: '#3861FB', img: '/stack/cmc.png' },
  { name: 'PancakeSwap', tone: '#23C7C7', img: '/stack/pancake.png' },
  { name: 'ERC-8004', tone: '#A78BFA' },
  { name: 'x402', tone: '#16C784' },
  { name: 'Binance Data', tone: '#FCD535', img: '/stack/bnb.png' },
  { name: 'BscScan', tone: '#F0B90B', img: '/stack/bnb.png' },
]

export const TRACKS = [
  {
    id: 'agent', path: '/compete/agent', tone: '#F0B90B',
    title: 'Autonomous Trading Agent',
    blurb: 'A self driving agent that fuses every MEFAI signal into one conviction score sizes with a drawdown budget that cannot be breached and proves each trade before it happens.',
  },
  {
    id: 'skills', path: '/compete/skills', tone: '#3861FB',
    title: 'CMC Strategy Skills',
    blurb: 'Backtested allocation TP and SL optimization narrative rotation and regime governing all powered by 181k labeled outcomes and the full CoinMarketCap Agent Hub.',
  },
  {
    id: 'protocol', path: '/compete/protocol', tone: '#3375BB',
    title: 'Verifiable Protocol',
    blurb: 'A commit reveal prediction registry plus a chain anchored drawdown circuit breaker a unified verifiable intelligence index and an x402 machine payable feed.',
  },
]
