/* BNB HACK competition sub-site shell.
   A tiny pathname router (history pushState) with a sticky nav, a 3-palette
   theme switcher, a font picker, a mobile drawer and a footer. Everything
   lives under .compete-root so its theme never touches the terminal. */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import './compete.css'
import { GITHUB_URL } from './config'
import {
  BrandLogo, IconMenu, IconClose, IconPalette, IconType, IconLang, IconCheck, IconCaret,
} from './icons'

// Each page is a separate chunk so a first visit only downloads the page it lands on.
const Landing = lazy(() => import('./pages/Landing'))
const AgentCockpit = lazy(() => import('./pages/AgentCockpit'))
const SkillStudio = lazy(() => import('./pages/SkillStudio'))
const Protocol = lazy(() => import('./pages/Protocol'))
const SkillOrchestra = lazy(() => import('./pages/SkillOrchestra'))
const Docs = lazy(() => import('./pages/Docs'))
const JudgeMode = lazy(() => import('./pages/JudgeMode'))
const TrustWallet = lazy(() => import('./pages/TrustWallet'))
const CoinMarketCap = lazy(() => import('./pages/CoinMarketCap'))
const BnbChain = lazy(() => import('./pages/BnbChain'))

const NAV = [
  { path: '/compete', label: 'Overview' },
  { path: '/compete/agent', label: 'Live Agent' },
  { path: '/compete/skills', label: 'Strategy Skills' },
  { path: '/compete/protocol', label: 'Protocol' },
  { path: '/compete/orchestra', label: 'AI Council' },
  { path: '/compete/judge', label: 'Judge Mode' },
  { path: '/compete/docs', label: 'Docs' },
]
const STACK = [
  { path: '/compete/trust', label: 'Trust Wallet' },
  { path: '/compete/cmc', label: 'CoinMarketCap' },
  { path: '/compete/bnb', label: 'BNB Chain' },
]
const THEMES: { id: string; label: string; swatch: string }[] = [
  { id: 'ocean', label: 'Daylight', swatch: '#0071c2' },
  { id: 'midnight', label: 'Midnight', swatch: '#0a1322' },
]
const FONTS: { id: string; label: string }[] = [
  { id: 'inter', label: 'Inter' },
  { id: 'plex', label: 'IBM Plex Sans' },
  { id: 'system', label: 'System UI' },
  { id: 'serif', label: 'Serif' },
]
const LANGS: { id: string; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'tr', label: 'Turkish' },
  { id: 'es', label: 'Español' },
  { id: 'zh', label: '中文' },
]

function normalize(p: string) {
  const path = p.replace(/\/+$/, '') || '/compete'
  return path.startsWith('/compete') ? path : '/compete'
}

function usePref(key: string, fallback: string, valid: string[]) {
  const [val, setVal] = useState(() => {
    try { const v = localStorage.getItem(key); if (v && valid.includes(v)) return v } catch { /* ignore */ }
    return fallback
  })
  const set = useCallback((v: string) => {
    setVal(v)
    try { localStorage.setItem(key, v) } catch { /* ignore */ }
  }, [key])
  return [val, set] as const
}

export default function CompeteApp() {
  const [path, setPath] = useState(() => normalize(window.location.pathname))
  const [theme, setTheme] = usePref('mefai_compete_theme', 'ocean', THEMES.map((t) => t.id))
  const [font, setFont] = usePref('mefai_compete_font', 'inter', FONTS.map((f) => f.id))
  const [lang, setLang] = usePref('mefai_compete_lang', 'en', LANGS.map((l) => l.id))
  const [menu, setMenu] = useState<null | 'theme' | 'font' | 'lang' | 'stack'>(null)
  const [drawer, setDrawer] = useState(false)
  const navRef = useRef<HTMLDivElement>(null)

  const go = useCallback((to: string) => {
    const next = normalize(to)
    window.history.pushState({}, '', next)
    setPath(next)
    setDrawer(false)
    setMenu(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    const onPop = () => setPath(normalize(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // close popovers on outside click / escape
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (navRef.current && !navRef.current.contains(e.target as Node)) setMenu(null) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(null); setDrawer(false) } }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [])

  const render = () => {
    switch (path) {
      case '/compete/agent': return <AgentCockpit go={go} />
      case '/compete/skills': return <SkillStudio go={go} />
      case '/compete/protocol': return <Protocol go={go} />
      case '/compete/orchestra': return <SkillOrchestra go={go} />
      case '/compete/judge': return <JudgeMode go={go} />
      case '/compete/docs': return <Docs go={go} />
      case '/compete/trust': return <TrustWallet go={go} />
      case '/compete/cmc': return <CoinMarketCap go={go} />
      case '/compete/bnb': return <BnbChain go={go} />
      default: return <Landing go={go} />
    }
  }

  const track = path === '/compete/agent' ? 'agent' : ''

  return <div className="compete-root" data-theme={theme} data-font={font} data-lang={lang} data-track={track}>
    {/* ════════ sticky nav ════════ */}
    <nav className="cp-nav">
      <div ref={navRef} style={{ position: 'relative', maxWidth: 1320, margin: '0 auto', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => go('/compete')} style={{ background: 'none', border: 0, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, padding: 0 }} aria-label="MEFAI home">
          <BrandLogo height={26} dark />
          <span className="cp-nav-desktop cp-nav-brand-tag" style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: 1, marginLeft: 2 }}>BNB HACK</span>
        </button>

        {/* desktop links */}
        <div className="cp-nav-desktop" style={{ flex: 1, display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', alignItems: 'center' }}>
          {NAV.map((n) => (
            <span key={n.path} className={`cp-navlink ${path === n.path ? 'active' : ''}`} onClick={() => go(n.path)}>{n.label}</span>
          ))}
          <div style={{ position: 'relative' }}>
            <span className={`cp-navlink ${STACK.some((s) => s.path === path) ? 'active' : ''}`} onClick={() => setMenu(menu === 'stack' ? null : 'stack')} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              Built with
              <IconCaret dir={menu === 'stack' ? 'up' : 'down'} size={14} />
            </span>
            {menu === 'stack' && <div className="cp-pop" style={{ left: '50%', transform: 'translateX(-50%)' }}>
              <div className="cp-pop-label">Sponsor stacks</div>
              {STACK.map((s) => (
                <button key={s.path} className={`cp-pop-row ${path === s.path ? 'on' : ''}`} onClick={() => go(s.path)}>
                  {s.label}{path === s.path && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
                </button>
              ))}
            </div>}
          </div>
        </div>

        {/* right controls */}
        <div className="cp-nav-desktop" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ position: 'relative' }}>
            <button className="cp-iconbtn" onClick={() => setMenu(menu === 'theme' ? null : 'theme')} title="Color theme" aria-label="Color theme"><IconPalette /></button>
            {menu === 'theme' && <div className="cp-pop">
              <div className="cp-pop-label">Color theme</div>
              {THEMES.map((t) => (
                <button key={t.id} className={`cp-pop-row ${theme === t.id ? 'on' : ''}`} onClick={() => { setTheme(t.id); setMenu(null) }}>
                  <span className="cp-swatch" style={{ background: t.swatch }} />{t.label}
                  {theme === t.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
                </button>
              ))}
            </div>}
          </div>
          <div style={{ position: 'relative' }}>
            <button className="cp-iconbtn" onClick={() => setMenu(menu === 'font' ? null : 'font')} title="Typeface" aria-label="Typeface"><IconType /></button>
            {menu === 'font' && <div className="cp-pop">
              <div className="cp-pop-label">Typeface</div>
              {FONTS.map((f) => (
                <button key={f.id} className={`cp-pop-row ${font === f.id ? 'on' : ''}`} onClick={() => { setFont(f.id); setMenu(null) }}>
                  {f.label}{font === f.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
                </button>
              ))}
            </div>}
          </div>
          <div style={{ position: 'relative' }}>
            <button className="cp-iconbtn" onClick={() => setMenu(menu === 'lang' ? null : 'lang')} title="Language" aria-label="Language">
              <IconLang />
              <span style={{ fontSize: 12.5, fontWeight: 700 }}>{(LANGS.find((l) => l.id === lang)?.id || 'en').toUpperCase()}</span>
            </button>
            {menu === 'lang' && <div className="cp-pop">
              <div className="cp-pop-label">Language</div>
              {LANGS.map((l) => (
                <button key={l.id} className={`cp-pop-row ${lang === l.id ? 'on' : ''}`} onClick={() => { setLang(l.id); setMenu(null) }}>
                  {l.label}{lang === l.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
                </button>
              ))}
            </div>}
          </div>
          <a className="btn btn-primary btn-sm" href={GITHUB_URL} target="_blank" rel="noopener noreferrer" style={{ flexShrink: 0 }}>Source</a>
        </div>

        {/* mobile toggle */}
        <div className="cp-nav-mobile" style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
          <button className="cp-iconbtn" onClick={() => setDrawer(true)} aria-label="Open menu"><IconMenu /></button>
        </div>
      </div>
    </nav>

    {/* ════════ mobile drawer ════════ */}
    <div className={`cp-drawer ${drawer ? 'open' : ''}`}>
      <div className="cp-drawer-scrim" onClick={() => setDrawer(false)} />
      <div className="cp-drawer-panel">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <BrandLogo height={24} />
          <button className="cp-iconbtn" onClick={() => setDrawer(false)} aria-label="Close menu"><IconClose /></button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {NAV.map((n) => (
            <span key={n.path} className={`cp-navlink ${path === n.path ? 'active' : ''}`} style={{ padding: '11px 12px', fontSize: 15 }} onClick={() => go(n.path)}>{n.label}</span>
          ))}
          <div className="cp-pop-label">Built with</div>
          {STACK.map((n) => (
            <span key={n.path} className={`cp-navlink ${path === n.path ? 'active' : ''}`} style={{ padding: '11px 12px', fontSize: 15 }} onClick={() => go(n.path)}>{n.label}</span>
          ))}
        </div>
        <div className="cp-pop-label">Color theme</div>
        {THEMES.map((t) => (
          <button key={t.id} className={`cp-pop-row ${theme === t.id ? 'on' : ''}`} onClick={() => setTheme(t.id)}>
            <span className="cp-swatch" style={{ background: t.swatch }} />{t.label}
            {theme === t.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
          </button>
        ))}
        <div className="cp-pop-label">Typeface</div>
        {FONTS.map((f) => (
          <button key={f.id} className={`cp-pop-row ${font === f.id ? 'on' : ''}`} onClick={() => setFont(f.id)}>
            {f.label}{font === f.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
          </button>
        ))}
        <div className="cp-pop-label">Language</div>
        {LANGS.map((l) => (
          <button key={l.id} className={`cp-pop-row ${lang === l.id ? 'on' : ''}`} onClick={() => setLang(l.id)}>
            {l.label}{lang === l.id && <IconCheck size={16} style={{ marginLeft: 'auto' }} />}
          </button>
        ))}
        <a className="btn btn-primary" href={GITHUB_URL} target="_blank" rel="noopener noreferrer" style={{ marginTop: 14, width: '100%' }}>Source code</a>
      </div>
    </div>

    <Suspense fallback={<div className="cp-route-loading" aria-busy="true"><span className="cp-spinner" /></div>}>
      {render()}
    </Suspense>

    {/* ════════ footer ════════ */}
    <footer className="cp-footer">
      <div className="cp-foot-grid" />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1320, margin: '0 auto', padding: '52px 22px 26px' }}>
        <div className="cp-foot-cols" style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 1.6fr) repeat(3, minmax(130px, 1fr))', gap: 32 }}>
          {/* brand column */}
          <div>
            <BrandLogo height={26} />
            <p style={{ fontSize: 13.5, color: 'var(--c-text-2)', lineHeight: 1.65, margin: '16px 0 0', maxWidth: 360 }}>
              The verifiable autonomous trader. Every call is sealed to the BSC ledger before the outcome is known and a chain anchored circuit breaker makes the risk cap unbreakable.
            </p>
            <div style={{ marginTop: 18 }}>
              <a className="btn btn-primary btn-sm" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">Open source</a>
            </div>
          </div>
          {/* product column */}
          <div>
            <div className="cp-foot-col-h">Product</div>
            {NAV.map((n) => <span key={n.path} className="cp-foot-link" onClick={() => go(n.path)}>{n.label}</span>)}
          </div>
          {/* built with column */}
          <div>
            <div className="cp-foot-col-h">Built with</div>
            {STACK.map((n) => <span key={n.path} className="cp-foot-link" onClick={() => go(n.path)}>{n.label}</span>)}
          </div>
          {/* resources column */}
          <div>
            <div className="cp-foot-col-h">Resources</div>
            <span className="cp-foot-link" onClick={() => go('/compete/docs')}>Documentation</span>
            <a className="cp-foot-link" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
            <span className="cp-foot-link" onClick={() => go('/compete/protocol')}>Verifiable protocol</span>
            <span className="cp-foot-link" onClick={() => go('/compete/orchestra')}>AI council</span>
          </div>
        </div>
        <div style={{ marginTop: 36, paddingTop: 20, borderTop: '1px solid var(--c-line)', display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--c-muted)' }}>MEFAI · BNB HACK: AI Trading Agent Edition</span>
          <span style={{ fontSize: 12, color: 'var(--c-muted)' }}>Built to bring the power of AI to trading · does not constitute financial advice.</span>
        </div>
      </div>
    </footer>
  </div>
}
