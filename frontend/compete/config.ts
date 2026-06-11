/* Static facts for the BNB HACK presentation. Contract / wallet addresses are
   the project's verified BSC deployments: the result ledger, the ERC-8004 identity,
   the commit reveal registry, the RiskGovernor and its keeper all on BSC mainnet.
   Edit GITHUB_URL / DOCS links in one place. */

// Open-source repository. Update to the exact public repo before submission.
export const GITHUB_URL = 'https://github.com/mefai-dev/mefai-verifiable-trading-agent'
export const TERMINAL_URL = 'https://mefai.io'
// The live ERC-8004 registration-v1 document the agent's identity points its
// agentURI at. Serving it from the same origin keeps the minted identity and the
// served card from drifting, so it doubles as the agent's public registration.
export const AGENT_CARD_URL = 'https://mefai.io/bnbhack-api/agent-card'
export const COMPETITION = 'BNB HACK: AI Trading Agent Edition'
// Per-user Telegram bot subscription for the agent's trade feed. A judge starts
// @mefainews_bot and it sends them a direct message for every trade leg during
// the judged window (read only · a BscScan link per leg · no keys, no commands).
export const TELEGRAM_FEED_URL = 'https://t.me/mefainews_bot?start=agentfeed'

/* Verified BSC deployments + identities, all live on BSC mainnet (chain 56):
   the result ledger, the ERC-8004 identity, the commit reveal registry, the
   RiskGovernor and its equity keeper. This matches the agent's chain writer,
   which is pinned to chain 56 in production, so the judged record is anchored to
   mainnet and stays un backfillable. */
export const ADDR = {
  registry:  '0xcA9499a2d20cFAa98f9Bc3b2F1386A70f51c2FEB', // CommitRevealPredictionRegistry (mainnet)
  governor:  '0xFACBc0a9b5a7dd34BfD0B91e1102dF4E72b9e43f', // RiskGovernor, maxDrawdownBps=1400 (mainnet)
  agent:     '0xD5df700Ed5355f0c778159592a072B8773faE1CC', // agent wallet (holds the mainnet identity)
  keeper:    '0x064Af3880d562720963bba400B51F95d45AF91d3', // oracle/keeper, feeds the governor (mainnet)
  ledger:    '0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744', // result ledger (mainnet)
  erc8004:   '0x8004A169FB4a3325136EB29fA0ceB6D2e539a432', // ERC-8004 Identity Registry (mainnet)
}
// The internal commit id: the keccak identity seed the commit reveal registry
// binds predictions under. This is NOT the ERC-8004 token id (see below).
export const AGENT_ID = '0x7069f5fdcd64bcfa682ebd4d6654229c39b40753dc81f609fb6e9c34c4a246d4'
// The minted ERC-8004 identity token id, an integer, live on chain 56 and
// returned by /agent/identity as registry.agent_id. Prefer reading it live.
export const ERC8004_AGENT_ID = '131181'

/* Normalize a commit/reveal tx field to a bare hash. The backend now serves
   commit_tx / reveal_tx as full BscScan URLs (https://bscscan.com/tx/0x..),
   so strip any explorer prefix before building a link or shortening it. */
export const txHashOf = (v?: string): string =>
  !v ? '' : (v.includes('/tx/') ? v.split('/tx/').pop()! : v)

/* Every contract above is on BSC mainnet (chain 56), so the explorer link and
   the chain label always resolve to mainnet. chainOf is intentionally pinned to
   chain 56 for the judged window; the 97 (testnet) branch in chainLabel / scan
   below is a deliberate fallback kept for when this helper points back at a
   testnet deployment, not dead code to remove. */
export const chainOf = (_addr: string): 56 | 97 => 56
export const chainLabel = (addr: string): string =>
  chainOf(addr) === 97 ? 'BSC testnet' : 'BSC mainnet'
export const scan = (addr: string) =>
  `https://${chainOf(addr) === 97 ? 'testnet.bscscan.com' : 'bscscan.com'}/address/${addr}`

/* Sponsor / technology stack. Real brand marks (served from /stack) where one
   exists; the two protocol standards (ERC-8004, x402) fall back to our own
   custom SVG marks since they have no brand image. */
export const SPONSORS: { name: string; tone: string; img?: string; url: string }[] = [
  { name: 'BNB Chain', tone: '#F0B90B', img: '/stack/bnb.png', url: 'https://www.bnbchain.org' },
  { name: 'Trust Wallet', tone: '#3375BB', img: '/stack/trust.png?v=2', url: 'https://trustwallet.com' },
  { name: 'CoinMarketCap', tone: '#3861FB', img: '/stack/cmc.png', url: 'https://coinmarketcap.com' },
  { name: 'PancakeSwap', tone: '#23C7C7', img: '/stack/pancake.png', url: 'https://pancakeswap.finance' },
  { name: 'ERC-8004', tone: '#A78BFA', url: 'https://eips.ethereum.org/EIPS/eip-8004' },
  { name: 'x402', tone: '#16C784', url: 'https://www.x402.org' },
  { name: 'Binance Data', tone: '#FCD535', img: '/stack/bnb.png', url: 'https://www.binance.com' },
  { name: 'BscScan', tone: '#F0B90B', img: '/stack/bnb.png', url: 'https://bscscan.com' },
]

export const TRACKS = [
  {
    id: 'agent', path: '/compete/agent', tone: '#F0B90B',
    title: 'Autonomous Trading Agent',
    blurb: 'A self driving agent that fuses every MEFAI signal into one conviction score · sizes with a drawdown budget that cannot be breached · and proves each trade before it happens.',
  },
  {
    id: 'skills', path: '/compete/skills', tone: '#3861FB',
    title: 'CMC Strategy Skills',
    blurb: 'Backtested allocation · TP and SL optimization · narrative rotation · regime governing, all powered by 195k labeled outcomes and the full CoinMarketCap Agent Hub.',
  },
  {
    id: 'protocol', path: '/compete/protocol', tone: '#3375BB',
    title: 'Verifiable Protocol',
    blurb: 'A commit reveal prediction registry · a chain anchored drawdown circuit breaker · a unified verifiable intelligence index · and an x402 machine payable feed.',
  },
]

// Verifiable dataset commitment: the private production outcome base is sealed by
// its Merkle root on BSC mainnet (scripts/seal_dataset.py over signal_performance
// in id order). A juror reproduces the algorithm on the public sample, and under
// NDA/escrow reproduces the exact sealed root on the private DB byte for byte.
export const DATASET_SEAL = {
  txHash: '0xc3501e1e40954a8b4ca8da36a1018c7d32016e5aa823e63cdc02a5794a9917bc',
  merkleRoot: '0x42ce0ec21ca92a98f5b3a696a417255ee1adb739f240b3649abb6b736de183d5',
  sampleRoot: '0x36eac52e8e21e2d25eb600b186f22cad865c3e551a935904b95c87ffb9bb309b',
  rows: 198248, resolved: 195868, symbols: 42,
}
