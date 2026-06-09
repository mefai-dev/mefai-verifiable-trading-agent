/* BNB HACK · the CoinMarketCap Intelligence band.
   The whole CMC hub, read at once, distilled into one market-context lean that
   feeds the Omni Signal decision. Six live gates land in parallel · sentiment
   (Fear and Greed + altcoin season + dominance), derivatives (open interest +
   funding + volume), trending narratives, market-wide technicals, upcoming
   macro events, and the latest news. A transparent composite blends the live
   numeric regime signals (Fear and Greed, market RSI, MACD, BTC dominance, perp
   funding) into a single 0-100 reading; every figure is the gate's own value and
   any gate that does not answer says so. Nothing here is mocked. */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchCmcGate } from '../api'
import type { CmcGate } from '../api'
import { Gauge, Chip, fmtPct } from '../ui'

type Stage = { data: CmcGate | null; error: boolean; loading: boolean }
const idle = (): Stage => ({ data: null, error: false, loading: true })

/* "+58.02%" / "-3.25%" / "23.59" -> number (NaN-safe) */
function pctNum(s: unknown): number {
  if (typeof s === 'number') return s
  if (typeof s !== 'string') return NaN
  const m = s.replace(/[, ]/g, '').match(/-?\d+(\.\d+)?/)
  return m ? parseFloat(m[0]) : NaN
}
const has = (n: number) => Number.isFinite(n)

/* CMC table gates return parallel headers[] + rows[]; resolve a column by its
   header name so a reordered column never shifts the read. When the gate sends a
   real header row we trust the name (returning -1, i.e. skip the field, if it was
   renamed away) rather than reading a stale ordinal as truth; the positional
   fallback is used only when the gate omits headers entirely. */
function colAt(headers: unknown, name: string, fallback: number): number {
  if (Array.isArray(headers) && headers.length) return headers.indexOf(name)
  return fallback
}

/* ─────────────── gate parsers (defensive, real values only) ─────────────── */
type Sentiment = {
  fgIndex: number; fgLabel: string; fgWeek: number
  altIndex: number; altChg: number
  btcDom: number; btcDomWeek: number
  mcap: string; mcap24: number
}
function parseSentiment(g: CmcGate | null): Sentiment | null {
  const d = g?.data
  if (!d) return null
  const fg = d.sentiment?.fear_greed
  const alt = d.rotation?.altcoin_season
  const dom = d.dominance?.btc
  const mc = d.market_size?.total_crypto_market_cap_usd
  if (!fg && !alt && !dom) return null
  return {
    fgIndex: pctNum(fg?.current?.index), fgLabel: fg?.current?.value || '',
    fgWeek: pctNum(fg?.history?.last_week?.index),
    altIndex: pctNum(alt?.current?.index), altChg: pctNum(alt?.percent_change?.['7d']),
    btcDom: pctNum(dom?.current), btcDomWeek: pctNum(dom?.history?.last_week),
    mcap: mc?.current || '', mcap24: pctNum(mc?.percent_change?.['24h']),
  }
}

type Derivs = { oi: string; oi24: number; funding: number; funding24: number; perpVol: string }
function parseDerivs(g: CmcGate | null): Derivs | null {
  const d = g?.data
  if (!d) return null
  const oi = d.totalOpenInterest
  const fr = d.fundingRate
  if (!oi && !fr) return null
  return {
    oi: oi?.current || '', oi24: pctNum(oi?.percentage_change_24h),
    funding: pctNum(fr?.current), funding24: pctNum(fr?.percentage_change_24h),
    perpVol: d.perpetuals?.volume?.total_usd_24h || '',
  }
}

type Narrative = { name: string; mcap: string; chg24: number; coins: string[] }
function parseNarratives(g: CmcGate | null): Narrative[] | null {
  const cl = g?.data?.categoryList
  const rows = cl?.rows
  if (!Array.isArray(rows) || !rows.length) return null
  const h = cl.headers
  const iName = colAt(h, 'categoryName', 3)
  const iMc = colAt(h, 'marketCapUsd', 4)
  const iChg = colAt(h, 'marketCapChangePercentage24h', 5)
  const iTop = colAt(h, 'topCoinList', 17)
  const out: Narrative[] = []
  for (const r of rows.slice(0, 5)) {
    const name = String(r?.[iName] ?? '')
    if (!name) continue
    const coins: string[] = []
    const tc = r?.[iTop]?.rows
    if (Array.isArray(tc)) for (const c of tc.slice(0, 3)) if (Array.isArray(c) && c[0]) coins.push(String(c[0]))
    out.push({ name, mcap: String(r?.[iMc] ?? ''), chg24: pctNum(r?.[iChg]), coins })
  }
  return out.length ? out : null
}

type Ta = { rsi14: number; rsi7: number; macdHist: number; pivot: string; mcap: string }
function parseTa(g: CmcGate | null): Ta | null {
  const d = g?.data
  if (!d?.rsi && !d?.macd) return null
  return {
    rsi14: pctNum(d.rsi?.rsi14), rsi7: pctNum(d.rsi?.rsi7),
    macdHist: pctNum(d.macd?.histogram), pivot: d.pivotPoint || '', mcap: d.currentMarketCap || '',
  }
}

type Ev = { title: string; date: string }
function parseMacro(g: CmcGate | null): Ev[] | null {
  const blk = g?.data?.upcomingEventNews
  const rows = blk?.rows
  if (!Array.isArray(rows) || !rows.length) return null
  const iTitle = colAt(blk.headers, 'title', 0)
  const iDate = colAt(blk.headers, 'eventDate', 3)
  return rows.slice(0, 3).map((r: unknown[]) => ({ title: String(r?.[iTitle] ?? ''), date: String(r?.[iDate] ?? '') }))
    .filter((e: Ev) => e.title)
}

type News = { title: string; at: string }
function parseNews(g: CmcGate | null): News[] | null {
  const d = g?.data
  const rows = d?.rows
  if (!Array.isArray(rows) || !rows.length) return null
  const iTitle = colAt(d.headers, 'title', 0)
  const iAt = colAt(d.headers, 'publishedAt', 4)
  return rows.slice(0, 4).map((r: unknown[]) => ({ title: String(r?.[iTitle] ?? ''), at: String(r?.[iAt] ?? '') }))
    .filter((n: News) => n.title)
}

/* ─────────────── the transparent market-context composite ───────────────
   Four numeric CMC regime signals, each mapped to a 0-100 lean (50 = neutral),
   then weighted. Fear and Greed and market RSI are read contrarian (deep fear /
   oversold = a higher bullish lean); the MACD histogram is read with the trend
   (positive = bullish), and falling BTC dominance is read risk-on. The exact
   inputs are shown beside the dial so the number is never a black box. */
type Sub = { key: string; label: string; reading: string; lean: number; ok: boolean }
function buildContext(sent: Sentiment | null, deriv: Derivs | null, ta: Ta | null): { score: number; subs: Sub[] } {
  const subs: Sub[] = []
  // 1 · Fear and Greed (contrarian)
  if (sent && has(sent.fgIndex)) {
    subs.push({ key: 'fg', label: 'Fear and Greed', reading: `${sent.fgLabel || sent.fgIndex} · ${sent.fgIndex}`,
      lean: 100 - sent.fgIndex, ok: true })
  }
  // 2 · Market RSI 14 (contrarian / mean reversion)
  if (ta && has(ta.rsi14)) {
    subs.push({ key: 'rsi', label: 'Market RSI 14', reading: ta.rsi14.toFixed(1),
      lean: Math.max(0, Math.min(100, 100 - ta.rsi14)), ok: true })
  }
  // 3 · MACD histogram (trend)
  if (ta && has(ta.macdHist)) {
    subs.push({ key: 'macd', label: 'Market MACD', reading: ta.macdHist > 0 ? 'positive' : 'negative',
      lean: ta.macdHist > 0 ? 66 : 34, ok: true })
  }
  // 4 · BTC dominance week trend (risk rotation)
  if (sent && has(sent.btcDom) && has(sent.btcDomWeek)) {
    const falling = sent.btcDom < sent.btcDomWeek
    subs.push({ key: 'dom', label: 'BTC dominance', reading: `${sent.btcDom.toFixed(2)}% ${falling ? 'falling' : 'rising'}`,
      lean: falling ? 60 : 40, ok: true })
  }
  // 5 · Perp funding (positioning) · positive = longs in control, negative = squeeze setup
  if (deriv && has(deriv.funding)) {
    subs.push({ key: 'fund', label: 'Perp funding', reading: deriv.funding > 0 ? 'positive' : deriv.funding < 0 ? 'negative' : 'flat',
      lean: deriv.funding > 0 ? 56 : deriv.funding < 0 ? 44 : 50, ok: true })
  }
  const score = subs.length ? Math.round(subs.reduce((a, s) => a + s.lean, 0) / subs.length) : 50
  return { score, subs }
}
function leanOf(score: number): { t: string; c: string } {
  if (score >= 58) return { t: 'RISK ON LEAN', c: 'var(--green)' }
  if (score <= 42) return { t: 'RISK OFF LEAN', c: 'var(--red)' }
  return { t: 'MIXED', c: 'var(--gold)' }
}

/* ─────────────── tiles ─────────────── */
function Tile({ title, gate, status, children }: { title: string; gate: string; status: ReactNode; children: ReactNode }) {
  return <div className="cp-cmc-tile">
    <div className="cp-cmc-tile-h">
      <span className="cp-cmc-tile-t">{title}</span>
      <span className="cp-cmc-tile-g mono">{gate}</span>
      <span className="cp-cmc-tile-st">{status}</span>
    </div>
    <div className="cp-cmc-tile-b">{children}</div>
  </div>
}
function GateBadge({ s }: { s: Stage }) {
  if (s.loading) return <span className="cp-omni-badge wait">{'sync'}</span>
  if (s.error || !s.data) return <span className="cp-omni-badge off">{'down'}</span>
  return <span className="cp-omni-badge ok">{'live'}</span>
}
function Down() { return <p className="cp-cmc-down">{'This gate did not answer. The other gates and the composite still read.'}</p> }
function Wait() { return <p className="cp-cmc-wait">{'reading'}<span className="cp-ellipsis" /></p> }
function KV({ k, v, tone }: { k: string; v: ReactNode; tone?: string }) {
  return <div className="cp-cmc-kv"><span>{k}</span><b style={tone ? { color: tone } : undefined}>{v}</b></div>
}
const chgTone = (n: number) => (!has(n) ? 'var(--c-text)' : n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--c-muted)')

function SentimentTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const d = parseSentiment(s.data)
  if (s.error || !d) return <Down />
  return <>
    <KV k={'Fear and Greed'} v={`${d.fgLabel || '-'} · ${has(d.fgIndex) ? d.fgIndex : '-'}`}
      tone={has(d.fgIndex) ? (d.fgIndex < 25 ? 'var(--red)' : d.fgIndex > 70 ? 'var(--green)' : 'var(--gold)') : undefined} />
    <KV k={'Altcoin season'} v={has(d.altIndex) ? `${d.altIndex} / 100` : '-'} />
    <KV k={'BTC dominance'} v={has(d.btcDom) ? `${d.btcDom.toFixed(2)}%` : '-'} />
    <KV k={'Total market cap'} v={d.mcap || '-'} tone={chgTone(d.mcap24)} />
  </>
}
function DerivsTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const d = parseDerivs(s.data)
  if (s.error || !d) return <Down />
  return <>
    <KV k={'Open interest'} v={d.oi || '-'} tone={chgTone(d.oi24)} />
    <KV k={'OI 24h'} v={has(d.oi24) ? fmtPct(d.oi24, 2, true) : '-'} tone={chgTone(d.oi24)} />
    <KV k={'Funding rate'} v={has(d.funding) ? d.funding.toFixed(6) : '-'} tone={chgTone(d.funding)} />
    <KV k={'Perp volume 24h'} v={d.perpVol || '-'} />
  </>
}
function NarrativesTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const rows = parseNarratives(s.data)
  if (s.error || !rows) return <Down />
  return <div className="cp-cmc-narr">
    {rows.map((n, i) => <div key={n.name || i} className="cp-cmc-narr-r">
      <span className="cp-cmc-narr-n">{n.name}</span>
      <span className="cp-cmc-narr-c mono" style={{ color: chgTone(n.chg24) }}>{has(n.chg24) ? fmtPct(n.chg24, 2, true) : ''}</span>
      {n.coins.length > 0 && <span className="cp-cmc-narr-x mono">{n.coins.join(' ')}</span>}
    </div>)}
    <div className="cp-cmc-narr-cap">{'trending categories by capital rotation'}</div>
  </div>
}
function TaTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const d = parseTa(s.data)
  if (s.error || !d) return <Down />
  const rsiTone = has(d.rsi14) ? (d.rsi14 < 30 ? 'var(--green)' : d.rsi14 > 70 ? 'var(--red)' : 'var(--gold)') : undefined
  return <>
    <KV k={'Market RSI 14'} v={has(d.rsi14) ? d.rsi14.toFixed(1) : '-'} tone={rsiTone} />
    <KV k={'Market RSI 7'} v={has(d.rsi7) ? d.rsi7.toFixed(1) : '-'} />
    <KV k={'MACD histogram'} v={has(d.macdHist) ? (d.macdHist > 0 ? 'positive' : 'negative') : '-'} tone={chgTone(d.macdHist)} />
    <KV k={'Pivot'} v={d.pivot || '-'} />
  </>
}
function MacroTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const rows = parseMacro(s.data)
  if (s.error || !rows) return <Down />
  return <div className="cp-cmc-feed">
    {rows.map((e, i) => <div key={i} className="cp-cmc-feed-r">
      <span className="cp-cmc-feed-d mono">{e.date}</span>
      <span className="cp-cmc-feed-t">{e.title}</span>
    </div>)}
    <div className="cp-cmc-narr-cap">{'upcoming market moving events'}</div>
  </div>
}
function NewsTile({ s }: { s: Stage }) {
  if (s.loading) return <Wait />
  const rows = parseNews(s.data)
  if (s.error || !rows) return <Down />
  return <div className="cp-cmc-feed">
    {rows.map((n, i) => <div key={i} className="cp-cmc-feed-r">
      <span className="cp-cmc-feed-t">{n.title}</span>
    </div>)}
    <div className="cp-cmc-narr-cap">{'latest market news'}</div>
  </div>
}

/* ─────────────── the band ─────────────── */
const GATES = ['global-metrics', 'derivatives', 'narratives', 'marketcap-ta', 'macro-events', 'news'] as const

export function CmcHubBand() {
  const [g, setG] = useState<Record<string, Stage>>(() =>
    Object.fromEntries(GATES.map((k) => [k, idle()])))
  const runId = useRef(0)

  useEffect(() => {
    const id = ++runId.current
    setG(Object.fromEntries(GATES.map((k) => [k, idle()])))
    for (const tool of GATES) {
      fetchCmcGate(tool)
        .then((d) => { if (id === runId.current) setG((p) => ({ ...p, [tool]: { data: d, error: false, loading: false } })) })
        .catch(() => { if (id === runId.current) setG((p) => ({ ...p, [tool]: { data: null, error: true, loading: false } })) })
    }
  }, [])

  const sent = parseSentiment(g['global-metrics'].data)
  const deriv = parseDerivs(g['derivatives'].data)
  const ta = parseTa(g['marketcap-ta'].data)
  const { score, subs } = buildContext(sent, deriv, ta)
  const anyLive = GATES.some((k) => !g[k].loading && !g[k].error && g[k].data)
  const hasContext = subs.length > 0
  const lean = leanOf(score)

  return <div className="cp-cmc">
    <div className="cp-cmc-head">
      <div className="cp-cmc-head-l">
        <div className="cp-cmc-title">{'CoinMarketCap intelligence'}</div>
        <div className="cp-cmc-sub">{'The whole hub read at once, distilled into one market context the agent trades inside.'}</div>
        {subs.length > 0 && <div className="cp-cmc-subs">
          {subs.map((su) => <span key={su.key} className="cp-cmc-subchip"
            style={{ ['--l' as string]: su.lean >= 58 ? 'var(--green)' : su.lean <= 42 ? 'var(--red)' : 'var(--gold)' }}>
            <em>{su.label}</em><b>{su.reading}</b>
          </span>)}
        </div>}
        <div className="cp-cmc-method">{'Composite blends the live CMC regime signals shown above · Fear and Greed and market RSI read contrarian, MACD with the trend, dominance for rotation, perp funding for positioning. Every input is the gate\u2019s own value.'}</div>
      </div>
      <div className="cp-cmc-dial">
        {hasContext
          ? <Gauge value={score} max={100} label={'market context'} tone={lean.c} size={132}
              sub={'0 risk off · 100 risk on'} />
          : <div className="cp-cmc-dial-wait">{anyLive ? 'waiting on regime signals' : 'reading the hub'}<span className="cp-ellipsis" /></div>}
        {hasContext && <Chip tone={lean.c} solid>{lean.t}</Chip>}
      </div>
    </div>

    <div className="cp-cmc-grid">
      <Tile title={'Sentiment'} gate="global-metrics" status={<GateBadge s={g['global-metrics']} />}>
        <SentimentTile s={g['global-metrics']} /></Tile>
      <Tile title={'Derivatives'} gate="derivatives" status={<GateBadge s={g['derivatives']} />}>
        <DerivsTile s={g['derivatives']} /></Tile>
      <Tile title={'Trending narratives'} gate="narratives" status={<GateBadge s={g['narratives']} />}>
        <NarrativesTile s={g['narratives']} /></Tile>
      <Tile title={'Market technicals'} gate="marketcap-ta" status={<GateBadge s={g['marketcap-ta']} />}>
        <TaTile s={g['marketcap-ta']} /></Tile>
      <Tile title={'Macro events'} gate="macro-events" status={<GateBadge s={g['macro-events']} />}>
        <MacroTile s={g['macro-events']} /></Tile>
      <Tile title={'Latest news'} gate="news" status={<GateBadge s={g['news']} />}>
        <NewsTile s={g['news']} /></Tile>
    </div>
  </div>
}
