/* Shared presentational primitives for the BNB HACK sub-site.
   CMC table structure replicated 1:1; buttons / cards / chips borrow the
   Binance gold, Trust Wallet blue and CoinMarketCap palettes. */

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties, ReactNode } from 'react'
import { IconCaret } from './icons'

/* ─────────────── portal ───────────────
   Modal overlays must escape any transformed ancestor (a `.reveal` keeps a
   non-none transform even when settled, which turns position:fixed into a
   locally positioned box and lets page captions paint over the panel). We mount
   into the `.compete-root` element (which has no transform, so fixed resolves
   against the viewport) rather than <body> so the scoped `.compete-root .cp-*`
   styles still apply; fall back to <body> only if the root is missing. */
export function Portal({ children }: { children: ReactNode }) {
  const [el] = useState(() => (typeof document !== 'undefined' ? document.createElement('div') : null))
  useEffect(() => {
    if (!el) return
    const host = document.querySelector('.compete-root') || document.body
    host.appendChild(el)
    return () => { try { host.removeChild(el) } catch { /* already gone */ } }
  }, [el])
  return el ? createPortal(children, el) : null
}

/* ─────────────── formatters ─────────────── */
export const fmtNum = (n: number | null | undefined, d = 2) =>
  n == null || !Number.isFinite(Number(n)) ? '-' : Number(n).toFixed(d)

export const fmtUsd = (n: number | null | undefined, dp = 2) => {
  if (n == null || !Number.isFinite(Number(n))) return '-'
  const v = Number(n), abs = Math.abs(v), s = v < 0 ? '-' : ''
  if (abs >= 1e12) return `${s}$${(abs / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${s}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${s}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${s}$${(abs / 1e3).toFixed(2)}K`
  return `${s}$${abs.toFixed(dp)}`
}
export const fmtPrice = (n: number | null | undefined) => {
  if (n == null || !Number.isFinite(Number(n))) return '-'
  const v = Number(n)
  const dp = v >= 1000 ? 2 : v >= 1 ? 2 : v >= 0.01 ? 4 : 6
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })}`
}
export const fmtPct = (n: number | null | undefined, d = 2, sign = false) => {
  if (n == null || !Number.isFinite(Number(n))) return '-'
  const v = Number(n)
  return `${sign && v > 0 ? '+' : ''}${v.toFixed(d)}%`
}
export const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
export const shortAddr = (a?: string) => (a && a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a || '-')

/* ─────────────── reveal-on-scroll ─────────────── */
export function Reveal({ children, delay = 0, style, className = '' }: { children: ReactNode; delay?: number; style?: CSSProperties; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver((es) => {
      es.forEach((e) => { if (e.isIntersecting) { setSeen(true); io.disconnect() } })
    }, { threshold: 0.12 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return <div ref={ref} className={`reveal ${seen ? 'in' : ''} ${className}`} style={{ transitionDelay: `${delay}ms`, ...style }}>{children}</div>
}

/* ─────────────── lazy mount on scroll ───────────────
   The skill catalogs render every capability open, so the live panels could
   all fetch at once. This defers mounting a panel until it is near the
   viewport, which staggers the work and pairs with the api.ts cache so the
   backend is never hit by a wall of simultaneous requests. */
export function LazyMount({ children, minHeight = 96, rootMargin = '260px' }: { children: ReactNode; minHeight?: number; rootMargin?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [show, setShow] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver((es) => {
      es.forEach((e) => { if (e.isIntersecting) { setShow(true); io.disconnect() } })
    }, { rootMargin })
    io.observe(el)
    return () => io.disconnect()
  }, [rootMargin])
  return <div ref={ref} style={show ? undefined : { minHeight }}>{show ? children : null}</div>
}

/* ─────────────── star rain backdrop ─────────────── */
export function StarField({ count = 30, tone = 'var(--c-primary)' }: { count?: number; tone?: string }) {
  const stars = useRef<{ l: number; d: number; dur: number; s: number; o: number; x: number }[]>(undefined)
  if (!stars.current) {
    stars.current = Array.from({ length: count }, () => ({
      l: Math.random() * 100, d: Math.random() * 10, dur: 7 + Math.random() * 9,
      s: 1 + Math.random() * 2.2, o: 0.25 + Math.random() * 0.55, x: (Math.random() - 0.5) * 60,
    }))
  }
  return <div className="cp-stars" aria-hidden="true">
    {stars.current.map((st, i) => (
      <i key={i} style={{
        left: `${st.l}%`, width: st.s, height: st.s, background: tone,
        animationDelay: `${st.d}s`, animationDuration: `${st.dur}s`,
        ['--so' as string]: st.o, ['--sx' as string]: `${st.x}px`,
      } as CSSProperties} />
    ))}
  </div>
}

/* ─────────────── count-up ─────────────── */
export function CountUp({ value, decimals = 0, prefix = '', suffix = '', dur = 1100 }: { value: number; decimals?: number; prefix?: string; suffix?: string; dur?: number }) {
  const target = Number.isFinite(value) ? value : 0
  const [v, setV] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver((es) => {
      es.forEach((e) => {
        if (e.isIntersecting && !started.current) {
          started.current = true
          const t0 = performance.now()
          const loop = (t: number) => {
            const p = clamp01((t - t0) / dur)
            const e2 = 1 - Math.pow(1 - p, 3)
            setV(target * e2)
            if (p < 1) requestAnimationFrame(loop)
          }
          requestAnimationFrame(loop)
        }
      })
    }, { threshold: 0.4 })
    io.observe(el)
    return () => io.disconnect()
  }, [target, dur])
  return <span ref={ref} className="mono">{prefix}{v.toFixed(decimals)}{suffix}</span>
}

/* ─────────────── buttons ─────────────── */
type BtnVariant = 'primary' | 'gold' | 'amber' | 'cmc' | 'trust' | 'ghost'
export function Btn({ children, variant = 'primary', sm, onClick, href, disabled, style, title }: {
  children: ReactNode; variant?: BtnVariant; sm?: boolean; onClick?: () => void; href?: string; disabled?: boolean; style?: CSSProperties; title?: string
}) {
  const cls = `btn btn-${variant}${sm ? ' btn-sm' : ''}`
  if (href) return <a className={cls} href={href} target={href.startsWith('http') ? '_blank' : undefined} rel="noopener noreferrer" style={style} title={title}>{children}</a>
  return <button className={cls} onClick={onClick} disabled={disabled} style={style} title={title}>{children}</button>
}

/* ─────────────── card / panel ─────────────── */
export function Card({ children, hover, glow, style, className = '' }: { children: ReactNode; hover?: boolean; glow?: string; style?: CSSProperties; className?: string }) {
  return <div className={`card ${hover ? 'card-hover' : ''} ${glow ? 'card-glow' : ''} ${className}`} style={{ ...(glow ? { ['--glow' as any]: glow } : {}), ...style }}>{children}</div>
}
export function Panel({ title, right, accent, help, children, style }: { title: string; right?: ReactNode; accent?: string; help?: ReactNode; children?: ReactNode; style?: CSSProperties }) {
  const glow = accent ? `color-mix(in srgb, ${accent} 20%, transparent)` : undefined
  const [open, setOpen] = useState(false)
  return <Card className="cp-fx" style={{ padding: '15px 16px', ...(glow ? { ['--glow' as any]: glow } : {}), ...style }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, paddingBottom: 10, marginBottom: 12, borderBottom: '1px solid var(--c-line)' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <span className="panel-title" style={accent ? { color: accent } : undefined}>{title}</span>
        {help && <button className="cp-help" aria-expanded={open} aria-label="explain this panel" onClick={() => setOpen((o) => !o)}>?</button>}
      </span>
      {right && <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{right}</span>}
    </div>
    {help && open && <div className="cp-help-note" style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 10, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)', fontSize: 12.5, lineHeight: 1.6, color: 'var(--c-text-2)' }}>{help}</div>}
    {children}
  </Card>
}

/* ─────────────── stat tile ─────────────── */
export function Stat({ label, value, sub, tone, mono = true }: { label: string; value: ReactNode; sub?: string; tone?: string; mono?: boolean }) {
  return <div className="stat">
    <div className="stat-label">{label}</div>
    <div className={`stat-value ${mono ? 'mono' : ''}`} style={{ color: tone || 'var(--c-text)' }}>{value}</div>
    {sub && <div style={{ marginTop: 4, fontSize: 11, color: 'var(--c-muted)' }}>{sub}</div>}
  </div>
}

/* ─────────────── chip ─────────────── */
export function Chip({ children, tone = 'var(--gold)', solid, live }: { children: ReactNode; tone?: string; solid?: boolean; live?: boolean }) {
  return <span className="chip" style={solid
    ? { background: tone, color: '#fff', boxShadow: `0 3px 10px color-mix(in srgb, ${tone} 25%, transparent)` }
    : { color: tone, background: 'var(--c-fill)', boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${tone} 33%, transparent)` }}>
    {live && <span className="dot" style={{ color: tone, background: tone }} />}
    {children}
  </span>
}

/* ─────────────── bar ─────────────── */
export function Bar({ label, value, max = 100, tone = 'var(--gold)', fmt }: { label: ReactNode; value: number; max?: number; tone?: string; fmt?: (v: number) => string }) {
  const pct = clamp01(value / (max || 1)) * 100
  return <div style={{ marginBottom: 9 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--c-text-2)', marginBottom: 4 }}>
      <span>{label}</span><span className="mono" style={{ color: tone, fontWeight: 700 }}>{fmt ? fmt(value) : fmtNum(value, 1)}</span>
    </div>
    <div style={{ height: 7, borderRadius: 999, background: 'var(--c-fill-2)', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, borderRadius: 999, background: `linear-gradient(90deg, ${tone}, color-mix(in srgb, ${tone} 62%, transparent))`, transition: 'width .6s cubic-bezier(.2,.7,.2,1)' }} />
    </div>
  </div>
}

/* ─────────────── radial gauge ─────────────── */
export function Gauge({ value, label, tone, max = 100, size = 130, sub }: { value: number; label: string; tone: string; max?: number; size?: number; sub?: string }) {
  const r = size / 2 - 11, c = 2 * Math.PI * r, frac = clamp01(value / max)
  const cx = size / 2
  return <div style={{ position: 'relative', width: size, height: size, margin: '0 auto' }}>
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--c-fill-2)" strokeWidth={10} />
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={tone} strokeWidth={10} strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - frac)} style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.2,.7,.2,1)' }} />
    </svg>
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
      <div className="mono" style={{ fontSize: size * 0.22, fontWeight: 800, color: tone }}>{fmtNum(value, value < 10 ? 1 : 0)}</div>
      <div style={{ fontSize: 10, letterSpacing: 1.2, color: 'var(--c-muted)', textTransform: 'uppercase' }}>{label}</div>
      {sub && <div style={{ fontSize: 9.5, color: 'var(--c-muted-2)', marginTop: 2 }}>{sub}</div>}
    </div>
  </div>
}

/* ─────────────── sparkline ─────────────── */
export function Sparkline({ points, color, w = 130, h = 38 }: { points: number[]; color?: string; w?: number; h?: number }) {
  const gid = useId()
  if (!points || points.length < 2) return <span style={{ color: 'var(--c-muted-2)', fontSize: 11 }}>-</span>
  const min = Math.min(...points), max = Math.max(...points), span = max - min || 1
  const stepX = w / (points.length - 1)
  const up = points[points.length - 1] >= points[0]
  const col = color || (up ? 'var(--green)' : 'var(--red)')
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(1)},${(h - ((p - min) / span) * (h - 4) - 2).toFixed(1)}`).join(' ')
  return <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
    <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={col} stopOpacity="0.22" /><stop offset="100%" stopColor={col} stopOpacity="0" /></linearGradient></defs>
    <path d={`${d} L${w},${h} L0,${h} Z`} fill={`url(#${gid})`} />
    <path d={d} fill="none" stroke={col} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

/* ─────────────── CMC pct cell ─────────────── */
export function PctCell({ value, d = 2 }: { value: number | null | undefined; d?: number }) {
  if (value == null || !Number.isFinite(Number(value))) return <span style={{ color: 'var(--c-muted-2)' }}>-</span>
  const v = Number(value)
  if (v === 0) return <span className="cmc-pct" style={{ color: 'var(--c-muted)' }}>{v.toFixed(d)}%</span>
  const up = v > 0
  return <span className={`cmc-pct ${up ? 'pos' : 'neg'}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
    <IconCaret dir={up ? 'up' : 'down'} size={11} strokeWidth={2.4} />{Math.abs(v).toFixed(d)}%
  </span>
}

/* ─────────────── coin logo bubble ─────────────── */
const LOGO_TONES: Record<string, string> = {
  BTC: '#F7931A', ETH: '#627EEA', BNB: '#F0B90B', SOL: '#14F195', XRP: '#23292F',
  DOGE: '#C2A633', ADA: '#0033AD', AVAX: '#E84142', LINK: '#2A5ADA', SUI: '#4DA2FF',
}
/* CoinMarketCap numeric ids for the assets the cockpit shows. When an id is
   known we render the real token logo; anything else falls back to the gradient
   initials, as does any image that fails to load. */
const CMC_IDS: Record<string, number> = {
  BTC: 1, ETH: 1027, BNB: 1839, SOL: 5426, XRP: 52, ADA: 2010, DOGE: 74,
  AVAX: 5805, DOT: 6636, LINK: 1975, MATIC: 3890, TRX: 1958, LTC: 2,
  ATOM: 3794, UNI: 7083, ETC: 1321, FIL: 2280, APT: 21794, ARB: 11841,
  OP: 11840, SUI: 20947, NEAR: 6535, INJ: 7226, SEI: 23149, TIA: 22861,
  PEPE: 24478, WLD: 13502, FET: 3773, RENDER: 5690, RNDR: 5690, AAVE: 7278,
  SHIB: 5994, BCH: 1831, XLM: 512, ICP: 8916, HBAR: 4642,
}
export function CoinLogo({ symbol, size = 28 }: { symbol: string; size?: number }) {
  const base = symbol.replace('.P', '').replace('USDT', '').replace('USD', '').toUpperCase()
  const tone = LOGO_TONES[base] || '#F0B90B'
  const cid = CMC_IDS[base]
  const [failed, setFailed] = useState(false)
  if (cid && !failed) {
    return <img
      src={`https://s2.coinmarketcap.com/static/img/coins/64x64/${cid}.png`}
      alt={base} width={size} height={size} loading="lazy" onError={() => setFailed(true)}
      className="cmc-logo" style={{ width: size, height: size, objectFit: 'cover', background: 'var(--c-fill-2)' }}
    />
  }
  return <span className="cmc-logo" style={{ width: size, height: size, background: `linear-gradient(150deg, ${tone}, color-mix(in srgb, ${tone} 60%, transparent))`, fontSize: size * 0.38 }}>{base.slice(0, 3)}</span>
}

/* ─────────────── generic CMC table ─────────────── */
export type CmcColumn<R> = {
  key: string; header: string; align?: 'l' | 'r'; sticky?: boolean
  /* collapse this column on narrow screens so the core table fits without
     horizontal scroll on phones; the essential columns stay visible. */
  hideSm?: boolean
  sortValue?: (row: R) => number | string
  render: (row: R, i: number) => ReactNode
}
type SortState = { key: string; dir: 'asc' | 'desc' }
export function CmcTable<R>({ columns, rows, empty = 'no data', maxHeight, defaultSort }: {
  columns: CmcColumn<R>[]; rows: R[]; empty?: string; maxHeight?: number; defaultSort?: SortState
}) {
  const [sort, setSort] = useState<SortState | null>(defaultSort ?? null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sortValue) return rows
    const sv = col.sortValue
    const arr = rows.slice()
    arr.sort((a, b) => {
      const va = sv(a), vb = sv(b)
      const r = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb))
      return sort.dir === 'asc' ? r : -r
    })
    return arr
  }, [rows, sort, columns])
  const onSort = (c: CmcColumn<R>) => {
    if (!c.sortValue) return
    setSort((s) => s && s.key === c.key ? { key: c.key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: c.key, dir: 'desc' })
  }
  return <div className="cmc-table-wrap" style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
    <table className="cmc">
      <thead><tr>
        {columns.map((c) => {
          const on = sort?.key === c.key
          return <th key={c.key}
            className={`${c.align === 'l' ? 'l' : ''}${c.sticky ? ' sticky-name' : ''}${c.sortValue ? ' cmc-sortable' : ''}${c.hideSm ? ' cmc-hide-sm' : ''}${on ? ' on' : ''}`}
            onClick={c.sortValue ? () => onSort(c) : undefined}>
            <span className="cmc-th-in">{c.header}{c.sortValue && <IconCaret dir={on ? (sort!.dir === 'asc' ? 'up' : 'down') : 'down'} size={10} strokeWidth={2.4} />}</span>
          </th>
        })}
      </tr></thead>
      <tbody>
        {sorted.length === 0
          ? <tr><td className="l" colSpan={columns.length} style={{ textAlign: 'center', color: 'var(--c-muted)', padding: 34 }}>{empty}</td></tr>
          : sorted.map((row, i) => <tr key={i}>
              {columns.map((c) => <td key={c.key} className={`${c.align === 'l' ? 'l' : ''}${c.hideSm ? ' cmc-hide-sm' : ''}`}>{c.render(row, i)}</td>)}
            </tr>)}
      </tbody>
    </table>
  </div>
}
