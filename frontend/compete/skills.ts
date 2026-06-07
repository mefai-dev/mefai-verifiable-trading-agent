/* BNB HACK · the full sponsor skill catalog.
   Every capability MEFAI builds on, one typed record each, grouped by sponsor.
   CMC = the CoinMarketCap Agent Hub (12 MCP tools + 8 skills), Trust = the Trust
   Wallet Agent Kit (3 skills + the twak command surface), BNB = MEFAI's own
   verifiable capabilities deployed to BNB Chain. `used` marks what the live agent
   actually calls today; `related` wires the cross sponsor flow so the capability
   web can draw CMC data into MEFAI's council, out through Trust execution and down
   to BNB settlement and proof. Visible copy uses the middle dot, never a dash;
   registered identifiers (ERC-8004, x402, EIP-3009, TP/SL) and literal command
   names keep their own spelling. */

export type SkillGroup = 'cmc' | 'trust' | 'bnb'
export type SkillKind = 'mcp-tool' | 'skill' | 'cli' | 'contract' | 'api' | 'sdk' | 'engine'

export type SkillDef = {
  id: string
  name: string
  group: SkillGroup
  kind: SkillKind
  summary: string          // one line, what it is
  what: string             // what MEFAI does with it
  inputs?: string
  outputs?: string
  invoke?: string          // the literal call / command / address
  tags: string[]
  related: string[]        // ids of related skills, cross group encouraged
  used: boolean            // does the live agent call it today
  link?: string
}

export const GROUP_TONE: Record<SkillGroup, string> = {
  cmc: 'var(--cmc)', trust: 'var(--trust)', bnb: 'var(--gold)',
}
export const GROUP_LABEL: Record<SkillGroup, string> = {
  cmc: 'CoinMarketCap', trust: 'Trust Wallet', bnb: 'BNB Chain',
}
export const KIND_LABEL: Record<SkillKind, string> = {
  'mcp-tool': 'MCP tool', skill: 'Skill', cli: 'CLI command',
  contract: 'Contract', api: 'REST API', sdk: 'SDK', engine: 'Engine',
}

const CMC_REPO = 'https://github.com/coinmarketcap-official/skills-for-ai-agents-by-CoinMarketCap'
const TW_REPO = 'https://github.com/trustwallet/tw-agent-skills'

/* ─────────────── CoinMarketCap Agent Hub · 12 MCP tools ─────────────── */
const CMC_TOOLS: SkillDef[] = [
  {
    id: 'cmc-quotes', name: 'get_crypto_quotes_latest', group: 'cmc', kind: 'mcp-tool',
    summary: 'Latest price volume and supply for any asset.',
    what: 'The price spine of the cockpit. Live quotes drive the market read every conviction score and the entry target and stop brackets the agent commits.',
    inputs: 'symbol or id convert currency', outputs: 'price · 24h volume · market cap · supply',
    invoke: 'mcp__cmc__get_crypto_quotes_latest', tags: ['price', 'quote', 'core'],
    related: ['bnb-fusion', 'cmc-metrics', 'cmc-skill-mcp'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-search', name: 'search_cryptos', group: 'cmc', kind: 'mcp-tool',
    summary: 'Resolve a name or ticker to a canonical CMC id.',
    what: 'Disambiguates user and signal symbols before anything else runs so the agent never trades the wrong token behind a shared ticker.',
    inputs: 'free text query', outputs: 'ranked id · symbol · name matches',
    invoke: 'mcp__cmc__search_cryptos', tags: ['search', 'resolve'],
    related: ['cmc-quotes', 'cmc-info'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-info', name: 'get_crypto_info', group: 'cmc', kind: 'mcp-tool',
    summary: 'Project profile category links and contract addresses.',
    what: 'Feeds the asset dossier and the narrative tags. The contract address it returns is handed straight to the Trust safety gate before any spend.',
    inputs: 'symbol or id', outputs: 'description · category · urls · platform contracts',
    invoke: 'mcp__cmc__get_crypto_info', tags: ['fundamentals', 'metadata'],
    related: ['tw-risk', 'cmc-narratives'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-ta', name: 'get_crypto_technical_analysis', group: 'cmc', kind: 'mcp-tool',
    summary: 'Indicator read and signal for a single asset.',
    what: 'A second opinion alongside MEFAI\u2019s own technical agent. Agreement raises conviction divergence shrinks size through the regime governor.',
    inputs: 'symbol or id timeframe', outputs: 'trend · momentum · indicator signal',
    invoke: 'mcp__cmc__get_crypto_technical_analysis', tags: ['technical', 'signal'],
    related: ['bnb-council', 'cmc-mcap-ta'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-mcap-ta', name: 'get_crypto_marketcap_technical_analysis', group: 'cmc', kind: 'mcp-tool',
    summary: 'Technical read on the total market cap series.',
    what: 'Sets the macro backdrop. A weak market cap trend tightens every bracket and biases the regime governor toward defence.',
    inputs: 'timeframe', outputs: 'market cap trend · momentum',
    invoke: 'mcp__cmc__get_crypto_marketcap_technical_analysis', tags: ['regime', 'macro'],
    related: ['cmc-global', 'bnb-fusion'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-metrics', name: 'get_crypto_metrics', group: 'cmc', kind: 'mcp-tool',
    summary: 'Deeper per asset metrics beyond the basic quote.',
    what: 'Liquidity volume quality and supply detail enrich the per token audit so a thin or manipulated book is caught before sizing.',
    inputs: 'symbol or id', outputs: 'extended metric set',
    invoke: 'mcp__cmc__get_crypto_metrics', tags: ['metrics', 'liquidity'],
    related: ['cmc-quotes', 'bnb-sizing'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-global', name: 'get_global_metrics_latest', group: 'cmc', kind: 'mcp-tool',
    summary: 'Total market cap volume and BTC dominance.',
    what: 'The regime governor reads dominance and the aggregate market here then scales the whole book\u2019s risk to the regime it implies.',
    inputs: 'convert currency', outputs: 'total cap · 24h volume · BTC and ETH dominance',
    invoke: 'mcp__cmc__get_global_metrics_latest', tags: ['regime', 'dominance', 'core'],
    related: ['bnb-fusion', 'cmc-mcap-ta'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-deriv', name: 'get_global_crypto_derivatives_metrics', group: 'cmc', kind: 'mcp-tool',
    summary: 'Aggregate open interest and funding.',
    what: 'Crowded positioning is flagged before the agent commits a direction. Stretched funding alone can veto an otherwise strong signal.',
    inputs: 'convert currency', outputs: 'open interest · funding · derivatives volume',
    invoke: 'mcp__cmc__get_global_crypto_derivatives_metrics', tags: ['derivatives', 'funding', 'positioning'],
    related: ['bnb-council', 'cmc-orderflow'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-narratives', name: 'trending_crypto_narratives', group: 'cmc', kind: 'mcp-tool',
    summary: 'Ranked live narratives and their momentum.',
    what: 'The narrative rotation skill ranks these and rotates the book into the strongest but only after the verifiable leaderboard confirms the edge is real.',
    inputs: 'none', outputs: 'ranked narratives · constituents · momentum',
    invoke: 'mcp__cmc__trending_crypto_narratives', tags: ['narrative', 'rotation'],
    related: ['bnb-leaderboard', 'cmc-info'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-macro', name: 'get_upcoming_macro_events', group: 'cmc', kind: 'mcp-tool',
    summary: 'Scheduled macro events and volatility windows.',
    what: 'Sizing is gated around known event windows so the agent never trades blind into a print it could have seen coming.',
    inputs: 'window', outputs: 'event calendar · timestamps · category',
    invoke: 'mcp__cmc__get_upcoming_macro_events', tags: ['macro', 'calendar', 'risk'],
    related: ['bnb-sizing', 'bnb-governor'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-news', name: 'get_crypto_latest_news', group: 'cmc', kind: 'mcp-tool',
    summary: 'Latest headlines for an asset or the market.',
    what: 'Headline flow colours the market intel agent\u2019s read and surfaces event risk the price has not yet absorbed.',
    inputs: 'symbol or id limit', outputs: 'headline · source · timestamp',
    invoke: 'mcp__cmc__get_crypto_latest_news', tags: ['news', 'sentiment'],
    related: ['bnb-council', 'cmc-narratives'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-search-info', name: 'search_crypto_info', group: 'cmc', kind: 'mcp-tool',
    summary: 'Search the project knowledge base by topic.',
    what: 'Powers the research skill\u2019s deeper lookups pulling the right profile and context for a free form question about an asset.',
    inputs: 'free text query', outputs: 'matched project info',
    invoke: 'mcp__cmc__search_crypto_info', tags: ['search', 'research'],
    related: ['cmc-skill-research', 'cmc-info'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-orderflow', name: 'Taker order flow', group: 'cmc', kind: 'engine',
    summary: 'Who is buying and who is selling live.',
    what: 'Aggressive taker buys versus sells read from the live trade tape and the book so the agent sees real pressure behind a quote not just the last price.',
    inputs: 'aggregated trades · order book · L/S ratio', outputs: 'taker buy vs sell pressure',
    tags: ['order-flow', 'pressure', 'live'], related: ['cmc-deriv', 'bnb-fusion'], used: true,
  },
]

/* ─────────────── CoinMarketCap Agent Hub · 8 skills ─────────────── */
const CMC_SKILLS: SkillDef[] = [
  {
    id: 'cmc-skill-mcp', name: 'cmc-mcp', group: 'cmc', kind: 'skill',
    summary: 'The MCP server wrapping all 12 hub tools.',
    what: 'MEFAI implements the full server surface verbatim so the same tool calls a judge runs in an IDE are the ones driving the live agent.',
    inputs: 'mcp.coinmarketcap.com/mcp · X CMC MCP API KEY', outputs: '12 tools over MCP',
    tags: ['mcp', 'server', 'core'], related: ['cmc-quotes', 'cmc-global'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-report', name: 'market-report', group: 'cmc', kind: 'skill',
    summary: 'A structured read of the whole market.',
    what: 'The live market read on this page mirrors the report skill: global metrics verdict chips and the per token audit in the CMC table language.',
    inputs: 'optional focus assets', outputs: 'narrative market report',
    tags: ['report', 'market'], related: ['cmc-global', 'cmc-skill-research'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-research', name: 'crypto-research', group: 'cmc', kind: 'skill',
    summary: 'Deep research on a single asset.',
    what: 'Fuses info metrics technicals and news into one dossier the same shape the council\u2019s market intel agent argues from at the table.',
    inputs: 'symbol or id', outputs: 'multi source asset dossier',
    tags: ['research', 'dossier'], related: ['cmc-search-info', 'bnb-council'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-x402', name: 'cmc-x402', group: 'cmc', kind: 'skill',
    summary: 'Pay per call hub access over x402.',
    what: 'Proves the same machine payable pattern MEFAI ships on its own feed: an agent settles 0.01 USDC on Base to call a tool no key handoff.',
    inputs: '/x402/mcp · 0.01 USDC on Base', outputs: 'metered tool access',
    tags: ['x402', 'payment'], related: ['bnb-x402', 'tw-x402'], used: true, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-api-crypto', name: 'cmc-api-crypto', group: 'cmc', kind: 'skill',
    summary: 'The crypto REST surface · 16 endpoints.',
    what: 'A direct API path for batch and historical reads the MCP tools do not cover available to deepen the agent\u2019s backfill when needed.',
    inputs: 'CMC API key', outputs: '16 crypto endpoints',
    tags: ['rest', 'crypto'], related: ['cmc-skill-mcp', 'cmc-skill-api-market'], used: false, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-api-dex', name: 'cmc-api-dex', group: 'cmc', kind: 'skill',
    summary: 'The DEX REST surface · 18 endpoints.',
    what: 'Pair and pool level DEX data available to extend the agent onto venue level liquidity reads beyond the aggregate hub view.',
    inputs: 'CMC API key', outputs: '18 DEX endpoints',
    tags: ['rest', 'dex'], related: ['cmc-skill-api-crypto', 'cmc-orderflow'], used: false, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-api-exchange', name: 'cmc-api-exchange', group: 'cmc', kind: 'skill',
    summary: 'The exchange REST surface · 7 endpoints.',
    what: 'Per exchange volume and listing data available to cross check venue concentration before routing a larger order.',
    inputs: 'CMC API key', outputs: '7 exchange endpoints',
    tags: ['rest', 'exchange'], related: ['cmc-skill-api-market', 'cmc-orderflow'], used: false, link: CMC_REPO,
  },
  {
    id: 'cmc-skill-api-market', name: 'cmc-api-market', group: 'cmc', kind: 'skill',
    summary: 'The market REST surface · 19 endpoints.',
    what: 'Global dominance and index series over REST available to backfill the regime governor with longer history than the live tool returns.',
    inputs: 'CMC API key', outputs: '19 market endpoints',
    tags: ['rest', 'market'], related: ['cmc-global', 'bnb-fusion'], used: false, link: CMC_REPO,
  },
]

/* ─────────────── Trust Wallet Agent Kit · 3 skills ─────────────── */
const TW_SKILLS: SkillDef[] = [
  {
    id: 'tw-wallet', name: 'wallet · twak CLI', group: 'trust', kind: 'skill',
    summary: 'The twak command line the agent actually drives.',
    what: 'Self custody execution. The agent reads balances quotes and sends swaps transfers and bridges through twak and registers its own identity and jobs through it too.',
    inputs: 'twak <command>', outputs: 'signed actions from the agent wallet',
    tags: ['cli', 'execution', 'core'], related: ['tw-swap', 'tw-balance', 'bnb-identity'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-api', name: 'api · REST', group: 'trust', kind: 'api',
    summary: 'The Trust Wallet REST surface.',
    what: 'A server side path to the same wallet primitives available where a long running service prefers REST over spawning the CLI.',
    inputs: 'REST endpoints', outputs: 'wallet data and actions',
    tags: ['rest', 'wallet'], related: ['tw-wallet', 'tw-sdk'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-sdk', name: 'sdk · Wallet Core', group: 'trust', kind: 'sdk',
    summary: 'Wallet Core Web3 Provider and Barz.',
    what: 'The lower level building blocks behind the kit available for native key handling and account abstraction if the agent ever embeds signing directly.',
    inputs: 'Wallet Core · Web3 Provider · Barz', outputs: 'embedded signing primitives',
    tags: ['sdk', 'wallet-core'], related: ['tw-wallet', 'tw-api'], used: false, link: TW_REPO,
  },
]

/* ─────────────── Trust Wallet · the twak command surface ─────────────── */
const TW_CMDS: SkillDef[] = [
  {
    id: 'tw-balance', name: 'wallet balance', group: 'trust', kind: 'cli',
    summary: 'Read the agent wallet balance.',
    what: 'The equity feed behind the drawdown budget. Every sizing decision starts from the real balance this returns not an assumed one.',
    invoke: 'twak wallet balance', tags: ['read', 'equity'],
    related: ['bnb-sizing', 'bnb-governor'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-swap', name: 'swap', group: 'trust', kind: 'cli',
    summary: 'Quote and execute a swap.',
    what: 'The agent quotes first runs the swap through the safety gate then executes through PancakeSwap slippage bounded on every spend.',
    invoke: 'twak swap --quote-only · twak swap --slippage', tags: ['execution', 'swap', 'core'],
    related: ['tw-risk', 'bnb-x402', 'cmc-quotes'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-transfer', name: 'transfer', group: 'trust', kind: 'cli',
    summary: 'Send tokens with spend caps.',
    what: 'Used for settlement and fee flows with a max spend and a confirm to guard so a transfer can never exceed the cap the agent set.',
    invoke: 'twak transfer --max-usd --confirm-to', tags: ['execution', 'transfer'],
    related: ['tw-swap', 'bnb-ledger'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-erc8004', name: 'erc8004', group: 'trust', kind: 'cli',
    summary: 'Register and manage the agent identity.',
    what: 'The agent registers its ERC-8004 identity and serves metadata through twak so the wallet you interact with is provably the audited MEFAI agent.',
    invoke: 'twak erc8004 register · show · set-metadata', tags: ['identity', 'erc-8004', 'core'],
    related: ['bnb-identity', 'tw-wallet'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-erc8183', name: 'erc8183', group: 'trust', kind: 'cli',
    summary: 'Create fund and settle agent jobs.',
    what: 'The job lifecycle for agent to agent work. MEFAI uses it to create fund and complete jobs against verifiable status.',
    invoke: 'twak erc8183 create-job · fund · complete · status', tags: ['jobs', 'erc-8183'],
    related: ['bnb-x402', 'tw-erc8004'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-compete', name: 'compete register', group: 'trust', kind: 'cli',
    summary: 'Register the agent into the competition.',
    what: 'The exact command that entered MEFAI into BNB HACK from the agent wallet on mainnet before the deadline.',
    invoke: 'twak compete register', tags: ['compete', 'register'],
    related: ['tw-erc8004', 'bnb-identity'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-serve', name: 'serve --watch', group: 'trust', kind: 'cli',
    summary: 'Run the agent autonomously.',
    what: 'The autonomous loop. With watch on the agent acts on its own signals through the same gated execution path no human in the loop.',
    invoke: 'twak serve --watch', tags: ['autonomous', 'loop', 'core'],
    related: ['tw-swap', 'bnb-signals'], used: true, link: TW_REPO,
  },
  {
    id: 'tw-guard', name: 'wallet approval guard', group: 'trust', kind: 'engine',
    summary: 'Live ERC-20 allowance scan for a self custody wallet.',
    what: 'The MEFAI wallet check the same scan the terminal runs. It reads every live ERC-20 allowance a wallet has granted on BSC flags unlimited and possible spam approvals and ranks each by the USD it puts at risk. Trade execution lives in Trust Wallet so the wallet the agent acts from has its drain surface audited before an exploit can use it. Revoke runs in the terminal with the user\u2019s own connected Trust Wallet.',
    inputs: 'wallet address · BSC', outputs: 'risky approvals · unlimited count · USD at risk · severity per spender',
    invoke: 'live · scan a wallet on the Trust Wallet page', tags: ['safety', 'approval', 'drainer', 'core'],
    related: ['tw-approve', 'tw-risk', 'tw-swap'], used: true,
  },
  {
    id: 'tw-dca', name: 'dca-setup', group: 'trust', kind: 'cli',
    summary: 'Schedule recurring buys.',
    what: 'Available in the kit for time sliced accumulation. MEFAI keeps entries signal driven today so this is surfaced as an option rather than wired in.',
    invoke: 'twak dca-setup', tags: ['dca', 'available'],
    related: ['tw-limit', 'tw-swap'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-limit', name: 'limit-order', group: 'trust', kind: 'cli',
    summary: 'Place a resting limit order.',
    what: 'Available for passive entries at a target price. The agent currently commits at signal time so this is an available extension.',
    invoke: 'twak limit-order', tags: ['limit', 'available'],
    related: ['tw-dca', 'bnb-tpsl'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-alert', name: 'price-alert', group: 'trust', kind: 'cli',
    summary: 'Set a price trigger.',
    what: 'Available to fire on a level. MEFAI\u2019s own signal engine already watches the tape so the kit alert is an available alternative path.',
    invoke: 'twak price-alert', tags: ['alert', 'available'],
    related: ['bnb-signals'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-sign', name: 'sign-message', group: 'trust', kind: 'cli',
    summary: 'Sign an arbitrary message.',
    what: 'Available for off chain attestations. MEFAI signs through its own auth flow today so this kit primitive is surfaced as available.',
    invoke: 'twak sign-message', tags: ['signature', 'available'],
    related: ['tw-wallet'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-risk', name: 'token-risk · honeypot-check', group: 'trust', kind: 'cli',
    summary: 'Honeypot and token risk probe.',
    what: 'The kit\u2019s own safety check. MEFAI runs a wider six check gate before any spend and surfaces the kit probe as the matching first party path.',
    invoke: 'twak token-risk · twak honeypot-check', tags: ['safety', 'honeypot'],
    related: ['tw-swap', 'cmc-info'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-approve', name: 'erc20 approve · revoke', group: 'trust', kind: 'cli',
    summary: 'Manage token approvals.',
    what: 'Available to grant check and revoke allowances. MEFAI watches drainer patterns and surfaces approval hygiene as an available control.',
    invoke: 'twak erc20 approve · check-allowance · revoke', tags: ['approval', 'available'],
    related: ['tw-risk'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-x402', name: 'x402 quote · payment', group: 'trust', kind: 'cli',
    summary: 'Pay for a machine payable resource.',
    what: 'The wallet side of x402. MEFAI sells its feed over x402 and the kit lets an agent settle for it the same pattern from the buyer seat.',
    invoke: 'twak x402 quote · payment', tags: ['x402', 'payment'],
    related: ['bnb-x402', 'cmc-skill-x402'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-bridge', name: 'bridge', group: 'trust', kind: 'cli',
    summary: 'Move assets across chains.',
    what: 'Available for cross chain settlement. MEFAI stays on BNB Chain for the judged window so bridging is surfaced as an available capability.',
    invoke: 'twak bridge', tags: ['bridge', 'available'],
    related: ['tw-transfer'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-fiat', name: 'buy-fiat · sell-fiat', group: 'trust', kind: 'cli',
    summary: 'Fiat on and off ramps.',
    what: 'Available to bring the user from cash into self custody and back. Surfaced as part of the full kit surface not in the trading loop.',
    invoke: 'twak buy-fiat · sell-fiat', tags: ['fiat', 'ramp', 'available'],
    related: ['tw-wallet'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-market', name: 'price · trending · dapps', group: 'trust', kind: 'cli',
    summary: 'Read market and ecosystem data.',
    what: 'The kit\u2019s own market reads. MEFAI sources price and trends from the CMC hub so these are available as a wallet native alternative.',
    invoke: 'twak price · trending · dapps', tags: ['read', 'available'],
    related: ['cmc-quotes', 'cmc-narratives'], used: false, link: TW_REPO,
  },
  {
    id: 'tw-history', name: 'tx-history', group: 'trust', kind: 'cli',
    summary: 'Read the wallet transaction history.',
    what: 'Available to reconstruct past activity. MEFAI keeps its own verifiable ledger so the kit history is surfaced as an available read.',
    invoke: 'twak tx-history', tags: ['history', 'available'],
    related: ['bnb-ledger'], used: false, link: TW_REPO,
  },
]

/* ─────────────── BNB Chain · MEFAI's own verifiable capabilities ─────────────── */
const BNB_CAPS: SkillDef[] = [
  {
    id: 'bnb-omni', name: 'MEFAI Omni Signal', group: 'bnb', kind: 'engine',
    summary: 'Our flagship · the whole decision chain in one live skill.',
    what: 'The capability MEFAI built for this hackathon fusing the full CoinMarketCap hub and the signal engine into one conviction convening the AI council fitting the TP/SL bracket from labeled history sizing against the drawdown budget and clearing the Trust Wallet safety gate then stating one verdict. Pick an asset and every stage runs live against the audited backend.',
    inputs: 'asset · timeframe', outputs: 'conviction · council · bracket · size · safety verdict',
    invoke: 'live · open the dossier to run the full chain', tags: ['flagship', 'fusion', 'decision', 'core'],
    related: ['bnb-fusion', 'bnb-council', 'bnb-tpsl', 'bnb-sizing', 'tw-risk', 'tw-swap', 'cmc-global', 'cmc-quotes', 'cmc-deriv', 'bnb-ledger'], used: true,
  },
  {
    id: 'bnb-signals', name: 'Signal engine', group: 'bnb', kind: 'engine',
    summary: 'The proprietary signal source behind every call.',
    what: 'The agent\u2019s primary edge. Thousands of resolved signals with labeled outcomes feed conviction and the strongest are what the council argues over.',
    outputs: 'directional signals · entry · target · stop',
    tags: ['signals', 'edge', 'core'], related: ['bnb-fusion', 'bnb-council', 'tw-serve'], used: true,
  },
  {
    id: 'bnb-fusion', name: 'Omni signal fusion', group: 'bnb', kind: 'engine',
    summary: 'One conviction score from many sources.',
    what: 'MEFAI signals the full CMC hub and the technical reads are weighted by measured hit rate into a single conviction the agent acts on.',
    inputs: 'signals · CMC tools · technicals', outputs: 'weighted conviction score',
    tags: ['fusion', 'conviction', 'core'], related: ['cmc-global', 'cmc-quotes', 'bnb-council'], used: true,
  },
  {
    id: 'bnb-council', name: 'AI council', group: 'bnb', kind: 'engine',
    summary: 'An expert council debates the trade.',
    what: 'Brain signal ML ensemble whale technical market intel prophet and candle argue challenge and reach a consensus with a track record behind each voice.',
    outputs: 'consensus signal · agreement · per expert case',
    tags: ['council', 'debate', 'consensus'], related: ['bnb-signals', 'cmc-skill-research'], used: true,
  },
  {
    id: 'bnb-sizing', name: 'Drawdown Kelly sizing', group: 'bnb', kind: 'engine',
    summary: 'Position size bounded by a drawdown budget.',
    what: 'Conviction sets the lean but the drawdown budget caps it. Size shrinks as equity nears the floor so one bad streak cannot end the agent.',
    inputs: 'conviction · equity · floor', outputs: 'bounded position size',
    tags: ['sizing', 'risk', 'kelly'], related: ['tw-balance', 'bnb-governor'], used: true,
  },
  {
    id: 'bnb-tpsl', name: 'TP/SL optimizer', group: 'bnb', kind: 'engine',
    summary: 'Take profit and stop brackets from labeled history.',
    what: 'Brackets are fit from the labeled outcome history then scaled to the live regime so the R:R reflects what actually worked not a round number.',
    outputs: 'optimized TP and SL · R:R', tags: ['tp-sl', 'brackets', 'optimization'],
    related: ['bnb-signals', 'cmc-mcap-ta'], used: true,
  },
  {
    id: 'bnb-leaderboard', name: 'Verifiable leaderboard · UVII', group: 'bnb', kind: 'engine',
    summary: 'A unified verifiable intelligence index.',
    what: 'Every skill earns its weight from a verifiable track record. The leaderboard is what gates narrative rotation and ranks the agent\u2019s own edges.',
    outputs: 'ranked skills · UVII score', tags: ['leaderboard', 'uvii', 'proof'],
    related: ['cmc-narratives', 'bnb-ledger'], used: true,
  },
  {
    id: 'bnb-registry', name: 'Commit reveal registry', group: 'bnb', kind: 'contract',
    summary: 'Every call sealed before the outcome is known.',
    what: 'A public notebook where each prediction is sealed as a keccak hash on BSC before entry and revealed after impossible to backfill or fake.',
    invoke: '0x48E9Dcb1f0F12367041Bbe5f2FE1f66D0D830558', tags: ['commit-reveal', 'proof', 'core'],
    related: ['bnb-ledger', 'bnb-signals'], used: true,
  },
  {
    id: 'bnb-governor', name: 'RiskGovernor circuit breaker', group: 'bnb', kind: 'contract',
    summary: 'A drawdown cap the agent cannot breach.',
    what: 'A contract enforcing a 1400 bps drawdown cap. Breach the budget and the vault halts on the testnet registry beneath the hard floor.',
    invoke: '0xf751366159446894D6fce783A9eB1bd5B6df25Be', tags: ['risk', 'circuit-breaker', 'core'],
    related: ['bnb-sizing', 'bnb-keeper'], used: true,
  },
  {
    id: 'bnb-ledger', name: 'Verified result ledger', group: 'bnb', kind: 'contract',
    summary: 'Thousands of real outcomes anchored to BSC.',
    what: 'The result ledger records resolved signals to BSC mainnet so the track record is something a judge verifies in a block explorer not a screenshot.',
    invoke: '0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744', tags: ['ledger', 'proof', 'mainnet'],
    related: ['bnb-registry', 'bnb-leaderboard'], used: true,
  },
  {
    id: 'bnb-identity', name: 'ERC-8004 identity', group: 'bnb', kind: 'contract',
    summary: 'A verifiable identity for the agent.',
    what: 'The agent registers an ERC-8004 identity and metadata on BSC mainnet so its actions are provably attributable to one audited entity.',
    invoke: '0x8004A169FB4a3325136EB29fA0ceB6D2e539a432', tags: ['identity', 'erc-8004', 'mainnet'],
    related: ['tw-erc8004', 'bnb-x402'], used: true,
  },
  {
    id: 'bnb-x402', name: 'x402 machine payable feed', group: 'bnb', kind: 'skill',
    summary: 'The verified signal feed sold over HTTP 402.',
    what: 'The verified feed is served over HTTP 402 with EIP-3009 binding the exact BSC token charged so one agent pays another for proven alpha in one settlement.',
    invoke: '/bnbhack-api/x402/products', tags: ['x402', 'eip-3009', 'core'],
    related: ['cmc-skill-x402', 'tw-x402', 'bnb-leaderboard'], used: true,
  },
  {
    id: 'bnb-keeper', name: 'Oracle keeper', group: 'bnb', kind: 'contract',
    summary: 'Feeds true equity to the circuit breaker.',
    what: 'The keeper records equity to the chain so the RiskGovernor always knows the real balance the drawdown cap is measured against.',
    invoke: '0x064Af3880d562720963bba400B51F95d45AF91d3', tags: ['oracle', 'keeper'],
    related: ['bnb-governor', 'tw-balance'], used: true,
  },
]

export const SKILLS: SkillDef[] = [
  ...CMC_TOOLS, ...CMC_SKILLS, ...TW_SKILLS, ...TW_CMDS, ...BNB_CAPS,
]

export const skillsByGroup = (g: SkillGroup): SkillDef[] => SKILLS.filter((s) => s.group === g)
export const skillById = (id: string): SkillDef | undefined => SKILLS.find((s) => s.id === id)

export const groupCounts = (g: SkillGroup) => {
  const all = skillsByGroup(g)
  return { total: all.length, used: all.filter((s) => s.used).length }
}
