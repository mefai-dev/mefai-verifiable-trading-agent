/* Shared layout primitives for the three "what we built with X" pages
   (Trust Wallet, CoinMarketCap, BNB Chain). Keeps them visually consistent
   while each keeps its own brand tone and content. */

import type { ReactNode } from 'react'
import { Btn, Card, Reveal } from '../ui'
import { IconExternal } from '../icons'
import { GITHUB_URL } from '../config'

function Eyebrow({ tone, children }: { tone?: string; children: ReactNode }) {
  const c = tone || 'var(--c-accent)'
  return <span style={{
    display: 'inline-block',
    fontSize: 11.5, fontWeight: 800, letterSpacing: '.14em', textTransform: 'uppercase',
    color: c,
  }}>
    {children}
  </span>
}

export function SponsorHero({ tone, eyebrow, title, blurb, go }: {
  tone: string; eyebrow?: string; title: ReactNode; blurb: string; go: (p: string) => void
}) {
  return <section style={{ position: 'relative', overflow: 'hidden', padding: '56px 22px 30px' }}>
    <div className="cp-mesh"><div className="cp-grid-bg" /></div>
    <div style={{ position: 'relative', zIndex: 1, maxWidth: 980, margin: '0 auto' }}>
      <Reveal>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Btn variant="ghost" sm onClick={() => go('/compete')}>{'Home'}</Btn>
          <Btn variant="primary" sm href={GITHUB_URL}>{'Open source'}</Btn>
        </div>
      </Reveal>
      {eyebrow && <Reveal delay={50}><div style={{ marginTop: 16 }}><Eyebrow tone={tone}>{eyebrow}</Eyebrow></div></Reveal>}
      <Reveal delay={70}>
        <h1 style={{ fontSize: 'clamp(30px,5vw,54px)', fontWeight: 900, letterSpacing: '-1.1px', margin: eyebrow ? '6px 0 0' : '18px 0 0', lineHeight: 1.06 }}>{title}</h1>
      </Reveal>
      <Reveal delay={140}>
        <p style={{ maxWidth: 720, marginTop: 14, fontSize: 'clamp(14.5px,1.5vw,17px)', lineHeight: 1.65, color: 'var(--c-text-2)' }}>{blurb}</p>
      </Reveal>
    </div>
  </section>
}

export function FeatureGrid({ tone, items }: {
  tone: string; items: { t: string; d: string }[]
}) {
  return <section style={{ maxWidth: 1180, margin: '0 auto', padding: '20px 22px' }}>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
      {items.map((f, i) => (
        <Reveal key={f.t} delay={(i % 3) * 70}>
          <Card hover style={{ padding: 22, height: '100%' }}>
            <span style={{ display: 'block', width: 26, height: 4, borderRadius: 999, background: tone, marginBottom: 16 }} />
            <h3 style={{ fontSize: 17, fontWeight: 800, margin: '0 0 8px' }}>{f.t}</h3>
            <p style={{ fontSize: 13.5, lineHeight: 1.62, color: 'var(--c-text-2)', margin: 0 }}>{f.d}</p>
          </Card>
        </Reveal>
      ))}
    </div>
  </section>
}

export function PlainContract({ tone, label, plain, addr, scanUrl, chain }: {
  tone: string; label: string; plain: string; addr: string; scanUrl: string; chain?: string
}) {
  void addr
  const testnet = chain === 'BSC testnet'
  return <a className="cp-a" href={scanUrl} target="_blank" rel="noopener noreferrer"
    style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 16, borderRadius: 12, background: 'var(--c-panel)', border: '1px solid var(--c-line)', textDecoration: 'none', height: '100%' }}>
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 9, height: 9, borderRadius: 3, background: tone, flexShrink: 0 }} />
      <span style={{ fontSize: 14.5, fontWeight: 800, color: 'var(--c-text)' }}>{label}</span>
      {chain && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: testnet ? 'var(--gold)' : 'var(--green)' }}>{chain}</span>}
    </span>
    <span style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--c-text-2)' }}>{plain}</span>
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: tone, marginTop: 'auto', paddingTop: 6 }}>
      {'View on'} {testnet ? 'testnet BscScan' : 'BscScan'} <IconExternal size={13} />
    </span>
  </a>
}

export function SponsorSectionHead({ tone, eyebrow, title, sub }: { tone?: string; eyebrow?: string; title: ReactNode; sub?: string }) {
  return <div style={{ maxWidth: 980, margin: '0 auto', padding: '40px 22px 4px' }}>
    {eyebrow && <Eyebrow tone={tone}>{eyebrow}</Eyebrow>}
    <h2 style={{ fontSize: 'clamp(23px,3.1vw,34px)', fontWeight: 900, letterSpacing: '-.7px', margin: eyebrow ? '7px 0 0' : 0 }}>{title}</h2>
    {sub && <p style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--c-text-2)', margin: '8px 0 0', maxWidth: 720 }}>{sub}</p>}
  </div>
}
