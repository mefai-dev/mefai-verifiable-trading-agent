/* BNB HACK · MEFAI wallet approval guard, surfaced as a Trust Wallet feature.
   This is the same wallet safety check the MEFAI terminal runs: it reads every
   live ERC-20 allowance a wallet has granted on BSC, flags unlimited approvals
   and possible-spam tokens, and ranks each by the USD it puts at risk. Real
   Moralis-backed chain data, no fabrication. Trade execution lives in Trust
   Wallet, so the same self custody users get their approval surface audited
   before an exploit can drain it. The compete site is read only: revoke runs in
   the full terminal with the visitor's own connected Trust Wallet. */

import { useCallback, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Btn, Chip, Panel, Stat, CountUp, fmtUsd } from '../ui'
import { fetchWalletGuard } from '../api'
import type { WalletGuard, ApprovalSeverity } from '../api'

const TONE = 'var(--trust)'
const isAddr = (v: string) => /^0x[a-fA-F0-9]{40}$/.test(v.trim())
const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`

/* documented public entity + a sample wallet, so a judge sees a real, populated
   approval surface without connecting their own keys */
const PRESETS: { label: string; addr: string }[] = [
  { label: 'Binance hot wallet', addr: '0xF977814e90dA44bFA03b6295A0616a897441aceC' },
  { label: 'Sample wallet', addr: '0x161bA15a5f335c9f06BB5Bbb0A9cE14076FBb645' },
]

const SEV_TONE: Record<ApprovalSeverity, string> = {
  high: 'var(--red)', medium: 'var(--gold)', low: 'var(--c-muted)',
}
const SEV_LABEL: Record<ApprovalSeverity, string> = {
  high: 'high risk', medium: 'review', low: 'low',
}

export function WalletGuardPanel() {
  const [addr, setAddr] = useState(PRESETS[0].addr)
  const [report, setReport] = useState<WalletGuard | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const ctrl = useRef<AbortController | null>(null)

  const scan = useCallback(async () => {
    if (!isAddr(addr)) { setErr('Enter a valid wallet address (0x followed by 40 hex characters).'); return }
    ctrl.current?.abort()
    const c = new AbortController(); ctrl.current = c
    setBusy(true); setErr(''); setReport(null)
    try {
      const r = await fetchWalletGuard(addr.trim(), c.signal)
      if (!c.signal.aborted) setReport(r)
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') setErr('The approval scan could not complete. Try again shortly.')
    } finally {
      if (!c.signal.aborted) setBusy(false)
    }
  }, [addr])

  const clean = report && report.risky === 0 && report.unlimited === 0

  return <Panel title="WALLET APPROVAL GUARD" accent="var(--trust)"
    right={report ? `${report.scanned} ${'live approvals'}` : 'self custody'}
    help={<>{'Every ERC-20 allowance a wallet has granted is a standing permission for another contract to move that token. Unlimited approvals and approvals to spam tokens are the most common drain vector in self custody. This is the MEFAI wallet check the same scan the terminal runs reading live allowances on BSC and ranking each by the USD it exposes. Revoke runs in the full terminal with your own connected Trust Wallet.'}</>}>

    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      {PRESETS.map((p) => (
        <button key={p.label} className={`cp-pill ${addr === p.addr ? 'on' : ''}`} onClick={() => setAddr(p.addr)}>{p.label}</button>
      ))}
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 10, alignItems: 'end' }} className="cp-grid-form">
      <Field label="BSC wallet address">
        <input value={addr} onChange={(e) => setAddr(e.target.value)} spellCheck={false}
          placeholder="0x…" className="mono" style={inputStyle} />
      </Field>
      <Btn variant="trust" onClick={scan} disabled={busy} style={{ width: '100%', justifyContent: 'center' }}>{busy ? 'Scanning…' : 'Scan wallet'}</Btn>
    </div>
    {err && <div style={{ color: 'var(--red)', fontSize: 12.5, marginTop: 10 }}>{err}</div>}

    {report && <div style={{ marginTop: 18 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
        <Stat label="Live approvals" value={<CountUp value={report.scanned} />} tone={TONE} sub="granted on BSC" />
        <Stat label="High risk" value={<CountUp value={report.risky} />} tone={report.risky > 0 ? 'var(--red)' : 'var(--green)'} sub="unlimited or spam" />
        <Stat label="Unlimited" value={<CountUp value={report.unlimited} />} tone={report.unlimited > 0 ? 'var(--gold)' : 'var(--green)'} sub="infinite allowance" />
        <Stat label="USD at risk" value={report.usdAtRisk > 0 ? fmtUsd(report.usdAtRisk) : '$0'} tone={report.usdAtRisk > 0 ? 'var(--red)' : 'var(--green)'} sub="exposed balance" />
      </div>

      {clean && <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 10, background: 'color-mix(in srgb, var(--green) 10%, transparent)', border: '1px solid var(--green)', fontSize: 13, color: 'var(--green)', fontWeight: 700 }}>
        {'Clean surface · no unlimited or spam approvals on this wallet.'}
      </div>}

      {report.approvals.length > 0 && <div style={{ marginTop: 14, display: 'grid', gap: 8 }}>
        {report.approvals.slice(0, 12).map((a) => (
          <div key={`${a.token}:${a.spender}`} style={{ padding: '11px 13px', borderRadius: 10, background: 'var(--c-fill)', border: '1px solid var(--c-line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 800 }}>
                {a.symbol}
                {a.possibleSpam && <span style={{ marginLeft: 7, fontSize: 11, fontWeight: 700, color: 'var(--red)' }}>{'spam'}</span>}
                {a.unlimited && <span style={{ marginLeft: 7, fontSize: 11, fontWeight: 700, color: 'var(--gold)' }}>{'unlimited'}</span>}
              </span>
              <Chip tone={SEV_TONE[a.severity]} solid>{SEV_LABEL[a.severity]}</Chip>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginTop: 6, fontSize: 11.5, color: 'var(--c-muted)' }}>
              <span>{'Spender'} · {a.spenderLabel || short(a.spender)}</span>
              <span className="mono">{a.unlimited ? 'UNLIMITED' : a.allowanceFormatted}{a.usdAtRisk && a.usdAtRisk > 0 ? ` · ${fmtUsd(a.usdAtRisk)} ${'at risk'}` : ''}</span>
            </div>
          </div>
        ))}
        {report.approvals.length > 12 && <div style={{ fontSize: 11.5, color: 'var(--c-muted-2)', textAlign: 'center' }}>+{report.approvals.length - 12} {'more approvals on this wallet'}</div>}
      </div>}
    </div>}

    {!report && !busy && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 16 }}>
      <Stat label="Reads" value={'Live allowances'} tone={TONE} sub="ERC-20 on BSC" />
      <Stat label="Flags" value={'Unlimited · spam'} tone="var(--c-text)" sub="ranked by USD" />
      <Stat label="Custody" value={'Self'} tone="var(--green)" sub="read only here" />
      <Stat label="Revoke" value={'In terminal'} tone="var(--gold)" sub="your Trust Wallet" />
    </div>}

    <div style={{ fontSize: 11, color: 'var(--c-muted-2)', marginTop: 14, lineHeight: 1.55 }}>
      {'Live ERC-20 allowances on BSC · the same wallet check MEFAI runs in the terminal. Unlimited and spam approvals are the primary self custody drain vector; the agent surfaces them before they can be used. One tap revoke runs in the full terminal with your own connected Trust Wallet.'}
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
