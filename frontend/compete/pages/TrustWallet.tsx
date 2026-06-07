/* BNB HACK · what we built with Trust Wallet.
   MEFAI is self custody first: the wallet is the identity, and a pre trade
   safety gate protects the very users Trust Wallet onboards. The gate below is
   live, the same security solver the agent runs before it ever asks to sign. */

import { useCallback, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Btn, Chip, Panel, Reveal, Stat } from '../ui'
import { apiPost } from '../api'
import type { SecurityVerdict } from '../api'
import { GITHUB_URL } from '../config'
import { SponsorHero, FeatureGrid, SponsorSectionHead } from './sponsorKit'
import { SkillCatalog } from './skillCatalog'
import { WalletGuardPanel } from './walletGuard'
import { IconCheck, IconClose } from '../icons'

const TONE = 'var(--trust)'

/* canonical, widely audited BSC tokens the visitor can probe */
const PRESETS: { label: string; token: string }[] = [
  { label: 'USDT', token: '0x55d398326f99059fF775485246999027B3197955' },
  { label: 'WBNB', token: '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c' },
  { label: 'CAKE', token: '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82' },
]
const isAddr = (v: string) => /^0x[a-fA-F0-9]{40}$/.test(v.trim())

export default function TrustWallet({ go }: { go: (p: string) => void }) {
  return <div>
    <SponsorHero
      tone={TONE} eyebrow="Built with Trust Wallet" go={go}
      title={<>Self custody trading<br />and a wallet that <span style={{ color: TONE }}>cannot be drained</span></>}
      blurb="MEFAI never holds your keys. We use Trust Wallet for sign in identity and execution then wrap every move in a safety gate so the same retail users Trust Wallet onboards are protected before they ever sign a malicious transaction."
    />

    <SponsorSectionHead tone={TONE} eyebrow="Try it live" title="The pre trade safety gate" />
    <Reveal>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '0 22px' }}>
        <SafetyGate />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow="Scan a live wallet" title="The MEFAI wallet check"
      sub="The same wallet safety scan the terminal runs. It reads every live ERC-20 allowance a wallet has granted on BSC flags the unlimited and spam approvals that drain self custody wallets and ranks each by the USD it exposes. Real chain data. Revoke runs in the full terminal with your own connected Trust Wallet." />
    <Reveal>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '0 22px' }}>
        <WalletGuardPanel />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow="What we built" title="The wallet is the account" />
    <FeatureGrid tone={TONE} items={[
      { t: 'Wallet sign in no passwords', d: 'You connect Trust Wallet and that address IS your account. No email no password no custody. Tier and history follow the wallet across devices.' },
      { t: 'Signature gated access', d: 'Premium access is unlocked by a time windowed single use signed message. Sessions are stateless HMAC tokens so a leaked link is worthless after minutes.' },
      { t: 'Pre trade safety gate', d: 'Before any spend the agent runs honeypot contract slippage approval preflight and MEV checks. A BLOCK verdict stops the transaction before the wallet is ever asked to sign.' },
      { t: 'Approval drainer radar', d: 'We surveil unlimited approval and drainer patterns so a Trust Wallet user sees the trap highlighted instead of approving it blind.' },
      { t: 'Deep link and WalletConnect', d: 'Connect from mobile Trust Wallet over WalletConnect or jump straight into the cockpit with a deep link. The flow is built for the wallet not bolted on.' },
      { t: 'Verifiable agent identity', d: 'The trading agent itself is a registered ERC-8004 identity on BSC so the wallet you interact with is provably the audited agent not an impostor.' },
    ]} />

    <SponsorSectionHead tone={TONE} eyebrow="The full surface" title="Every Trust Wallet skill catalogued"
      sub="The Agent Kit in full: the three skills and the twak command surface the agent drives. Live cards are wired into the trading loop today; available cards are kit capabilities surfaced as options. Tap any card for how it fits." />
    <SkillCatalog group="trust" tone={TONE} />

    <div style={{ textAlign: 'center', padding: '34px 22px 70px', display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
      <Btn variant="trust" onClick={() => go('/compete/protocol')}>See the safety gate in the protocol</Btn>
      <Btn variant="ghost" href={GITHUB_URL}>Read the source</Btn>
    </div>
  </div>
}

/* ─────────────── live pre trade safety gate ─────────────── */
const EQUITY = 10000
const DD_CAP = 0.14

function SafetyGate() {
  const [token, setToken] = useState(PRESETS[0].token)
  const [amount, setAmount] = useState('1000')
  const [slip, setSlip] = useState('50')
  const [verdict, setVerdict] = useState<SecurityVerdict | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const ctrl = useRef<AbortController | null>(null)

  const evaluate = useCallback(async () => {
    if (!isAddr(token)) { setErr('Enter a valid BSC token address (0x followed by 40 hex characters).'); return }
    const amt = Math.max(1, Number(amount) || 0)
    const slippage = Math.max(1, Math.min(5000, Number(slip) || 50))
    ctrl.current?.abort()
    const c = new AbortController(); ctrl.current = c
    setBusy(true); setErr(''); setVerdict(null)
    try {
      const v = await apiPost<SecurityVerdict>('/security/evaluate', {
        token: token.trim(), chain_id: 56, slippage_bps: slippage,
        trade_amount: amt, min_out: amt * (1 - slippage / 10000), expected_out: amt,
        equity: EQUITY, equity_floor: EQUITY * (1 - DD_CAP),
      }, c.signal)
      if (!c.signal.aborted) setVerdict(v)
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') setErr('The safety gate is busy. Try again shortly.')
    } finally {
      if (!c.signal.aborted) setBusy(false)
    }
  }, [token, amount, slip])

  const go = verdict?.go
  return <Panel title="PRE TRADE SAFETY GATE" accent="#3375BB" right={verdict ? `score ${verdict.score}` : 'self custody'}>
    {/* controls */}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      {PRESETS.map((p) => (
        <button key={p.label} className={`cp-pill ${token === p.token ? 'on' : ''}`} onClick={() => setToken(p.token)}>{p.label}</button>
      ))}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(0,1fr) minmax(0,1fr) auto', gap: 10, alignItems: 'end' }} className="cp-grid-form">
      <Field label="BSC token address">
        <input value={token} onChange={(e) => setToken(e.target.value)} spellCheck={false}
          placeholder="0x…" className="mono" style={inputStyle} />
      </Field>
      <Field label="Trade amount (USD)">
        <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} inputMode="decimal" style={inputStyle} />
      </Field>
      <Field label="Slippage (bps)">
        <input value={slip} onChange={(e) => setSlip(e.target.value.replace(/[^\d]/g, ''))} inputMode="numeric" style={inputStyle} />
      </Field>
      <Btn variant="trust" onClick={evaluate} disabled={busy} style={{ width: '100%', justifyContent: 'center' }}>{busy ? 'Checking…' : 'Run the gate'}</Btn>
    </div>
    {err && <div style={{ color: 'var(--red)', fontSize: 12.5, marginTop: 10 }}>{err}</div>}

    {/* verdict */}
    {verdict && <div style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
        <div style={{ width: 60, height: 60, borderRadius: 15, display: 'flex', alignItems: 'center', justifyContent: 'center', background: go ? 'rgba(22,199,132,.14)' : 'rgba(234,57,67,.14)', boxShadow: `inset 0 0 0 1px ${go ? 'var(--green)' : 'var(--red)'}` }}>
          {go ? <IconCheck size={28} color="var(--green)" strokeWidth={2.6} /> : <IconClose size={28} color="var(--red)" strokeWidth={2.6} />}
        </div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, color: go ? 'var(--green)' : 'var(--red)' }}>{go ? 'GO · safe to sign' : 'BLOCK · do not sign'}</div>
          <div style={{ fontSize: 12.5, color: 'var(--c-muted)', maxWidth: 420 }}>{verdict.detail || 'The agent would let this transaction proceed.'}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 4 }}>
        {(verdict.checks ?? []).filter((c) => (c.status || '').toLowerCase() !== 'skip').map((c) => {
          const s = (c.status || '').toLowerCase()
          const t = s === 'pass' ? 'var(--green)' : s === 'warn' ? 'var(--gold)' : (s === 'fail' || s === 'block') ? 'var(--red)' : 'var(--c-muted)'
          const lbl = c.status
          return <div key={c.name} style={{ padding: '10px 12px', borderRadius: 10, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--c-text-2)', textTransform: 'capitalize' }}>{c.name.replace(/_/g, ' ')}</span>
              <Chip tone={t} solid>{lbl}</Chip>
            </div>
            {c.detail && <div style={{ fontSize: 11.5, color: 'var(--c-muted)', marginTop: 6, lineHeight: 1.5 }}>{c.detail}</div>}
          </div>
        })}
      </div>

      {verdict.blockers && verdict.blockers.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--red)' }}>Blockers · {verdict.blockers.join(' · ')}</div>
      )}
      {verdict.warnings && verdict.warnings.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--gold)' }}>Warnings · {verdict.warnings.join(' · ')}</div>
      )}
    </div>}

    {!verdict && !busy && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 16 }}>
      <Stat label="Checks run" value="6" tone={TONE} sub="per transaction" />
      <Stat label="Verdict" value="GO / BLOCK" tone="var(--c-text)" sub="before any sign" />
      <Stat label="Custody" value="Self" tone="var(--green)" sub="keys stay with you" />
      <Stat label="Chain" value="BSC 56" tone="var(--gold)" sub="mainnet" />
    </div>}

    <div style={{ fontSize: 11, color: 'var(--c-muted-2)', marginTop: 14 }}>
      Honeypot · contract · slippage · approval · preflight · MEV. The agent runs this exact gate and stops on a BLOCK verdict before your wallet is ever asked to sign.
    </div>
  </Panel>
}

const inputStyle: CSSProperties = {
  width: '100%', padding: '10px 12px', borderRadius: 9, border: '1px solid var(--c-line-2)',
  background: 'var(--c-panel)', color: 'var(--c-text)', fontSize: 13.5, fontFamily: 'inherit', outline: 'none',
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0 }}>
    <span style={{ fontSize: 10.5, letterSpacing: .6, color: 'var(--c-muted)', textTransform: 'uppercase', fontWeight: 700 }}>{label}</span>
    {children}
  </label>
}
