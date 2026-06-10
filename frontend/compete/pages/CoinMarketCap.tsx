/* BNB HACK · what we built with the CoinMarketCap Agent Hub.
   The full CMC surface feeds MEFAI's fusion, narrative rotation and regime
   governor, and the live market read borrows the CMC visual language. */

import { useMemo, useState } from 'react'
import {
  Btn, Card, Chip, Panel, Stat, CountUp, Reveal, PctCell, CmcTable, CoinLogo,
  fmtUsd, fmtPrice, fmtNum,
} from '../ui'
import type { CmcColumn } from '../ui'
import { usePoll, fetchCmcGlobal, fetchCmcIntel } from '../api'
import type { CmcGlobal, CmcIntel, CmcToken } from '../api'
import { GITHUB_URL } from '../config'
import { SponsorHero, FeatureGrid, SponsorSectionHead } from './sponsorKit'
import { SkillCatalog } from './skillCatalog'
import { OrderFlowPanel, TokenizedStocksPanel } from './orderFlow'
import { IconExternal } from '../icons'

const TONE = 'var(--cmc)'

const VERDICT_TONE: Record<string, string> = {
  'strong buy': 'var(--green)', buy: 'var(--green)', neutral: 'var(--c-muted)',
  weak: 'var(--gold)', avoid: 'var(--red)',
}
const verdictTone = (v: string) => VERDICT_TONE[(v || '').toLowerCase()] || 'var(--c-muted)'

export default function CoinMarketCap({ go }: { go: (p: string) => void }) {
  return <div>
    <SponsorHero
      tone={TONE} eyebrow={'Built with CoinMarketCap'} go={go}
      title={<>{'The whole market'}<br />{'fused into'} <span style={{ color: TONE }}>{'one conviction'}</span></>}
      blurb={'MEFAI wires the full CoinMarketCap Agent Hub into its decision engine. Global metrics · derivatives · trending narratives · market cap reads · macro events all flow into one conviction score, the narrative rotation skill and the regime governor.'}
    />

    <Reveal>
      <div style={{ maxWidth: 1320, margin: '0 auto', padding: '0 22px' }}>
        <LiveMarket />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow={'The live tape'} title={'Who is buying who is selling'}
      sub={'The same order flow read that feeds the agent. Aggressive taker buys versus sells from the real Binance spot tape plus the resting book imbalance. No key no fabrication. The tokenized stocks card shows where this engine extends next on BNB Chain.'} />
    <Reveal>
      <div style={{ maxWidth: 1320, margin: '0 auto', padding: '0 22px', display: 'grid', gap: 16 }}>
        <OrderFlowPanel />
        <TokenizedStocksPanel />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow={'What we built'} title={'Every CMC tool doing real work'} />
    <FeatureGrid tone={TONE} items={[
      { t: 'CMC inside omni signal fusion', d: 'Global market cap dominance and volume become weighted inputs in the same conviction score as our own signals each scaled by its measured hit rate.' },
      { t: 'Narrative rotation skill', d: 'We rank live CMC trending narratives and rotate the book into the strongest but only after the verifiable leaderboard confirms the edge is real.' },
      { t: 'Regime governor', d: 'BTC dominance and the aggregate market read set the regime. Every take profit and stop bracket is scaled to that regime so risk shrinks in a hostile tape.' },
      { t: 'Derivatives overlay', d: 'Open interest and funding from the CMC derivatives tools flag crowded positioning before the agent commits to a direction.' },
      { t: 'Macro event awareness', d: 'Upcoming macro events from the hub gate sizing around known volatility windows instead of trading blind into them.' },
      { t: 'CMC native tables', d: 'The verifiable leaderboard and skill studio replicate the CMC table language so judges read our proof in a format they already trust.' },
    ]} />

    <SponsorSectionHead tone={TONE} eyebrow={'See it running'} title={'Our live market intelligence embedded'}
      sub={'The same CoinMarketCap powered reads the agent uses embedded live from the production terminal. The AI crossover engine the audited top 1000 the deep intelligence read the market regime gauge and the macro dashboard. Pick one watch it pull live data then open it full screen.'} />
    <Reveal>
      <div style={{ maxWidth: 1320, margin: '0 auto', padding: '0 22px' }}>
        <CmcEmbedViewer />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow={'The full surface'} title={'Every CoinMarketCap skill catalogued'}
      sub={'The whole Agent Hub one card per capability: the 12 MCP tools and the 8 skills. Search filter by kind or show only what the live agent calls today. Tap any card for how MEFAI wires it in and what it connects to.'} />
    <SkillCatalog group="cmc" tone={TONE} />

    <div style={{ textAlign: 'center', padding: '34px 22px 70px', display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
      <Btn variant="cmc" onClick={() => go('/compete/skills')}>{'Open the strategy skills'}</Btn>
      <Btn variant="ghost" href={GITHUB_URL}>{'Read the source'}</Btn>
    </div>
  </div>
}

/* ─────────────── live CMC powered terminal pages, embedded ───────────────
   The real production pages, loaded in preview mode from the same origin so
   the panels render without the wallet upsell. Same backend, same data, just
   surfaced inside the jury sub-site. */
const CMC_EMBEDS: { label: string; path: string; note: string }[] = [
  { label: 'AI Crossover', path: '/cross-signal', note: 'The cross asset signal engine: where our own resolved signals and the CoinMarketCap market read agree scored on the live verifiable track record.' },
  { label: 'Top 1000', path: '/cmc-intelligence', note: 'The full audited market: every one of the top 1000 assets scored with a MEFAI verdict the same read that feeds the conviction engine.' },
  { label: 'Deep Intelligence', path: '/deep-intelligence', note: 'The deep market intelligence read that fuses the CoinMarketCap surface with our signal and regime layers into one view.' },
  { label: 'Market Regime', path: '/btc-dominance', note: 'BTC dominance and the aggregate market read that set the regime. Every take profit and stop bracket is scaled to this gauge.' },
  { label: 'Macro Dashboard', path: '/btc-macro', note: 'The institutional macro cockpit: net liquidity regime score correlations and the macro calendar that gate sizing around volatility windows.' },
]

function CmcEmbedViewer() {
  const [active, setActive] = useState(0)
  const cur = CMC_EMBEDS[active]
  return <Panel title={'LIVE MARKET INTELLIGENCE EMBEDDED'} accent="#3861FB" right="mefai.io terminal">
    <p style={{ fontSize: 12.5, color: 'var(--c-muted)', margin: '0 0 14px', lineHeight: 1.55 }}>
      {'Each tool below reads live as you watch it. Pick one then open it full screen to drive it yourself.'}
    </p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14, ['--c-primary' as string]: TONE, ['--c-primary-soft' as string]: 'color-mix(in srgb, var(--cmc) 14%, transparent)' }}>
      {CMC_EMBEDS.map((e, i) => (
        <button key={e.path} onClick={() => setActive(i)} aria-pressed={i === active} className={`cp-pill ${i === active ? 'on' : ''}`}>{e.label}</button>
      ))}
    </div>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-text-2)', lineHeight: 1.55, flex: '1 1 320px' }}>{cur.note}</span>
      <a href={cur.path} target="_blank" rel="noopener noreferrer" className="mono" style={{ fontSize: 12, fontWeight: 700, color: TONE, textDecoration: 'none', whiteSpace: 'nowrap' }}>
        {'Open full screen'} <IconExternal size={12} />
      </a>
    </div>
    <div style={{ borderRadius: 12, overflow: 'hidden', border: '1px solid var(--c-line)', background: 'var(--c-panel-2)', height: 'min(72vh, 760px)' }}>
      <iframe key={cur.path} src={`${cur.path}?mobile=preview`} title={cur.label} loading="lazy" allow="clipboard-write" style={{ width: '100%', height: '100%', border: 0, display: 'block' }} />
    </div>
  </Panel>
}

/* ─────────────── live market read (CMC + CoinGecko global) ─────────────── */
function LiveMarket() {
  const { data: g } = usePoll<CmcGlobal>((s) => fetchCmcGlobal(s), 60_000)
  const { data: intel, error: intelErr } = usePoll<CmcIntel>((s) => fetchCmcIntel(1000, s), 60_000)
  const sum = intel?.market_summary

  return <div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginTop: 4 }}>
      <Stat label={'Total market cap'} value={g ? fmtUsd(g.total_market_cap_usd) : '-'} tone={TONE} sub={'all assets'} />
      <Stat label={'24h volume'} value={g ? fmtUsd(g.total_volume_usd) : '-'} tone="var(--c-text)" sub={'spot turnover'} />
      <Stat label={'BTC dominance'} value={g ? <CountUp value={g.btc_dominance} decimals={1} suffix="%" /> : '-'} tone="var(--gold)" sub={'share of cap'} />
      <Stat label={'ETH dominance'} value={g ? <CountUp value={g.eth_dominance} decimals={1} suffix="%" /> : '-'} tone="var(--trust)" sub={'share of cap'} />
      <Stat label={'Avg MEFAI score'} value={sum ? <CountUp value={sum.avg_score} decimals={1} /> : '-'} tone="var(--green)" sub={`${sum?.total_tokens ?? 0} ${'tokens audited'}`} />
      <Stat label={'Anomalies'} value={sum ? <CountUp value={sum.anomaly_count} /> : '-'} tone={sum && sum.anomaly_count > 0 ? 'var(--red)' : 'var(--c-text)'} sub={'flagged by engine'} />
    </div>

    {sum && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center', marginTop: 14 }}>
      <Chip tone="var(--green)" solid>{sum.strong_buy} {'strong buy'}</Chip>
      <Chip tone="var(--green)">{sum.buy} {'buy'}</Chip>
      <Chip tone="var(--c-muted)">{sum.neutral} {'neutral'}</Chip>
      <Chip tone="var(--gold)">{sum.weak} {'weak'}</Chip>
      <Chip tone="var(--red)">{sum.avoid} {'avoid'}</Chip>
    </div>}

    <div style={{ marginTop: 16 }}>
      <TokenTable intel={intel} error={intelErr} />
    </div>

    <div style={{ marginTop: 16 }}>
      <NarrativeRotation intel={intel} />
    </div>
  </div>
}

/* ─────────────── narrative rotation · CMC ecosystems, derived from the same
   audited token set (no extra fetch) ─────────────── */
type NarrRow = { name: string; chg: number; vol: number; mcap: number; n: number }
function NarrativeRotation({ intel }: { intel: CmcIntel | null }) {
  const rows = useMemo<NarrRow[]>(() => {
    const tokens = intel?.tokens ?? []
    const map = new Map<string, { chgSum: number; n: number; vol: number; mcap: number }>()
    for (const t of tokens) {
      for (const eco of (t.ecosystems || [])) {
        if (!eco) continue
        const m = map.get(eco) || { chgSum: 0, n: 0, vol: 0, mcap: 0 }
        m.chgSum += Number(t.change_24h) || 0; m.n += 1
        m.vol += Number(t.volume_24h) || 0; m.mcap += Number(t.market_cap) || 0
        map.set(eco, m)
      }
    }
    return [...map.entries()]
      .filter(([, m]) => m.n >= 2)
      .map(([name, m]) => ({ name, chg: m.chgSum / m.n, vol: m.vol, mcap: m.mcap, n: m.n }))
      .sort((a, b) => b.chg - a.chg)
      .slice(0, 12)
  }, [intel])

  const cols: CmcColumn<NarrRow>[] = [
    { key: 'name', header: 'Narrative', align: 'l', sticky: true, sortValue: (r) => r.name, render: (r) => <span style={{ fontWeight: 700, textTransform: 'capitalize' }}>{r.name}</span> },
    { key: 'tokens', header: 'Tokens', sortValue: (r) => r.n, render: (r) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{r.n}</span> },
    { key: 'chg', header: 'Avg 24h', sortValue: (r) => r.chg, render: (r) => <PctCell value={r.chg} d={2} /> },
    { key: 'mcap', header: 'Market cap', sortValue: (r) => r.mcap, render: (r) => <span className="mono">{fmtUsd(r.mcap)}</span> },
    { key: 'rotate', header: 'Signal', sortValue: (r) => r.chg, render: (r) => <Chip tone={r.chg > 0 ? 'var(--green)' : 'var(--red)'}>{r.chg > 2 ? 'ROTATE IN' : r.chg < -2 ? 'ROTATE OUT' : 'HOLD'}</Chip> },
  ]

  return <Panel title={'NARRATIVE ROTATION'} accent="#3861FB" right={'CMC ecosystems'}>
    {rows.length === 0
      ? <div style={{ color: 'var(--c-muted)', padding: 24, textAlign: 'center', fontSize: 13 }}>{intel ? 'Ecosystem grouping needs at least two tokens per narrative.' : 'reading ecosystems…'}</div>
      : <CmcTable columns={cols} rows={rows} maxHeight={440} defaultSort={{ key: 'chg', dir: 'desc' }} />}
  </Panel>
}

const VERDICT_RANK: Record<string, number> = {
  'strong buy': 4, buy: 3, neutral: 2, weak: 1, avoid: 0,
}
const VERDICT_FILTERS = ['all', 'strong buy', 'buy', 'neutral', 'weak', 'avoid']

function TokenTable({ intel, error }: { intel: CmcIntel | null; error?: boolean }) {
  const all = intel?.tokens ?? []
  const [q, setQ] = useState('')
  const [verdict, setVerdict] = useState('all')
  const [showAll, setShowAll] = useState(false)

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return all.filter((r) => {
      if (verdict !== 'all' && (r.verdict || '').toLowerCase() !== verdict) return false
      if (!needle) return true
      return (r.symbol + ' ' + r.name).toLowerCase().includes(needle)
    })
  }, [all, q, verdict])

  const cols: CmcColumn<CmcToken>[] = [
    { key: 'rank', header: '#', sortValue: (r) => r.rank, render: (r) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{r.rank}</span> },
    { key: 'name', header: 'Token', align: 'l', sticky: true, sortValue: (r) => r.symbol, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.symbol} /><span><span className="cmc-name-main">{r.symbol}</span><span className="cmc-name-sym">{r.name}</span></span></span> },
    { key: 'price', header: 'Price', sortValue: (r) => r.price, render: (r) => <span className="mono">{fmtPrice(r.price)}</span> },
    { key: 'h1', header: '1h', hideSm: true, sortValue: (r) => r.change_1h, render: (r) => <PctCell value={r.change_1h} /> },
    { key: 'h24', header: '24h', sortValue: (r) => r.change_24h, render: (r) => <PctCell value={r.change_24h} /> },
    { key: 'd7', header: '7d', hideSm: true, sortValue: (r) => r.change_7d, render: (r) => <PctCell value={r.change_7d} /> },
    { key: 'vol', header: '24h volume', hideSm: true, sortValue: (r) => r.volume_24h, render: (r) => <span className="mono">{fmtUsd(r.volume_24h)}</span> },
    { key: 'cap', header: 'Market cap', hideSm: true, sortValue: (r) => r.market_cap, render: (r) => <span className="mono">{fmtUsd(r.market_cap)}</span> },
    { key: 'score', header: 'MEFAI', sortValue: (r) => r.mefai_score, render: (r) => <span className="mono" style={{ fontWeight: 800, color: TONE }}>{fmtNum(r.mefai_score, 0)}</span> },
    { key: 'verdict', header: 'Verdict', sortValue: (r) => VERDICT_RANK[(r.verdict || '').toLowerCase()] ?? -1, render: (r) => <Chip tone={verdictTone(r.verdict)}>{r.verdict}</Chip> },
  ]

  const right = intel ? `${rows.length} ${'of'} ${all.length} · ${intel.cache_age_seconds}s` : error ? 'offline' : 'loading'
  const empty = error
    ? 'The market feed is unreachable right now.'
    : (q || verdict !== 'all') ? 'No token matches that filter.' : 'reading the market…'

  return <Panel title={'MARKET · MEFAI AUDIT'} accent="#3861FB" right={right}>
    <div className="cp-sk-bar" style={{ marginBottom: 12, ['--sk-tone' as string]: TONE }}>
      <input className="cp-sk-search mono" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={`${'Search'} ${all.length} ${'tokens'}`} spellCheck={false} />
      <div className="cp-sk-filters">
        {VERDICT_FILTERS.map((v) => (
          <button key={v} className={`cp-sk-f ${verdict === v ? 'on' : ''}`} aria-pressed={verdict === v} onClick={() => setVerdict(v)}>
            {v === 'all' ? 'All' : v}
          </button>
        ))}
      </div>
    </div>
    <CmcTable columns={cols} rows={showAll ? rows : rows.slice(0, 100)} defaultSort={{ key: 'rank', dir: 'asc' }}
      empty={empty} maxHeight={520} />
    {rows.length > 100 && <div style={{ textAlign: 'center', marginTop: 12 }}>
      <button className="cp-pill" onClick={() => setShowAll(!showAll)}>
        {showAll ? 'Show top 100' : `Show all ${rows.length}`}
      </button>
    </div>}
  </Panel>
}
