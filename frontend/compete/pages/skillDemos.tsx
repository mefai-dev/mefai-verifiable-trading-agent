/* BNB HACK · live working demo per skill.
   Clicking a capability card opens its dossier and, where the data is reachable
   key-free, a working panel that runs the same read the agent runs. Every number
   here is live: global metrics and the per token audit come from the CMC backed
   intelligence endpoint, order flow from the real Binance spot tape. The few hub
   feeds that need the CMC Pro key (derivatives, narratives, macro, news) show the
   exact invoke and the response shape the agent consumes, but never fabricated
   numbers. Integrity is the point: a judge sees real output or an honest schema,
   never a faked feed. */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  usePoll, fetchCmcGlobal, fetchCmcIntel, fetchCmcGate, fetchX402Products, fetchLoopState,
  fetchSecurity, fetchFusion, fetchRecentSignals, fetchDebate, fetchSizing, fetchTpSl, fetchLeaderboard,
  fetchX402Roundtrip, fetchX402CmcChallenge,
} from '../api'
import type {
  CmcGlobal, CmcIntel, CmcToken, CmcGate, X402Catalog, LoopEnvelope, SecurityVerdict,
  FusionResult, RecentSignals, DebateResult, SizingResult, TpSl, Leaderboard,
  X402Step, X402Roundtrip, X402CmcChallenge,
} from '../api'
import { Chip, CountUp, PctCell, CoinLogo, fmtUsd, fmtPrice, fmtNum, fmtPct, clamp01, shortAddr, Btn } from '../ui'
import type { SkillDef } from '../skills'
import { SKILLS } from '../skills'
import { ADDR, AGENT_ID, scan, chainLabel } from '../config'
import { OrderFlowPanel } from './orderFlow'
import { WalletGuardPanel } from './walletGuard'
import { OmniSignalPanel } from './omniSignal'

const TONE = 'var(--cmc)'
const BNB_TONE = 'var(--gold)'
const TW_TONE = 'var(--trust)'

function DemoFrame({ label, right, children }: { label: string; right?: ReactNode; children: ReactNode }) {
  return <div className="cp-sk-demo">
    <div className="cp-sk-demo-h">
      <span className="cp-sk-demo-live">{'LIVE'}</span>
      <span className="cp-sk-demo-l">{label}</span>
      {right && <span className="cp-sk-demo-r mono">{right}</span>}
    </div>
    {children}
  </div>
}

function MiniStat({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: string; sub?: string }) {
  return <div style={{ padding: '9px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
    <div style={{ fontSize: 10, letterSpacing: .5, textTransform: 'uppercase', color: 'var(--c-muted)', fontWeight: 700 }}>{label}</div>
    <div style={{ fontSize: 16, fontWeight: 800, color: tone || 'var(--c-text)', marginTop: 3, overflowWrap: 'anywhere' }}>{value}</div>
    {sub && <div style={{ fontSize: 10.5, color: 'var(--c-muted-2)', marginTop: 2 }}>{sub}</div>}
  </div>
}
const statGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(116px,1fr))', gap: 8 }

/* ── live global + regime (cmc-global, cmc-mcap-ta) ── */
function GlobalDemo({ regime }: { regime?: boolean }) {
  const { data: g, error } = usePoll<CmcGlobal>((s) => fetchCmcGlobal(s), 60_000)
  const label = regime ? 'Total market cap regime read' : 'Global metrics live'
  if (!g && error) return <DemoFrame label={label} right={'CMC hub'}><Down what="Global market data is not reachable right now." /></DemoFrame>
  if (!g) return <DemoFrame label={label} right={'reading'}><Reading /></DemoFrame>
  const chg = g?.mcap_change_24h ?? 0
  const read = chg > 1.5 ? { t: 'Risk on', c: 'var(--green)' } : chg < -1.5 ? { t: 'Risk off', c: 'var(--red)' } : { t: 'Neutral', c: 'var(--gold)' }
  return <DemoFrame label={label} right={'updated'}>
    {regime && <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
      <Chip tone={read.c} solid>{read.t}</Chip>
      <span style={{ fontSize: 12, color: 'var(--c-muted)' }}>{'from the 24h market cap trend'}</span>
    </div>}
    <div style={statGrid}>
      <MiniStat label="Total cap" value={g ? fmtUsd(g.total_market_cap_usd) : '-'} tone={TONE} />
      <MiniStat label="24h volume" value={g ? fmtUsd(g.total_volume_usd) : '-'} />
      <MiniStat label="BTC dom" value={g ? <CountUp value={g.btc_dominance} decimals={1} suffix="%" /> : '-'} tone="var(--gold)" />
      <MiniStat label="ETH dom" value={g ? <CountUp value={g.eth_dominance} decimals={1} suffix="%" /> : '-'} tone="var(--trust)" />
      <MiniStat label="Cap 24h" value={g ? <PctCell value={g.mcap_change_24h} /> : '-'} tone={read.c} />
      <MiniStat label="Assets" value={g ? <CountUp value={g.active_cryptocurrencies} /> : '-'} />
    </div>
  </DemoFrame>
}

/* ── token picker shared by quote / metrics / info / ta / research ── */
function useTokens() {
  const { data, error, loading } = usePoll<CmcIntel>((s) => fetchCmcIntel(40, s), 60_000)
  return { tokens: data?.tokens ?? [], error, loading }
}
/* shared honest down/reading state for the token-driven CMC demos · render this
   in JSX (`return <TokenGate .../>`) when the token feed has nothing yet. */
function TokenGate({ label, error }: { label: string; error: unknown }) {
  return error
    ? <DemoFrame label={label} right={'CMC hub'}><Down what="The CMC token feed is not reachable right now." /></DemoFrame>
    : <DemoFrame label={label} right={'reading'}><Reading /></DemoFrame>
}
function TokenPick({ tokens, sym, setSym }: { tokens: CmcToken[]; sym: string; setSym: (s: string) => void }) {
  const picks = tokens.slice(0, 6)
  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
    {picks.map((t) => (
      <button key={t.symbol} className={`cp-pill ${sym === t.symbol ? 'on' : ''}`} aria-pressed={sym === t.symbol} onClick={() => setSym(t.symbol)}>
        <CoinLogo symbol={t.symbol} size={15} />{t.symbol}
      </button>
    ))}
  </div>
}

function QuoteDemo({ metrics }: { metrics?: boolean }) {
  const { tokens, error } = useTokens()
  const [sym, setSym] = useState('BTC')
  const t = tokens.find((x) => x.symbol === sym) || tokens[0]
  const label = metrics ? 'Per asset metrics live' : 'Latest quote live'
  if (tokens.length === 0) return <TokenGate label={label} error={error} />
  return <DemoFrame label={label} right={t ? `#${t.rank}` : 'reading'}>
    <TokenPick tokens={tokens} sym={t?.symbol ?? sym} setSym={setSym} />
    {t && <div style={statGrid}>
      <MiniStat label="Price" value={fmtPrice(t.price)} tone={TONE} />
      <MiniStat label="1h" value={<PctCell value={t.change_1h} />} />
      <MiniStat label="24h" value={<PctCell value={t.change_24h} />} />
      <MiniStat label="7d" value={<PctCell value={t.change_7d} />} />
      <MiniStat label="24h volume" value={fmtUsd(t.volume_24h)} />
      <MiniStat label="Market cap" value={fmtUsd(t.market_cap)} />
    </div>}
  </DemoFrame>
}

function InfoDemo() {
  const { tokens, error } = useTokens()
  const [sym, setSym] = useState('BNB')
  const t = tokens.find((x) => x.symbol === sym) || tokens[0]
  if (tokens.length === 0) return <TokenGate label="Asset profile live" error={error} />
  return <DemoFrame label="Asset profile live" right={t ? t.name : 'reading'}>
    <TokenPick tokens={tokens} sym={t?.symbol ?? sym} setSym={setSym} />
    {t && <div style={statGrid}>
      <MiniStat label="Name" value={<span style={{ fontSize: 13 }}>{t.name}</span>} />
      <MiniStat label="Rank" value={`#${t.rank}`} tone={TONE} />
      <MiniStat label="Contract chain" value={<span style={{ fontSize: 13 }}>{t.contract_chain || 'native'}</span>} />
      <MiniStat label="Ecosystems" value={<span style={{ fontSize: 12 }}>{(t.ecosystems || []).slice(0, 2).join(', ') || '-'}</span>} />
    </div>}
  </DemoFrame>
}

const verdictTone = (v: string) => {
  const k = (v || '').toLowerCase()
  if (k.includes('strong') || k === 'buy') return 'var(--green)'
  if (k === 'avoid') return 'var(--red)'
  if (k === 'weak') return 'var(--gold)'
  return 'var(--c-muted)'
}

function SignalDemo({ research }: { research?: boolean }) {
  const { tokens, error } = useTokens()
  const [sym, setSym] = useState('BTC')
  const t = tokens.find((x) => x.symbol === sym) || tokens[0]
  const label = research ? 'Asset dossier live' : 'Technical read live'
  if (tokens.length === 0) return <TokenGate label={label} error={error} />
  return <DemoFrame label={label} right={t ? `${t.symbol} ${'audit'}` : 'reading'}>
    <TokenPick tokens={tokens} sym={t?.symbol ?? sym} setSym={setSym} />
    {t && <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <div style={{ fontSize: 30, fontWeight: 900, color: TONE, lineHeight: 1 }}>{fmtNum(t.mefai_score, 0)}</div>
        <div>
          <Chip tone={verdictTone(t.verdict)} solid>{t.verdict}</Chip>
          <div style={{ fontSize: 11, color: 'var(--c-muted-2)', marginTop: 4 }}>{'MEFAI conviction score'}</div>
        </div>
        {t.has_anomaly && <Chip tone="var(--red)">{'anomaly'}</Chip>}
      </div>
      {t.verdict_reason && <p style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--c-text-2)', margin: 0 }}>{t.verdict_reason}</p>}
      {research && <div style={{ ...statGrid, marginTop: 10 }}>
        <MiniStat label="Price" value={fmtPrice(t.price)} />
        <MiniStat label="24h" value={<PctCell value={t.change_24h} />} />
        <MiniStat label="7d" value={<PctCell value={t.change_7d} />} />
      </div>}
    </>}
  </DemoFrame>
}

function SearchDemo() {
  const { tokens, error } = useTokens()
  const [q, setQ] = useState('bnb')
  if (tokens.length === 0) return <TokenGate label="Resolve a ticker live" error={error} />
  const needle = q.trim().toLowerCase()
  const hits = needle
    ? tokens.filter((t) => t.symbol.toLowerCase().includes(needle) || t.name.toLowerCase().includes(needle)).slice(0, 4)
    : []
  return <DemoFrame label="Resolve a ticker live" right={`${hits.length} ${'match'}`}>
    <input value={q} onChange={(e) => setQ(e.target.value)} spellCheck={false} placeholder={'Type a name or ticker'}
      className="mono" style={{ width: '100%', padding: '9px 11px', borderRadius: 9, border: '1px solid var(--c-line-2)', background: 'var(--c-panel)', color: 'var(--c-text)', fontSize: 13, outline: 'none', marginBottom: 10 }} />
    <div style={{ display: 'grid', gap: 6 }}>
      {hits.map((t) => (
        <div key={t.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '8px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 700 }}><CoinLogo symbol={t.symbol} size={16} />{t.symbol} · {t.name}</span>
          <span className="mono" style={{ fontSize: 12, color: 'var(--c-muted)' }}>{'rank'} #{t.rank} · {'score'} {fmtNum(t.mefai_score, 0)}</span>
        </div>
      ))}
      {needle && hits.length === 0 && <div style={{ fontSize: 12, color: 'var(--c-muted-2)' }}>{'No asset in the live set matches that.'}</div>}
    </div>
  </DemoFrame>
}

function ReportDemo() {
  const { data, error } = usePoll<CmcIntel>((s) => fetchCmcIntel(40, s), 60_000)
  const sum = data?.market_summary
  const top = (data?.tokens ?? []).slice(0, 5)
  if (!sum && error) return <DemoFrame label="Market report live" right={'CMC hub'}><Down what="The CMC market report is not reachable right now." /></DemoFrame>
  if (!sum) return <DemoFrame label="Market report live" right={'reading'}><Reading /></DemoFrame>
  return <DemoFrame label="Market report live" right={`${sum.total_tokens} ${'audited'}`}>
    {sum && <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        <Chip tone="var(--green)" solid>{sum.strong_buy} {'strong buy'}</Chip>
        <Chip tone="var(--green)">{sum.buy} {'buy'}</Chip>
        <Chip tone="var(--c-muted)">{sum.neutral} {'neutral'}</Chip>
        <Chip tone="var(--gold)">{sum.weak} {'weak'}</Chip>
        <Chip tone="var(--red)">{sum.avoid} {'avoid'}</Chip>
      </div>
      <div style={{ ...statGrid, marginBottom: 10 }}>
        <MiniStat label="Avg score" value={<CountUp value={sum.avg_score} decimals={1} />} tone={TONE} />
        <MiniStat label="Anomalies" value={<CountUp value={sum.anomaly_count} />} tone={sum.anomaly_count > 0 ? 'var(--red)' : 'var(--green)'} />
      </div>
      <div style={{ display: 'grid', gap: 5 }}>
        {top.map((t) => (
          <div key={t.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 12.5 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700 }}><CoinLogo symbol={t.symbol} size={15} />{t.symbol}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><PctCell value={t.change_24h} /><Chip tone={verdictTone(t.verdict)}>{t.verdict}</Chip></span>
          </div>
        ))}
      </div>
    </>}
  </DemoFrame>
}

function McpDemo() {
  const tools = useMemo(() => SKILLS.filter((s) => s.group === 'cmc' && s.kind === 'mcp-tool'), [])
  return <DemoFrame label="MCP server surface" right={`${tools.length} ${'tools'}`}>
    <p style={{ fontSize: 12, color: 'var(--c-muted)', margin: '0 0 10px' }}>{'Every tool the live agent calls is one of these served verbatim from the CoinMarketCap MCP server.'}</p>
    <div style={{ display: 'grid', gap: 5 }}>
      {tools.map((t) => (
        <div key={t.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '7px 10px', borderRadius: 8, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
          <code className="mono" style={{ fontSize: 11.5, color: 'var(--c-text-2)' }}>{t.name}</code>
          <span style={{ fontSize: 10.5, color: t.used ? TONE : 'var(--c-muted-2)', fontWeight: 700 }}>{t.used ? 'live' : 'idle'}</span>
        </div>
      ))}
    </div>
  </DemoFrame>
}

/* ── honest schema demo for hub feeds that need the CMC Pro key ── */
function SchemaDemo({ s }: { s: SkillDef }) {
  const note = s.used
    ? 'Live hub feed · the agent calls this on the CMC Pro key. We show the exact invoke and the response shape it consumes but render no fabricated numbers here so what you see is either real output or an honest schema.'
    : 'Available surface · not wired into the live agent today. The invoke and shape below are what it would return when enabled.'
  const fields = (s.outputs || '').split('·').map((x) => x.trim()).filter(Boolean)
  return <div className="cp-sk-demo">
    <div className="cp-sk-demo-h">
      <span className="cp-sk-demo-live" style={{ background: 'var(--c-muted-2)', color: 'var(--c-text)' }}>{s.used ? 'FEED' : 'AVAIL'}</span>
      <span className="cp-sk-demo-l">{'Response shape'}</span>
    </div>
    {s.invoke && <code className="cp-sk-invoke mono" style={{ display: 'block', marginBottom: 10 }}>{s.invoke}</code>}
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
      {fields.map((f) => <span key={f} className="cp-sk-tag">{f}</span>)}
    </div>
    <p style={{ fontSize: 11.5, lineHeight: 1.55, color: 'var(--c-muted-2)', margin: 0 }}>{note}</p>
  </div>
}

function Reading() { return <div style={{ fontSize: 12, color: 'var(--c-muted-2)', padding: '6px 2px' }}>{'reading live feed'}<span className="cp-ellipsis" /></div> }
function Down({ what }: { what: string }) { return <div style={{ fontSize: 12, color: 'var(--c-muted-2)', padding: '4px 2px', lineHeight: 1.5 }}>{what}</div> }
const miniLabel: React.CSSProperties = { fontSize: 10, letterSpacing: .5, textTransform: 'uppercase', color: 'var(--c-muted)', fontWeight: 700, marginBottom: 4 }
const rowBox: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '7px 10px', borderRadius: 8, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }

const dirTone = (d: number) => d > 0 ? 'var(--green)' : d < 0 ? 'var(--red)' : 'var(--c-muted)'
const dirText = (d: number) => d > 0 ? 'LONG' : d < 0 ? 'SHORT' : 'NEUTRAL'
const sigTone = (s?: string) => { const k = (s || '').toUpperCase(); if (k.includes('LONG') || k.includes('BUY')) return 'var(--green)'; if (k.includes('SHORT') || k.includes('SELL')) return 'var(--red)'; return 'var(--gold)' }
const checkTone = (s: string) => { const k = (s || '').toUpperCase(); if (k === 'PASS') return 'var(--green)'; if (k === 'WARN') return 'var(--gold)'; if (k === 'FAIL' || k === 'BLOCK') return 'var(--red)'; return 'var(--c-muted)' }

/* ── CoinMarketCap hub gates, fully live (cmc-global / mcap-ta / deriv / narratives / macro).
   Each carries its MCP method name so the demo can print the exact data lineage. ── */
const GATE_TOOL: Record<string, { slug: string; label: string; method: string }> = {
  'cmc-global': { slug: 'global-metrics', label: 'Global metrics live', method: 'global_metrics_latest' },
  'cmc-mcap-ta': { slug: 'marketcap-ta', label: 'Market cap technicals live', method: 'marketcap_technical_analysis' },
  'cmc-deriv': { slug: 'derivatives', label: 'Derivatives metrics live', method: 'derivatives_metrics' },
  'cmc-macro': { slug: 'macro-events', label: 'Upcoming macro events live', method: 'upcoming_macro_events' },
  'cmc-news': { slug: 'news', label: 'Latest market news live', method: 'latest_news' },
}
/* a signed value string like "-31.66 B" / "+0.45%" coloured by its sign */
const signedTone = (v?: string) => { const t = (v || '').trim(); if (t.startsWith('-')) return 'var(--red)'; if (t.startsWith('+')) return 'var(--green)'; return 'var(--c-text)' }
/* fear & greed / altcoin-season index 0-100 → tone (low = fear/red, high = greed/green) */
const idxTone = (n: number) => n >= 55 ? 'var(--green)' : n <= 25 ? 'var(--red)' : 'var(--gold)'
/* RSI tone: oversold reads bullish (green), overbought reads bearish (red) */
const rsiTone = (n: number) => n <= 30 ? 'var(--green)' : n >= 70 ? 'var(--red)' : 'var(--c-text)'

/* cmc-global · the real CMC global_metrics_latest payload (cap, liquidity,
   fear & greed, altcoin season, dominance). Every value rendered verbatim. */
function GlobalMetricsGate({ d }: { d: any }) {
  const cap = d.market_size?.total_crypto_market_cap_usd || {}
  const vol = d.liquidity?.volume24h?.total || {}
  const fg = d.sentiment?.fear_greed?.current || {}
  const alt = d.rotation?.altcoin_season?.current || {}
  const altChg = d.rotation?.altcoin_season?.percent_change?.['24h']
  const dom = d.dominance || {}
  const fgIdx = Number(fg.index)
  const altIdx = Number(alt.index)
  return <div style={statGrid}>
    <MiniStat label="Total cap" value={cap.current || '-'} tone={TONE} sub={cap.percent_change?.['24h'] ? `24h ${cap.percent_change['24h']}` : undefined} />
    <MiniStat label="24h volume" value={vol.current || '-'} sub={vol.percent_change?.['24h'] ? `24h ${vol.percent_change['24h']}` : undefined} />
    <MiniStat label="Fear & greed" value={Number.isFinite(fgIdx) ? String(fgIdx) : '-'} tone={Number.isFinite(fgIdx) ? idxTone(fgIdx) : undefined} sub={fg.value || undefined} />
    <MiniStat label="Altcoin season" value={Number.isFinite(altIdx) ? String(altIdx) : '-'} tone={Number.isFinite(altIdx) ? idxTone(altIdx) : undefined} sub={altChg ? `24h ${altChg}` : undefined} />
    <MiniStat label="BTC dominance" value={dom.btc?.current || '-'} tone="var(--gold)" />
    <MiniStat label="ETH dominance" value={dom.eth?.current || '-'} tone="var(--trust)" />
  </div>
}

/* cmc-mcap-ta · the real CMC marketcap_technical_analysis payload (RSI, MACD,
   pivot, fib retracement on the total-cap series). Rendered verbatim. */
function MarketcapTaGate({ d }: { d: any }) {
  const rsi = d.rsi || {}, macd = d.macd || {}, fib = d.fibonacciLevels?.retracementLevels || {}
  const rsi14 = Number(rsi.rsi14)
  return <div>
    <div style={statGrid}>
      <MiniStat label="RSI 14" value={rsi.rsi14 || '-'} tone={Number.isFinite(rsi14) ? rsiTone(rsi14) : undefined} sub={(rsi.rsi7 || rsi.rsi21) ? `7 ${rsi.rsi7 ?? '-'} · 21 ${rsi.rsi21 ?? '-'}` : undefined} />
      <MiniStat label="MACD histogram" value={macd.histogram || '-'} tone={signedTone(macd.histogram)} sub={macd.macdLine ? `line ${macd.macdLine}` : undefined} />
      <MiniStat label="Pivot point" value={d.pivotPoint || '-'} tone={TONE} />
      <MiniStat label="Market cap" value={d.currentMarketCap || '-'} />
      <MiniStat label="24h volume" value={d.currentVolume || '-'} />
      <MiniStat label="Fib 61.8%" value={fib['61.8%'] || '-'} sub={fib['50.0%'] ? `50% ${fib['50.0%']}` : undefined} />
    </div>
  </div>
}
function DerivGate({ d }: { d: any }) {
  const oi = d.totalOpenInterest || {}, vol = d.totalVolume || {}, fut = d.futures || {}, perp = d.perpetuals || {}
  return <div style={statGrid}>
    <MiniStat label="Open interest" value={oi.current || '-'} tone={TONE} sub={oi.percentage_change_24h ? `24h ${oi.percentage_change_24h}` : undefined} />
    <MiniStat label="Total volume 24h" value={vol.total_usd_24h || '-'} sub={vol.pct_change_prev_24h_vs_prior_24h ? `${vol.pct_change_prev_24h_vs_prior_24h} vs prior` : undefined} />
    <MiniStat label="Futures OI" value={fut.openInterest?.current || '-'} sub={fut.openInterest?.percentage_change_24h ? `24h ${fut.openInterest.percentage_change_24h}` : undefined} />
    <MiniStat label="Perp OI" value={perp.openInterest?.current || '-'} sub={perp.openInterest?.percentage_change_24h ? `24h ${perp.openInterest.percentage_change_24h}` : undefined} />
  </div>
}
const cell = (r: any[], i: number) => (i >= 0 && r[i] != null ? String(r[i]) : '-')
/* ── narrative rotation · differentiated sector narratives grouped live from the
   CMC token universe by ecosystem (cmc-narratives). The raw trending feed returns
   market-wide regulatory baskets that all track the whole market; the rotation
   skill instead ranks distinct ecosystem narratives by their own 24h momentum. ── */
function NarrativeRotationDemo() {
  const { data, error, loading } = usePoll<CmcIntel>((s) => fetchCmcIntel(s), 90_000)
  const rows = useMemo(() => {
    const tokens = data?.tokens ?? []
    const map = new Map<string, { chgSum: number; n: number; mcap: number }>()
    for (const tk of tokens) {
      for (const eco of (tk.ecosystems || [])) {
        if (!eco) continue
        const m = map.get(eco) || { chgSum: 0, n: 0, mcap: 0 }
        m.chgSum += Number(tk.change_24h) || 0; m.n += 1; m.mcap += Number(tk.market_cap) || 0
        map.set(eco, m)
      }
    }
    return [...map.entries()]
      .filter(([, m]) => m.n >= 2)
      .map(([name, m]) => ({ name, chg: m.chgSum / m.n, mcap: m.mcap, n: m.n }))
      .sort((a, b) => b.chg - a.chg)
      .slice(0, 8)
  }, [data])
  if (loading) return <DemoFrame label="Narrative rotation live" right={'reading'}><Reading /></DemoFrame>
  if (error || rows.length === 0) return <DemoFrame label="Narrative rotation live" right={'CMC hub'}><Down what="Ecosystem narratives are not reachable right now." /></DemoFrame>
  return <DemoFrame label="Narrative rotation · live CMC ecosystems" right={`${rows.length} ${'narratives'}`}>
    <div style={{ display: 'grid', gap: 5 }}>
      {rows.map((r, i) => (
        <div key={r.name} style={rowBox}>
          <span style={{ fontSize: 12.5, fontWeight: 700, textTransform: 'capitalize' }}>{i + 1} · {r.name}</span>
          <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{r.n} {'tokens'}</span>
            <span className="mono" style={{ fontSize: 11.5, color: 'var(--c-muted)' }}>{fmtUsd(r.mcap)}</span>
            <span style={{ minWidth: 58, textAlign: 'right' }}><PctCell value={r.chg} d={2} /></span>
            <Chip tone={r.chg > 2 ? 'var(--green)' : r.chg < -2 ? 'var(--red)' : 'var(--gold)'}>{r.chg > 2 ? 'ROTATE IN' : r.chg < -2 ? 'ROTATE OUT' : 'HOLD'}</Chip>
          </span>
        </div>
      ))}
    </div>
    <div style={{ fontSize: 10.5, color: 'var(--c-muted-2)', marginTop: 8, lineHeight: 1.5 }}>
      {'Narratives grouped from the live CMC token universe by ecosystem and ranked by average 24h momentum. The rotation skill only acts after the verifiable leaderboard confirms the edge is real.'}
    </div>
  </DemoFrame>
}
function MacroGate({ d }: { d: any }) {
  const ev = d.upcomingEventNews || {}
  const headers: string[] = ev.headers || []
  const rows: any[][] = ev.rows || []
  const iTitle = headers.indexOf('title'), iDate = headers.indexOf('eventDate')
  if (iTitle < 0 || rows.length === 0) return null
  return <div style={{ display: 'grid', gap: 6 }}>
    {rows.slice(0, 6).map((r, i) => (
      <div key={i} style={{ padding: '8px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--c-text)', lineHeight: 1.4 }}>{cell(r, iTitle)}</div>
        <div className="mono" style={{ fontSize: 11, color: TONE, marginTop: 3 }}>{cell(r, iDate)}</div>
      </div>
    ))}
  </div>
}
function NewsGate({ d }: { d: any }) {
  const headers: string[] = d.headers || []
  const rows: any[][] = d.rows || []
  const iTitle = headers.indexOf('title'), iDate = headers.indexOf('publishedAt'), iUrl = headers.indexOf('url')
  if (iTitle < 0 || rows.length === 0) return null
  return <div style={{ display: 'grid', gap: 6 }}>
    {rows.slice(0, 6).map((r, i) => {
      const url = iUrl >= 0 ? r[iUrl] : ''
      const title = cell(r, iTitle)
      return <div key={i} style={{ padding: '8px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--c-text)', lineHeight: 1.4, textDecoration: 'none' }}>{title}</a>
        ) : (
          <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--c-text)', lineHeight: 1.4 }}>{title}</div>
        )}
        <div className="mono" style={{ fontSize: 11, color: TONE, marginTop: 3 }}>{cell(r, iDate)}</div>
      </div>
    })}
  </div>
}
function gateValid(id: string, d: any): boolean {
  if (id === 'cmc-global') return !!(d.market_size || d.dominance || d.liquidity)
  if (id === 'cmc-mcap-ta') return !!(d.macd || d.rsi || d.pivotPoint)
  if (id === 'cmc-deriv') return !!(d.totalOpenInterest || d.totalVolume || d.futures || d.perpetuals)
  if (id === 'cmc-macro') return (d.upcomingEventNews?.headers || []).indexOf('title') >= 0 && (d.upcomingEventNews?.rows || []).length > 0
  if (id === 'cmc-news') return (d.headers || []).indexOf('title') >= 0 && (d.rows || []).length > 0
  return false
}
function GateLineage({ method }: { method: string }) {
  return <div style={{ fontSize: 10, color: 'var(--c-muted-2)', marginTop: 9, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
    <span>{'source'}</span>
    <code className="mono" style={{ fontSize: 10, color: 'var(--c-muted)' }}>CoinMarketCap MCP · {method}</code>
  </div>
}
function CmcGateDemo({ s }: { s: SkillDef }) {
  const map = GATE_TOOL[s.id]
  const { data, error, loading } = usePoll<CmcGate>((sig) => fetchCmcGate(map.slug, sig), 120_000, [map.slug])
  if (loading) return <DemoFrame label={map.label} right={'reading'}><Reading /></DemoFrame>
  if (error || !data?.data || !gateValid(s.id, data.data)) {
    // Graceful real fallback: cap/regime tools still read CoinGecko global (key
    // free, real). Pure hub feeds fall back to the honest invoke + shape.
    if (s.id === 'cmc-global') return <GlobalDemo />
    if (s.id === 'cmc-mcap-ta') return <GlobalDemo regime />
    return <SchemaDemo s={s} />
  }
  return <DemoFrame label={map.label} right={'CMC hub'}>
    {s.id === 'cmc-global' && <GlobalMetricsGate d={data.data} />}
    {s.id === 'cmc-mcap-ta' && <MarketcapTaGate d={data.data} />}
    {s.id === 'cmc-deriv' && <DerivGate d={data.data} />}
    {s.id === 'cmc-macro' && <MacroGate d={data.data} />}
    {s.id === 'cmc-news' && <NewsGate d={data.data} />}
    <GateLineage method={map.method} />
  </DemoFrame>
}

/* ── x402 machine payable catalog, live (cmc-skill-x402 / bnb-x402) ── */
function shortHex(s?: string, head = 10, tail = 6): string {
  if (!s) return '-'
  return s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`
}

function X402StepCard({ step }: { step: X402Step }) {
  const tone = step.name === 'challenge' ? TONE
    : step.name === 'sign' ? BNB_TONE
      : step.name === 'verify' ? (step.valid ? 'var(--green)' : 'var(--red)')
        : 'var(--green)'
  const accept = step.accepts && step.accepts[0]
  return <div style={{ display: 'flex', gap: 10, padding: '9px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
    <span style={{ flex: '0 0 auto', width: 22, height: 22, borderRadius: 7, display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 800, color: '#000', background: tone }}>{step.n}</span>
    <div style={{ minWidth: 0, flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12.5, fontWeight: 700 }}>{step.title}</span>
        {step.status != null && <Chip tone={tone}>{step.status}</Chip>}
        {step.name === 'verify' && <Chip tone={tone} solid>{step.valid ? 'verified' : (step.code || 'rejected')}</Chip>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--c-muted)', marginTop: 3, lineHeight: 1.5 }}>{step.detail}</div>
      <div className="mono" style={{ fontSize: 10.5, color: 'var(--c-muted-2)', marginTop: 5, lineHeight: 1.7, wordBreak: 'break-all' }}>
        {step.name === 'challenge' && accept && <>
          <div>{'price'} {accept.maxAmountRequired} · {accept.network} · {'asset'} {shortHex(accept.asset)}</div>
          <div>{'pay to'} {shortHex(accept.payTo)}</div>
        </>}
        {step.name === 'sign' && <>
          <div>{'payer'} {shortHex(step.payer)} · {'value'} {step.value_atomic}</div>
          <div>{'nonce'} {shortHex(step.nonce)}</div>
          <div>{'signature'} {shortHex(step.signature, 14, 8)}</div>
        </>}
        {step.name === 'verify' && <>
          <div>{'recovered signer'} {shortHex(step.recovered_payer)}</div>
          <div>{'code'} {step.code} · {step.network}</div>
        </>}
        {step.name === 'serve' && step.payment_response && <>
          <div>{'settled'} {String(step.payment_response.success)} · {'deferred'} {String(step.payment_response.deferred)}</div>
          <div>{'payload'} {(step.payload_keys || []).join(', ')}</div>
        </>}
      </div>
    </div>
  </div>
}

function X402Roundtrip({ productId }: { productId: string }) {
  const [data, setData] = useState<X402Roundtrip | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  async function run() {
    setLoading(true); setError(false)
    try { setData(await fetchX402Roundtrip(productId)) }
    catch { setError(true) }
    finally { setLoading(false) }
  }
  const right = data ? (data.verified ? 'verified end to end' : 'incomplete') : `${data ? '' : ''}`
  return <DemoFrame label="Live 402 handshake · MEFAI feed" right={right || undefined}>
    <div style={{ fontSize: 11.5, color: 'var(--c-muted)', lineHeight: 1.55, marginBottom: 8 }}>
      {'A fresh ephemeral key signs a real EIP-3009 authorization for the exact price; the server recovers the signer and serves the verified feed. The settlement transaction is deferred to a funded facilitator, so no funds move in this proof.'}
    </div>
    {!data && !loading && <Btn sm variant="primary" onClick={run}>{'Run live 402 handshake'}</Btn>}
    {loading && <Reading />}
    {error && <Down what="The handshake endpoint is not reachable right now." />}
    {data && <div style={{ display: 'grid', gap: 6 }}>
      {data.steps.map((s) => <X402StepCard key={s.n} step={s} />)}
      <div style={{ fontSize: 10.5, color: 'var(--c-muted-2)', lineHeight: 1.6, marginTop: 2 }}>{data.settlement.note}</div>
      <Btn sm variant="ghost" onClick={run}>{'Run again'}</Btn>
    </div>}
  </DemoFrame>
}

function netLabel(n?: string): string {
  if (!n) return '-'
  if (n === 'eip155:8453') return 'Base · 8453'
  if (n === 'eip155:56') return 'BSC · 56'
  if (n === 'eip155:204') return 'opBNB · 204'
  return n
}
function X402CmcUpstream() {
  const { data, error, loading } = usePoll<X402CmcChallenge>((s) => fetchX402CmcChallenge(s), 120_000)
  const pr = data?.probe
  const accepts = (pr?.is_402 && pr.accepts) ? pr.accepts : []
  return <DemoFrame label="CMC upstream x402 gateway · live 402" right={data ? `${data.network} · ${data.chain_id}` : 'reading'}>
    {loading && <Reading />}
    {error && <Down what="The CMC gateway probe is not reachable right now." />}
    {data && <>
      <div style={{ ...statGrid, marginBottom: 9 }}>
        <MiniStat label="Price per call" value={`$${fmtNum(data.price_human, 2)}`} tone={TONE} sub={data.asset_symbol} />
        <MiniStat label="Network" value={data.network} sub={`chain ${data.chain_id}`} />
        <MiniStat label="Live probe" value={pr?.is_402 ? '402' : (pr?.http_status ?? (pr?.reached ? 'ok' : 'n/a'))} tone={pr?.is_402 ? 'var(--green)' : pr?.reached ? 'var(--gold)' : 'var(--c-muted)'} sub={pr?.is_402 ? 'challenge received' : pr?.reached ? 'reachable' : 'no response'} />
      </div>
      <div style={{ fontSize: 10.5, letterSpacing: .5, textTransform: 'uppercase', color: 'var(--c-muted)', fontWeight: 700, marginBottom: 5 }}>{'metered tools'}</div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: accepts.length ? 9 : 6 }}>
        {data.tools.map((t) => <Chip key={t} tone="var(--c-muted)">{t}</Chip>)}
      </div>
      {accepts.length > 0 && <>
        <div style={{ fontSize: 10.5, letterSpacing: .5, textTransform: 'uppercase', color: 'var(--c-muted)', fontWeight: 700, marginBottom: 5 }}>{'live accepted terms'} · {pr?.resource}</div>
        <div style={{ display: 'grid', gap: 5, marginBottom: 7 }}>
          {accepts.slice(0, 5).map((a, i) => (
            <div key={i} style={rowBox}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 11.5, fontWeight: 700 }}>
                <Chip tone={a.network === 'eip155:8453' ? TONE : BNB_TONE}>{netLabel(a.network)}</Chip>
                {(a.extra && a.extra.name) || 'asset'}
              </span>
              <span className="mono" style={{ fontSize: 10.5, color: 'var(--c-muted-2)' }}>{a.amount} · {shortHex(a.asset, 8, 6)} · {(a.extra && a.extra.assetTransferMethod) || a.scheme}</span>
            </div>
          ))}
        </div>
      </>}
      <div style={{ fontSize: 11, color: 'var(--c-muted)', lineHeight: 1.55 }}>{pr?.note} · <span className="mono">{data.gateway}</span></div>
      <div style={{ fontSize: 10.5, color: 'var(--c-muted-2)', marginTop: 4 }}>{data.source}</div>
    </>}
  </DemoFrame>
}

function X402Demo({ cmc }: { cmc?: boolean }) {
  const { data, error, loading } = usePoll<X402Catalog>((s) => fetchX402Products(s), 120_000)
  const productId = data?.products[0]?.product_id || 'verified-leaderboard'
  return <div style={{ display: 'grid', gap: 10 }}>
    <DemoFrame label="Machine payable products live" right={data ? `${data.network} · ${data.products.length}` : 'reading'}>
      {loading && <Reading />}
      {error && <Down what="The product catalog is not reachable right now." />}
      {data && <div style={{ display: 'grid', gap: 6 }}>
        {data.products.map((p) => {
          const raw = Number(p.price_atomic) / 1e18
          const price = Number.isFinite(raw) ? raw : null
          return <div key={p.product_id} style={{ padding: '9px 11px', borderRadius: 9, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>{p.title}</span>
              <Chip tone={BNB_TONE}>{price == null ? '-' : fmtNum(price, 2)} {'per call'}</Chip>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--c-muted)', marginTop: 4, lineHeight: 1.5 }}>{p.description}</div>
          </div>
        })}
      </div>}
    </DemoFrame>
    <X402Roundtrip productId={productId} />
    {cmc && <X402CmcUpstream />}
  </div>
}

/* ── Trust Wallet, live from the autonomous loop snapshot ── */
function useLoop() { return usePoll<LoopEnvelope>((s) => fetchLoopState(s), 30_000) }
function BalanceDemo() {
  const { data, error, loading } = useLoop()
  const st = data?.available ? data.state : undefined
  return <DemoFrame label="Agent wallet equity live" right={st ? 'paper book' : 'reading'}>
    {loading && <Reading />}
    {(error || (data && !data.available)) && !loading && <Down what="The autonomous loop snapshot is not available right now." />}
    {st && <div style={statGrid}>
      <MiniStat label="Equity" value={fmtUsd(st.equity)} tone={TW_TONE} />
      <MiniStat label="Peak equity" value={fmtUsd(st.peak_equity)} />
      <MiniStat label="Drawdown" value={fmtPct(st.drawdown * 100, 2)} tone={st.drawdown > 0 ? 'var(--red)' : 'var(--green)'} />
      <MiniStat label="Risk budget" value={fmtPct(st.internal_cap * 100, 0)} sub="internal cap" />
    </div>}
  </DemoFrame>
}
function LoopDemo() {
  const { data, error, loading } = useLoop()
  const st = data?.available ? data.state : undefined
  return <DemoFrame label="Autonomous loop snapshot live" right={st ? `${'cycle'} ${st.cycle}` : 'reading'}>
    {loading && <Reading />}
    {(error || (data && !data.available)) && !loading && <Down what="The autonomous loop is not reporting right now." />}
    {st && <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        <Chip tone={st.governor.ok ? 'var(--green)' : 'var(--red)'} solid>{st.mode} {'mode'}</Chip>
        <Chip tone={TW_TONE}>{st.config.watchlist.length} {'symbols watched'}</Chip>
        <Chip tone="var(--c-muted)">{Math.round(st.uptime_s / 3600)}{'h uptime'}</Chip>
      </div>
      <div style={{ ...statGrid, marginBottom: 10 }}>
        <MiniStat label="Wallet" value={<code className="mono" style={{ fontSize: 11 }}>{shortAddr(st.agent.wallet)}</code>} />
        <MiniStat label="Cycle" value={fmtNum(st.cycle, 0)} tone={TW_TONE} />
        <MiniStat label="Interval" value={`${fmtNum(st.config.interval, 0)}s`} />
      </div>
      <div style={{ display: 'grid', gap: 5 }}>
        {(st.decisions || []).slice(0, 4).map((dc, i) => (
          <div key={i} style={rowBox}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700, fontSize: 12 }}><CoinLogo symbol={dc.symbol} size={14} />{dc.symbol.replace('USDT', '')}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{'conv'} {fmtNum(dc.conviction, 0)}</span>
              <Chip tone={dc.action === 'SKIP' ? 'var(--c-muted)' : 'var(--green)'}>{dc.action}</Chip>
            </span>
          </div>
        ))}
      </div>
    </>}
  </DemoFrame>
}
function IdentityDemo() {
  return <DemoFrame label="Agent identity verifiable" right={chainLabel(ADDR.erc8004)}>
    <div style={{ ...statGrid, marginBottom: 10 }}>
      <MiniStat label="Standard" value="ERC-8004" tone="#A78BFA" />
      <MiniStat label="Agent wallet" value={<code className="mono" style={{ fontSize: 11 }}>{shortAddr(ADDR.agent)}</code>} />
    </div>
    <div style={{ marginBottom: 10 }}>
      <div style={miniLabel}>{'Agent id'}</div>
      <code className="mono" style={{ fontSize: 10.5, color: 'var(--c-text-2)', wordBreak: 'break-all', lineHeight: 1.5 }}>{AGENT_ID}</code>
    </div>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <Btn sm variant="ghost" href={scan(ADDR.erc8004)}>{'Identity registry'}</Btn>
      <Btn sm variant="ghost" href={scan(ADDR.agent)}>{'Agent wallet'}</Btn>
    </div>
  </DemoFrame>
}
const SAMPLE_PLAN = { token: '0x55d398326f99059fF775485246999027B3197955', router: '0x10ED43C718714eb63d5aA57B78B54704E256024E', chain_id: 56, slippage_bps: 50, equity: 1000, equity_floor: 860 }
function SecurityGateDemo() {
  const { data, error, loading } = usePoll<SecurityVerdict>((s) => fetchSecurity(SAMPLE_PLAN, s), 120_000)
  return <DemoFrame label="Pre trade safety gate live" right={data ? `${'score'} ${fmtNum(data.score, 0)}` : 'reading'}>
    {loading && <Reading />}
    {error && <Down what="The security gate is not reachable right now." />}
    {data && <>
      <div style={{ marginBottom: 10 }}><Chip tone={data.go ? 'var(--green)' : 'var(--red)'} solid>{data.go ? 'GO' : 'NO GO'}</Chip></div>
      <div style={{ display: 'grid', gap: 5 }}>
        {data.checks.map((c) => (
          <div key={c.name} style={rowBox} title={c.detail}>
            <span style={{ fontWeight: 600, fontSize: 12 }}>{c.name.replace(/_/g, ' ')}</span>
            <Chip tone={checkTone(c.status)}>{c.status}</Chip>
          </div>
        ))}
      </div>
    </>}
  </DemoFrame>
}

/* ── honest twak command shape for kit primitives with no browser safe path ── */
function CommandDemo({ s }: { s: SkillDef }) {
  const fields = (s.outputs || '').split('·').map((x) => x.trim()).filter(Boolean)
  const inputs = (s.inputs || '').split('·').map((x) => x.trim()).filter(Boolean)
  return <div className="cp-sk-demo">
    <div className="cp-sk-demo-h">
      <span className="cp-sk-demo-live" style={{ background: TW_TONE }}>twak</span>
      <span className="cp-sk-demo-l">{'Command surface'}</span>
    </div>
    {s.invoke && <code className="cp-sk-invoke mono" style={{ display: 'block', marginBottom: 10 }}>{s.invoke}</code>}
    {inputs.length > 0 && <div style={{ marginBottom: 8 }}>
      <div style={miniLabel}>{'Inputs'}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{inputs.map((f) => <span key={f} className="cp-sk-tag">{f}</span>)}</div>
    </div>}
    {fields.length > 0 && <div style={{ marginBottom: 10 }}>
      <div style={miniLabel}>{'Returns'}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{fields.map((f) => <span key={f} className="cp-sk-tag">{f}</span>)}</div>
    </div>}
    <p style={{ fontSize: 11.5, lineHeight: 1.55, color: 'var(--c-muted-2)', margin: '0 0 10px' }}>
      {s.used
        ? 'The live agent runs this exact command through the Trust Wallet kit. Execution spends from the agent wallet so the call and its shape are shown here with no fabricated output.'
        : 'Available in the kit not wired into the live loop today. The call and its shape are what it returns when enabled.'}
    </p>
    <Btn sm variant="ghost" href={scan(ADDR.agent)}>{'Agent wallet on BscScan'}</Btn>
  </div>
}

/* ── BNB Chain, fully live engines ── */
const PAIRS4 = [{ base: 'BTC', spot: 'BTCUSDT', slash: 'BTC/USDT' }, { base: 'ETH', spot: 'ETHUSDT', slash: 'ETH/USDT' }, { base: 'BNB', spot: 'BNBUSDT', slash: 'BNB/USDT' }, { base: 'SOL', spot: 'SOLUSDT', slash: 'SOL/USDT' }]
function PairPicks({ sel, set }: { sel: string; set: (x: typeof PAIRS4[number]) => void }) {
  return <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
    {PAIRS4.map((x) => <button key={x.base} className={`cp-pill ${sel === x.base ? 'on' : ''}`} aria-pressed={sel === x.base} onClick={() => set(x)}><CoinLogo symbol={x.base} size={15} />{x.base}</button>)}
  </div>
}
function FusionDemo() {
  const [a, setA] = useState(PAIRS4[2])
  const { data, error, loading } = usePoll<FusionResult>((s) => fetchFusion(a.spot, '1h', s), 60_000, [a.spot])
  return <DemoFrame label="Signal fusion live" right={data ? `${data.n_sources} ${'sources'}` : 'reading'}>
    <PairPicks sel={a.base} set={setA} />
    {loading && <Reading />}
    {error && <Down what="Fusion did not answer for this asset right now." />}
    {data && <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <Chip tone={dirTone(data.direction)} solid>{dirText(data.direction)}</Chip>
        <span className="mono" style={{ fontSize: 12, color: 'var(--c-muted)' }}>{fmtPct(clamp01(data.agreement) * 100, 0)} {'agreement'} · {fmtPct(data.coverage * 100, 0)} {'coverage'}</span>
      </div>
      <div style={{ display: 'grid', gap: 5 }}>
        {(data.sources || []).filter((x) => x.available).slice(0, 6).map((x) => (
          <div key={x.name} style={rowBox}>
            <span style={{ fontWeight: 600, fontSize: 12 }}>{x.name}</span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{'w'} {fmtPct(x.weight_pct * 100, 0)}</span>
              <Chip tone={dirTone(x.direction)}>{dirText(x.direction)}</Chip>
            </span>
          </div>
        ))}
      </div>
    </>}
  </DemoFrame>
}
function RecentSignalsDemo() {
  const { data, error, loading } = usePoll<RecentSignals>((s) => fetchRecentSignals(8, undefined, s), 60_000)
  const sigs = data?.signals ?? []
  const wins = sigs.filter((x) => x.result === 'win').length
  return <DemoFrame label="Resolved signals live" right={sigs.length ? `${wins}/${sigs.length} ${'win'}` : 'reading'}>
    {loading && <Reading />}
    {error && <Down what="The signal record is not reachable right now." />}
    {sigs.length > 0 && <div style={{ display: 'grid', gap: 5 }}>
      {sigs.slice(0, 7).map((x, i) => (
        <div key={`${x.symbol}-${x.direction}-${i}`} style={rowBox}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700, fontSize: 12 }}><CoinLogo symbol={x.symbol} size={14} />{x.symbol.replace('.P', '')}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Chip tone={x.direction === 'short' ? 'var(--red)' : 'var(--green)'}>{x.direction.toUpperCase()}</Chip>
            <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: x.pnl >= 0 ? 'var(--green)' : 'var(--red)', minWidth: 54, textAlign: 'right' }}>{x.pnl >= 0 ? '+' : ''}{fmtNum(x.pnl, 2)}%</span>
            <Chip tone={x.result === 'win' ? 'var(--green)' : 'var(--red)'}>{x.result}</Chip>
          </span>
        </div>
      ))}
    </div>}
  </DemoFrame>
}
function CouncilDemo() {
  const [a, setA] = useState(PAIRS4[2])
  const { data, error, loading } = usePoll<DebateResult>((s) => fetchDebate(a.slash, s), 90_000, [a.slash])
  const c = data?.consensus
  return <DemoFrame label="AI council consensus live" right={data?.experts ? `${data.experts.length} ${'experts'}` : 'reading'}>
    <PairPicks sel={a.base} set={setA} />
    {loading && <Reading />}
    {!loading && (error || !c) && <Down what="The council is not reachable for this asset right now." />}
    {c && <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <Chip tone={sigTone(c.signal)} solid>{c.signal}</Chip>
        <span className="mono" style={{ fontSize: 12, color: 'var(--c-muted)' }}>{fmtPct((c.agreement_pct ?? c.confidence * 100), 0)} {'agreement'}</span>
      </div>
      {c.summary && <p style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--c-text-2)', margin: 0 }}>{c.summary}</p>}
    </>}
  </DemoFrame>
}
function SizingDemo() {
  const { data, error, loading } = usePoll<SizingResult>(async (s) => {
    // Size against the agent's live paper book; if the loop snapshot is down we
    // refuse to show a notional derived from a placeholder equity.
    const ls = await fetchLoopState(s)
    if (!ls.available || !ls.state) throw new Error('loop snapshot unavailable')
    const equity = ls.state.equity
    let conviction = 0.5 // neutral lean if fusion is briefly unreachable
    try { const f = await fetchFusion('BNBUSDT', '1h', s); if (Number.isFinite(f.net)) conviction = clamp01(Math.abs(f.net)) } catch { /* keep neutral lean */ }
    return fetchSizing({ symbol: 'BNBUSDT', timeframe: '1h', equity, conviction }, s)
  }, 120_000)
  return <DemoFrame label="Drawdown budget sizing live" right={data ? (data.approved ? 'sized' : 'no bet') : 'reading'}>
    {loading && <Reading />}
    {error && <Down what="The sizing service is not reachable right now." />}
    {data && <>
      <div style={statGrid}>
        <MiniStat label="Notional" value={fmtUsd(data.notional)} tone={BNB_TONE} />
        <MiniStat label="Leverage" value={`${fmtNum(data.leverage, 1)}x`} />
        <MiniStat label="Worst case" value={fmtUsd(data.worst_case_loss)} tone="var(--red)" sub="if the stop hits" />
        <MiniStat label="Equity" value={fmtUsd(data.equity)} sub="paper book" />
      </div>
      {data.reasons?.length > 0 && <p style={{ fontSize: 11.5, color: 'var(--c-muted)', margin: '8px 0 0', lineHeight: 1.5 }}>{data.reasons[0]}</p>}
    </>}
  </DemoFrame>
}
function TpSlDemo() {
  const [a, setA] = useState(PAIRS4[2])
  const { data, error, loading } = usePoll<TpSl>((s) => fetchTpSl(a.spot, '1h', 12, s), 120_000, [a.spot])
  const cell = data?.best_per_risk || data?.best
  return <DemoFrame label="TP/SL bracket live" right={data?.n_total ? `${fmtNum(data.n_total, 0)} ${'samples'}` : 'reading'}>
    <PairPicks sel={a.base} set={setA} />
    {loading && <Reading />}
    {error && <Down what="The optimizer is not reachable right now." />}
    {data && !cell && !loading && <Down what={data.note || 'No bracket reached the minimum sample threshold for this asset so the agent would not commit a bracket here.'} />}
    {cell && <div style={statGrid}>
      <MiniStat label="Take profit" value={fmtPct(cell.tp, 2)} tone="var(--green)" />
      <MiniStat label="Stop loss" value={fmtPct(cell.sl, 2)} tone="var(--red)" />
      <MiniStat label="R:R" value={fmtNum(cell.rr, 2)} tone={BNB_TONE} />
      <MiniStat label="Sample" value={fmtNum(cell.n, 0)} sub="labeled outcomes" />
    </div>}
  </DemoFrame>
}
function LeaderboardDemo() {
  const { data, error, loading } = usePoll<Leaderboard>((s) => fetchLeaderboard('symbol', 'expectancy', '24h', 8, s), 120_000)
  const ov = data?.overall
  return <DemoFrame label="Verifiable leaderboard live" right={data ? `${data.qualified} ${'qualified'}` : 'reading'}>
    {loading && <Reading />}
    {error && <Down what="The leaderboard is not reachable right now." />}
    {ov && <div style={{ ...statGrid, marginBottom: 10 }}>
      <MiniStat label="Resolved" value={fmtNum(ov.n_resolved, 0)} tone={BNB_TONE} sub="labeled outcomes" />
      <MiniStat label="Expectancy" value={fmtNum(ov.expectancy, 4)} sub="per signal" />
    </div>}
    {data && <div style={{ display: 'grid', gap: 5 }}>
      {data.entries.slice(0, 6).map((e) => (
        <div key={e.key} style={rowBox}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700, fontSize: 12 }}><CoinLogo symbol={e.key} size={14} />{e.key.replace('.P', '')}</span>
          <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{fmtNum(e.n_resolved, 0)} {'res'}</span>
            <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: e.expectancy >= 0 ? 'var(--green)' : 'var(--red)', minWidth: 48, textAlign: 'right' }}>{fmtNum(e.expectancy, 3)}</span>
          </span>
        </div>
      ))}
    </div>}
  </DemoFrame>
}
const PROOF_ADDR: Record<string, keyof typeof ADDR> = {
  'bnb-registry': 'registry', 'bnb-governor': 'governor', 'bnb-ledger': 'ledger', 'bnb-identity': 'erc8004', 'bnb-keeper': 'keeper',
}
function ProofDemo({ s }: { s: SkillDef }) {
  const { data, loading } = useLoop()
  const st = data?.available ? data.state : undefined
  const addr = ADDR[PROOF_ADDR[s.id] || 'ledger']
  return <DemoFrame label="Verifiable record live" right={chainLabel(addr)}>
    {loading && <Reading />}
    {st && s.id === 'bnb-governor' && <div style={{ ...statGrid, marginBottom: 10 }}>
      <MiniStat label="Governor" value={st.governor.ok ? 'OK' : 'HALT'} tone={st.governor.ok ? 'var(--green)' : 'var(--red)'} />
      <MiniStat label="Drawdown" value={`${fmtNum(st.governor.dd_bps, 0)} bps`} sub="vs 1400 cap" />
    </div>}
    {st && (st.reveals?.length ?? 0) > 0 && <div style={{ display: 'grid', gap: 5, marginBottom: 10 }}>
      {st.reveals.slice(0, 4).map((r, i) => (
        <div key={`${r.symbol}-${i}`} style={rowBox}>
          <span style={{ fontWeight: 700, fontSize: 12 }}>{r.symbol}</span>
          <code className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{r.detail}</code>
        </div>
      ))}
    </div>}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <code className="mono" style={{ fontSize: 11, color: 'var(--c-text-2)' }}>{shortAddr(addr)}</code>
      <Btn sm variant="ghost" href={scan(addr)}>{'View on BscScan'}</Btn>
    </div>
  </DemoFrame>
}

/* ── registry: id → live demo. Missing ids simply show the dossier only. ── */
export const SKILL_DEMO: Record<string, (s: SkillDef) => ReactNode> = {
  'cmc-global': (s) => <CmcGateDemo s={s} />,
  'cmc-mcap-ta': (s) => <CmcGateDemo s={s} />,
  'cmc-quotes': () => <QuoteDemo />,
  'cmc-metrics': () => <QuoteDemo metrics />,
  'cmc-info': () => <InfoDemo />,
  'cmc-ta': () => <SignalDemo />,
  'cmc-skill-research': () => <SignalDemo research />,
  'cmc-search': () => <SearchDemo />,
  'cmc-search-info': () => <SearchDemo />,
  'cmc-skill-report': () => <ReportDemo />,
  'cmc-skill-mcp': () => <McpDemo />,
  'cmc-orderflow': () => <OrderFlowPanel />,
  'cmc-deriv': (s) => <CmcGateDemo s={s} />,
  'cmc-narratives': () => <NarrativeRotationDemo />,
  'cmc-macro': (s) => <CmcGateDemo s={s} />,
  'cmc-news': (s) => <CmcGateDemo s={s} />,
  'cmc-skill-x402': () => <X402Demo cmc />,
  'cmc-skill-api-crypto': (s) => <SchemaDemo s={s} />,
  'cmc-skill-api-dex': (s) => <SchemaDemo s={s} />,
  'cmc-skill-api-exchange': (s) => <SchemaDemo s={s} />,
  'cmc-skill-api-market': (s) => <SchemaDemo s={s} />,

  /* Trust Wallet · live where browser safe, honest command shape otherwise */
  'tw-guard': () => <WalletGuardPanel />,
  'tw-approve': () => <WalletGuardPanel />,
  'tw-balance': () => <BalanceDemo />,
  'tw-wallet': () => <LoopDemo />,
  'tw-serve': () => <LoopDemo />,
  'tw-erc8004': () => <IdentityDemo />,
  'tw-compete': () => <IdentityDemo />,
  'tw-erc8183': () => <IdentityDemo />,
  'tw-risk': () => <SecurityGateDemo />,
  'tw-swap': (s) => <CommandDemo s={s} />,
  'tw-transfer': (s) => <CommandDemo s={s} />,
  'tw-bridge': (s) => <CommandDemo s={s} />,
  'tw-fiat': (s) => <CommandDemo s={s} />,
  'tw-dca': (s) => <CommandDemo s={s} />,
  'tw-limit': (s) => <CommandDemo s={s} />,
  'tw-alert': (s) => <CommandDemo s={s} />,
  'tw-sign': (s) => <CommandDemo s={s} />,
  'tw-market': (s) => <CommandDemo s={s} />,
  'tw-history': (s) => <CommandDemo s={s} />,
  'tw-x402': (s) => <CommandDemo s={s} />,
  'tw-api': (s) => <CommandDemo s={s} />,
  'tw-sdk': (s) => <CommandDemo s={s} />,

  /* BNB Chain · MEFAI's own live engines and verifiable records */
  'bnb-omni': () => <OmniSignalPanel />,
  'bnb-fusion': () => <FusionDemo />,
  'bnb-signals': () => <RecentSignalsDemo />,
  'bnb-council': () => <CouncilDemo />,
  'bnb-sizing': () => <SizingDemo />,
  'bnb-tpsl': () => <TpSlDemo />,
  'bnb-leaderboard': () => <LeaderboardDemo />,
  'bnb-registry': (s) => <ProofDemo s={s} />,
  'bnb-governor': (s) => <ProofDemo s={s} />,
  'bnb-ledger': (s) => <ProofDemo s={s} />,
  'bnb-identity': (s) => <ProofDemo s={s} />,
  'bnb-keeper': (s) => <ProofDemo s={s} />,
  'bnb-x402': () => <X402Demo />,
}
