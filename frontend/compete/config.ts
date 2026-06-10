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
  governor:  '0xf679DD2Fe68Bd8e67838efB2740285E491Fa00b2', // RiskGovernor, maxDrawdownBps=1400 (mainnet)
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
    blurb: 'A self driving agent that fuses every MEFAI signal into one conviction score · sizes with a drawdown budget that cannot be breached · and proves each trade before it happens.',
  },
  {
    id: 'skills', path: '/compete/skills', tone: '#3861FB',
    title: 'CMC Strategy Skills',
    blurb: 'Backtested allocation · TP and SL optimization · narrative rotation · regime governing, all powered by 181k labeled outcomes and the full CoinMarketCap Agent Hub.',
  },
  {
    id: 'protocol', path: '/compete/protocol', tone: '#3375BB',
    title: 'Verifiable Protocol',
    blurb: 'A commit reveal prediction registry · a chain anchored drawdown circuit breaker · a unified verifiable intelligence index · and an x402 machine payable feed.',
  },
]
