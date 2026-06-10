/* Landing · the product, presented plainly.
   Hero, the live agent heartbeat, the stack we build on, the system surfaces,
   how it stays honest and safe, the agent's sealed calls, and the proof links.
   No competition framing, no kicker labels: just the product. */

import { Btn, Card, CountUp, Reveal, Stat, StarField, fmtNum, shortAddr } from '../ui'
import { apiGet, usePoll } from '../api'
import type { Leaderboard, LoopEnvelope } from '../api'
import { ADDR, AGENT_ID, AGENT_CARD_URL, COMPETITION, GITHUB_URL, SPONSORS, TRACKS, scan, chainOf, txHashOf } from '../config'
import { SPONSOR_LOGO, IconExternal } from '../icons'
import { CapabilityWeb } from './capabilityWeb'

const cleanSym = (s: string) => s.replace('USDT.P', '').replace('USDT', '').replace('.P', '') || s
// Commit / reveal seals are written to the mainnet registry during the judged window.
// commit_tx may arrive as a full BscScan URL, so normalize to a bare hash first
const txUrl = (h: string) => `https://bscscan.com/tx/${txHashOf(h)}`
const isTx = (h?: string) => /^0x[0-9a-fA-F]{6,}/.test(txHashOf(h))

export default function Landing({ go }: { go: (p: string) => void }) {
  const { data: lb } = usePoll<Leaderboard>((s) => apiGet('/leaderboard?rank_by=expectancy&min_samples=30&top_n=12', s), 60_000)
  const { data: wlb } = usePoll<Leaderboard>((s) => apiGet('/leaderboard?rank_by=win_rate&min_samples=50&top_n=3', s), 60_000)
  const { data: loop } = usePoll<LoopEnvelope>((s) => apiGet('/loop/state', s), 15_000)

  const ov = lb?.overall
  const top = wlb?.entries?.[0]
  const st = loop?.available ? loop.state : undefined
  const ddBps = st ? Math.round(st.drawdown * 10000) : 0
  const capBps = st ? Math.round(st.jury_cap * 10000) : 2000
  const exp = ov?.expectancy ?? 0

  return <div>
    {/* ════════ HERO ════════ */}
    <section style={{ position: 'relative', overflow: 'hidden', padding: '92px 22px 60px' }}>
      <div className="cp-mesh">
        <div className="cp-wash" />
        <div className="cp-grid-bg" />
        <div className="cp-orbs">
          <span className="cp-orb" style={{ width: 360, height: 360, left: '6%', top: '-8%', background: 'var(--c-primary)', opacity: .22, animationDelay: '0s' }} />
          <span className="cp-orb" style={{ width: 300, height: 300, right: '8%', top: '2%', background: 'var(--cmc)', opacity: .18, animationDelay: '3s' }} />
          <span className="cp-orb" style={{ width: 240, height: 240, left: '42%', top: '38%', background: 'var(--gold-2)', opacity: .12, animationDelay: '6s' }} />
        </div>
      </div>

      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1040, margin: '0 auto', textAlign: 'center' }}>
        <Reveal>
          <h1 style={{ fontSize: 'clamp(38px, 6vw, 72px)', lineHeight: 1.04, fontWeight: 900, letterSpacing: '-1.6px', margin: 0 }}>
            <span className="cp-grad-text">{'MEFAI Verifiable'}</span><br />
            <span style={{ color: 'var(--c-text)' }}>{'Autonomous Trader'}</span>
          </h1>
        </Reveal>
        <Reveal delay={120}>
          <p style={{ maxWidth: 680, margin: '22px auto 0', fontSize: 'clamp(15px,1.5vw,18px)', lineHeight: 1.65, color: 'var(--c-text-2)' }}>
            {'An agent that proves every trade before it happens and cannot breach its own risk cap. One conviction engine fuses every MEFAI signal, sizes with a drawdown budget and writes a commit then reveal proof to the BSC ledger.'}
          </p>
        </Reveal>
        <Reveal delay={210}>
          <div style={{ display: 'flex', gap: 11, flexWrap: 'wrap', justifyContent: 'center', marginTop: 32 }}>
            <Btn variant="primary" onClick={() => go('/compete/agent')}>{'Enter the live agent'}</Btn>
            <Btn variant="amber" onClick={() => go('/compete/judge')}>{'Judge mode · verify in 5 min'}</Btn>
            <Btn variant="ghost" onClick={() => go('/compete/orchestra')}>{'Talk to the AI council'}</Btn>
            <Btn variant="ghost" href={GITHUB_URL}>{'Open source'}</Btn>
          </div>
        </Reveal>

        {/* live heartbeat strip · honest headline metrics */}
        <Reveal delay={290}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(155px,1fr))', gap: 12, marginTop: 50, maxWidth: 940, marginLeft: 'auto', marginRight: 'auto' }}>
            <Stat label={'Agent equity'} value={st ? <CountUp value={st.equity} decimals={0} prefix="$" /> : '-'} tone="var(--c-primary)" sub={st ? `${'peak'} $${(st.peak_equity ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : 'standby'} />
            <Stat label={'Live drawdown'} value={`${ddBps} bps`} tone={ddBps >= capBps * 0.9 ? 'var(--red)' : 'var(--green)'} sub={`${'cap'} ${capBps} bps`} />
            <Stat label={'Edge per signal'} value={ov ? `${exp >= 0 ? '+' : ''}${fmtNum(exp, 2)} R` : '-'} tone={exp >= 0 ? 'var(--green)' : 'var(--red)'} sub={'mean realized'} />
            <Stat label={'Top strategy edge'} value={top ? `${top.expectancy >= 0 ? '+' : ''}${fmtNum(top.expectancy, 3)} R` : '-'} tone={top && top.expectancy >= 0 ? 'var(--green)' : 'var(--cmc)'} sub={top ? `${cleanSym(top.key)} · ${top.n_resolved} ${'resolved'}` : 'edge base'} />
            <Stat label={'Labeled outcomes'} value={ov ? <CountUp value={ov.n_resolved} /> : '-'} tone="var(--trust)" sub={'off-chain edge base · on-chain proofs in Judge mode'} />
          </div>
        </Reveal>
      </div>
    </section>

    {/* ════════ STACK · scrolling brand logos ════════ */}
    <section style={{ padding: '30px 0 34px', borderTop: '1px solid var(--c-line)', borderBottom: '1px solid var(--c-line)', background: 'var(--c-bg-soft)' }}>
      <div style={{ textAlign: 'center', fontSize: 12, letterSpacing: 1.2, textTransform: 'uppercase', color: 'var(--c-muted)', fontWeight: 800, marginBottom: 22 }}>{'The stack we build on'}</div>
      <div className="marquee">
        <div className="marquee-track">
          {[...SPONSORS, ...SPONSORS].map((s, i) => {
            const Logo = SPONSOR_LOGO[s.name]
            return <span key={`${s.name}-${i}`} className="stack-tile" aria-hidden={i >= SPONSORS.length}>
              <span className="stack-logo">
                {s.img
                  ? <img src={s.img} alt={`${s.name} logo`} loading="lazy" />
                  : Logo ? <span style={{ color: s.tone, display: 'inline-flex' }}><Logo size={24} /></span> : null}
              </span>
              {s.name}
            </span>
          })}
        </div>
      </div>
    </section>

    {/* ════════ THE THREE SURFACES · centered, star rain backdrop ════════ */}
    <section style={{ position: 'relative', overflow: 'hidden', padding: '64px 22px 30px' }}>
      <StarField count={34} />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1080, margin: '0 auto' }}>
        <Reveal><SectionHead title={'One system three surfaces'} sub={'The same verifiable engine exposed three ways. Open any surface to use it live.'} /></Reveal>
        <div className="cp-deck" style={{ marginTop: 34, maxWidth: 1100, marginLeft: 'auto', marginRight: 'auto' }}>
          {TRACKS.map((t, i) => (
            <Reveal key={t.id} delay={i * 80}>
              <Card hover className="cp-tilt" style={{ padding: 28, height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', ['--glow' as string]: `color-mix(in srgb, ${t.tone} 22%, transparent)` }}>
                <span className="cp-tilt-bar" style={{ display: 'block', width: 30, height: 4, borderRadius: 999, background: t.tone, marginBottom: 18, boxShadow: `0 0 16px ${t.tone}` }} />
                <h3 style={{ fontSize: 22, fontWeight: 800, margin: '0 0 11px', letterSpacing: '-.3px' }}>{t.title}</h3>
                <p style={{ fontSize: 14.5, lineHeight: 1.62, color: 'var(--c-text-2)', flex: 1, margin: 0 }}>{t.blurb}</p>
                <div style={{ marginTop: 22 }}>
                  <Btn variant="ghost" sm onClick={() => go(t.path)}>{'Open'}</Btn>
                </div>
              </Card>
            </Reveal>
          ))}
        </div>
      </div>
    </section>

    {/* ════════ CAPABILITY WEB · cross sponsor flow ════════ */}
    <section style={{ maxWidth: 1180, margin: '0 auto', padding: '52px 22px 16px' }}>
      <Reveal><SectionHead nowrap title={'Three sponsors one trade'} sub={"The same flow behind every call: CoinMarketCap data converges into MEFAI's decision engine, executes through Trust Wallet and settles as proof on BNB Chain. Tap any node to open its dossier."} /></Reveal>
      <Reveal delay={70}>
        <CapabilityWeb />
      </Reveal>
    </section>

    {/* ════════ HONEST AND SAFE · no icons ════════ */}
    <section style={{ maxWidth: 1180, margin: '0 auto', padding: '52px 22px 22px' }}>
      <Reveal><SectionHead nowrap title={'Built so it cannot cheat and cannot exceed its risk cap'} sub={'Every guarantee below is structural not a promise. You can audit each one yourself.'} /></Reveal>
      <div className="cp-deck" style={{ marginTop: 30, maxWidth: 1160, marginLeft: 'auto', marginRight: 'auto' }}>
        {[
          { t: 'Commit before reveal', d: 'Each trade is committed as keccak(symbol direction entry target stop expiry salt) to the BSC registry before entry then revealed after. The track record cannot be backfilled by construction.' },
          { t: 'Circuit breaker on the ledger', d: 'A RiskGovernor contract enforces a 1400 bps drawdown cap. When equity breaches the budget the vault halts and canTrade returns false. The agent cannot exceed its own risk limit.' },
          { t: 'Empirical Kelly sizing', d: 'Win rate and optimal TP/SL come from real labeled outcomes not guesses. Size shrinks as the drawdown budget shrinks so the agent maximizes Sharpe while it physically cannot breach the cap.' },
          { t: 'Omni signal fusion', d: 'One conviction score unions every MEFAI capability: signals, expert debate, whale tracking, smart money, accumulation, derivatives risk and the full CoinMarketCap regime, each weighted by its own hit rate.' },
          { t: 'Pre trade security gate', d: 'Honeypot, contract scan, slippage, approval, preflight and MEV checks run before any spend. A GO or BLOCK verdict gates execution. Every spend is quote bounded and capped.' },
          { t: 'x402 machine payable', d: 'The verified signal feed is served over HTTP 402 with EIP-3009 signed payment binding the exact token and chain charged. Agents can pay other agents for proven alpha.' },
        ].map((f, i) => (
          <Reveal key={f.t} delay={(i % 3) * 70}>
            <Card hover className="cp-tilt" style={{ padding: 24, height: '100%', textAlign: 'center' }}>
              <h4 style={{ fontSize: 17, fontWeight: 800, margin: '0 0 9px' }}>{f.t}</h4>
              <p style={{ fontSize: 14, lineHeight: 1.62, color: 'var(--c-text-2)', margin: 0 }}>{f.d}</p>
            </Card>
          </Reveal>
        ))}
      </div>
    </section>

    {/* ════════ THE AGENT'S SEALED CALLS ════════ */}
    <section style={{ maxWidth: 1080, margin: '0 auto', padding: '52px 22px 22px' }}>
      <Reveal><SectionHead title={"The agent's sealed calls"} sub={'What the agent is acting on right now, each one committed to the registry before the outcome is known.'} /></Reveal>
      <Reveal delay={70}>
        {st && st.decisions?.length > 0 ? (
          <div className="cp-grid-4" style={{ marginTop: 30 }}>
            {st.decisions.filter((d) => /[a-z0-9]/i.test(cleanSym(d.symbol || ''))).slice(0, 8).map((d) => {
              const isLong = d.action.includes('LONG'), isShort = d.action.includes('SHORT')
              const acting = isLong || isShort
              const tone = isLong ? 'var(--green)' : isShort ? 'var(--red)' : 'var(--c-muted)'
              const label = isLong ? 'Long' : isShort ? 'Short' : 'No trade'
              const pf = st.proofs?.find((p) => p.symbol === d.symbol)
              return <Card key={d.symbol} hover className="cp-tilt" style={{ padding: 20, ['--glow' as string]: `color-mix(in srgb, ${tone} 20%, transparent)` }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <span style={{ fontWeight: 800, fontSize: 22, letterSpacing: '-.4px' }}>{cleanSym(d.symbol)}</span>
                  <span style={{ fontSize: 13, fontWeight: 800, color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)`, padding: '5px 12px', borderRadius: 8 }}>{label}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
                  <span style={{ color: 'var(--c-muted)', fontSize: 13.5 }}>{'Conviction'}</span>
                  <span className="mono" style={{ fontWeight: 800, fontSize: 18, color: acting ? tone : 'var(--c-text)' }}>{d.conviction.toFixed(0)}</span>
                </div>
                {isTx(pf?.commit_tx) ? (
                  <a className="cp-a" href={txUrl(pf!.commit_tx)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--c-primary)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    {'Sealed proof'} <IconExternal size={14} />
                  </a>
                ) : <span style={{ fontSize: 13.5, color: 'var(--c-muted)' }}>{acting ? <>{'Sealing to registry'}<span className="cp-ellipsis" /></> : 'Held this cycle'}</span>}
              </Card>
            })}
          </div>
        ) : (
          <Card style={{ padding: 26, marginTop: 30, textAlign: 'center' }}>
            <p style={{ fontSize: 15, color: 'var(--c-text-2)', margin: 0, lineHeight: 1.62 }}>
              {'The agent is on standby between cycles. Live calls are written to the registry the moment a cycle opens, and the verified record above is the evidence base every decision is sized against.'}
            </p>
          </Card>
        )}
      </Reveal>
    </section>

    {/* ════════ VERIFIABLE PROOF ════════ */}
    <section style={{ maxWidth: 1080, margin: '0 auto', padding: '52px 22px 30px' }}>
      <Reveal><SectionHead title={'Audit the proof yourself'} sub={'Every contract and identity below is deployed and verified on BSC mainnet. The result ledger, the identity, the live judged registry and the risk governor all run on chain 56. One tap opens it in the explorer.'} /></Reveal>
      <Reveal delay={70}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 14, marginTop: 30 }}>
          {[
            ['Prediction registry', ADDR.registry], ['Risk governor', ADDR.governor],
            ['Agent wallet', ADDR.agent], ['Oracle keeper', ADDR.keeper],
            ['Result ledger', ADDR.ledger], ['ERC-8004 identity', ADDR.erc8004],
          ].map(([label, addr]) => {
            const testnet = chainOf(addr) === 97
            return <a key={label} className="cp-a card card-hover" href={scan(addr)} target="_blank" rel="noopener noreferrer"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, padding: '16px 18px', textDecoration: 'none' }}>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 14.5, color: 'var(--c-text)', fontWeight: 700 }}>{label}</span>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: testnet ? 'var(--gold)' : 'var(--green)' }}>{testnet ? 'testnet' : 'mainnet'}</span>
                </span>
                <span className="mono" style={{ fontSize: 14, color: 'var(--c-text-2)', fontWeight: 600 }}>{shortAddr(addr)}</span>
              </span>
              <span style={{ color: 'var(--c-primary)', flexShrink: 0, display: 'inline-flex' }}><IconExternal size={18} /></span>
            </a>
          })}
        </div>
        <div className="mono" style={{ marginTop: 18, fontSize: 13, color: 'var(--c-muted)', textAlign: 'center' }}>
          commit id {shortAddr(AGENT_ID)} · {'mainnet identity · contracts source verified on BscScan'}
        </div>
        <div style={{ marginTop: 14, display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', fontSize: 13, color: 'var(--c-text-2)' }}>
          <span>{'Registered for'} {COMPETITION}.</span>
          <a className="cp-a" href={AGENT_CARD_URL} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontWeight: 700, color: 'var(--c-primary)' }}>
            {'Read the live ERC-8004 agent card'} <IconExternal size={14} />
          </a>
        </div>
      </Reveal>
    </section>

    <div style={{ height: 36 }} />
  </div>
}

function SectionHead({ title, sub, nowrap }: { title: string; sub?: string; nowrap?: boolean }) {
  return <div style={{ maxWidth: nowrap ? 1000 : 760, margin: '0 auto', textAlign: 'center' }}>
    <h2 className={nowrap ? 'cp-sec-1line' : undefined} style={{ fontSize: 'clamp(26px,3.3vw,40px)', fontWeight: 900, letterSpacing: '-.8px', margin: 0 }}>{title}</h2>
    {sub && <p style={{ fontSize: 15.5, lineHeight: 1.6, color: 'var(--c-text-2)', margin: '12px 0 0' }}>{sub}</p>}
  </div>
}
