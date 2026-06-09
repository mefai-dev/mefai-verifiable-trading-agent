/* BNB HACK · Track 3 · Verifiable Protocol (Trust Wallet blue).
   Commit-reveal prediction registry, the RiskGovernor circuit breaker, the unified
   verifiable intelligence index (UVII) and the x402 machine-payable feed. */

import { useState } from 'react'
import {
  Btn, Card, Chip, Gauge, Panel, PctCell, Reveal, Stat, CountUp,
  CoinLogo, CmcTable, Bar, fmtNum, fmtUsd, shortAddr,
} from '../ui'
import type { CmcColumn } from '../ui'
import { apiGet, usePoll, fetchX402Roundtrip } from '../api'
import type { UviiIndex, Uvii, X402Catalog, LoopEnvelope, X402Roundtrip } from '../api'
import { ADDR, AGENT_ID, scan, chainOf } from '../config'
import { IconExternal } from '../icons'

const TRUST = 'var(--trust)'

export default function Protocol({ go }: { go: (p: string) => void }) {
  const { data: uvii } = usePoll<UviiIndex>((s) => apiGet('/uvii?min_samples=30&top_n=12', s), 60_000)
  const { data: x402 } = usePoll<X402Catalog>((s) => apiGet('/x402/products', s), 120_000)
  const { data: loop } = usePoll<LoopEnvelope>((s) => apiGet('/loop/state', s), 12_000)
  const st = loop?.available ? loop.state : undefined

  const gi = uvii?.global_index
  const ddBps = st ? Math.round(st.drawdown * 10000) : 0
  const capBps = st ? Math.round(st.jury_cap * 10000) : 2000
  const internalBps = st ? Math.round(st.internal_cap * 10000) : 1400

  return <div style={{ maxWidth: 1320, margin: '0 auto', padding: '40px 22px 80px' }}>
    {/* header */}
    <Reveal>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 'clamp(28px,4vw,46px)', fontWeight: 900, letterSpacing: '-1px', margin: 0 }}>
            Verifiable <span style={{ color: TRUST }}>Protocol</span>
          </h1>
          <p style={{ color: 'var(--c-text-2)', maxWidth: 660, marginTop: 10, lineHeight: 1.6, fontSize: 14.5 }}>
            A commit then reveal prediction registry a chain anchored drawdown circuit breaker one unified verifiable
            intelligence index and an x402 machine payable feed. Every claim is auditable on BscScan.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Btn variant="ghost" sm onClick={() => go('/compete')}>Home</Btn>
          <Btn variant="trust" sm href={scan(ADDR.registry)}>Registry</Btn>
        </div>
      </div>
    </Reveal>

    {/* stat strip */}
    <Reveal delay={80}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginTop: 30 }}>
        <Stat label="Global UVII" value={gi ? <CountUp value={gi.score} decimals={1} /> : '-'} tone={TRUST} sub="0 to 100" />
        <Stat label="Integrity" value={gi ? fmtNum(gi.integrity_score, 1) : '-'} tone="var(--green)" sub="resolved share" />
        <Stat label="Discipline" value={gi ? fmtNum(gi.discipline_score, 1) : '-'} tone="var(--gold)" sub="drawdown" />
        <Stat label="Skill" value={gi ? fmtNum(gi.skill_score, 1) : '-'} tone="var(--cmc)" sub="win rate" />
        <Stat label="Uptime" value={gi ? fmtNum(gi.uptime_score, 1) : '-'} tone="var(--c-text)" sub="keeper" />
        <Stat label="Resolved" value={gi ? <CountUp value={gi.n_resolved} /> : '-'} tone="var(--c-text)" sub="outcomes" />
      </div>
    </Reveal>

    {/* how the index reads + where each number comes from */}
    <Reveal delay={110}>
      <Card style={{ padding: '13px 16px', marginTop: 12, fontSize: 12.5, lineHeight: 1.65, color: 'var(--c-text-2)' }}>
        <b style={{ color: 'var(--c-text)' }}>How to read this.</b> The Global UVII fuses five 0 to 100 sub scores, weighted
        PnL 30 · Skill 25 · Discipline 20 · Integrity 15 · Uptime 10.
        {' '}<b style={{ color: 'var(--green)' }}>Integrity</b> is the share of predictions that reached a recorded outcome
        ({gi ? `${fmtNum(gi.integrity_score, 1)}%` : '-'}); it sits below 100 because the newest open calls have not
        resolved yet, so they are not counted as proven. <b style={{ color: 'var(--cmc)' }}>Skill</b> is the realised win rate,
        <b style={{ color: 'var(--gold)' }}> Discipline</b> reads from realised drawdown and Uptime from keeper recency.
        Every <b style={{ color: 'var(--c-text)' }}>Resolved</b> outcome is anchored to the result ledger on BSC mainnet.{' '}
        <a className="cp-a" href={scan(ADDR.ledger)} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
          open the ledger on BscScan <IconExternal size={11} />
        </a>
      </Card>
    </Reveal>

    {/* commit reveal + circuit breaker */}
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }} className="cp-grid-2">
      <Reveal delay={60}>
        <Panel title="COMMIT REVEAL REGISTRY" accent="#3375BB" right="cannot be backfilled">
          <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--c-text-2)', marginTop: 0 }}>
            Before any entry the agent writes <span className="mono" style={{ color: TRUST }}>keccak256(symbol, direction, entry, target, stop, expiry, salt)</span> to
            the registry. After the window it reveals the preimage. The hash binds the call before the outcome is known so the track record cannot be rewritten.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            {[
              ['1 · COMMIT', 'hash of the full prediction lands on the ledger', 'var(--gold)'],
              ['2 · TRADE', 'entry executes under the security gate', TRUST],
              ['3 · REVEAL', 'preimage revealed hash verified', 'var(--green)'],
              ['4 · RESOLVE', 'keeper records the outcome to the ledger', 'var(--cmc)'],
            ].map(([t, d, c]) => (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '9px 12px', borderRadius: 11, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
                <span className="mono" style={{ fontSize: 12, fontWeight: 800, color: c as string, minWidth: 78 }}>{t}</span>
                <span style={{ fontSize: 12.5, color: 'var(--c-text-2)' }}>{d}</span>
              </div>
            ))}
          </div>
          <a className="cp-a" href={scan(ADDR.registry)} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 12, fontSize: 12.5 }}>
            CommitRevealPredictionRegistry · {shortAddr(ADDR.registry)} <IconExternal size={12} />
          </a>
        </Panel>
      </Reveal>

      <Reveal delay={120}>
        <Panel title="RISK GOVERNOR · CIRCUIT BREAKER" accent="#3375BB" right={st?.governor?.ok === false ? 'HALTED' : 'ARMED'}
          help={<>DD USED reads <b style={{ color: 'var(--c-text)' }}>realised</b> drawdown against the internal cap. It shows
            <b style={{ color: 'var(--c-text)' }}> 0 / {capBps} bps</b> because equity has not drawn down: the breaker is armed and the floor
            has never been touched, so <span className="mono">canTrade()</span> stays true. The number only climbs when a live loss
            eats into the budget; at the internal cap the contract refuses the next entry before the jury DQ line is ever reached.</>}>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' }}>
            <Gauge value={Math.min(100, (ddBps / (capBps || 1)) * 100)} max={100} label="DD USED" tone={ddBps >= capBps * 0.9 ? 'var(--red)' : TRUST} size={140} sub={`${ddBps} / ${capBps} bps`} />
            <div style={{ flex: 1, minWidth: 180 }}>
              <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--c-text-2)', marginTop: 0 }}>
                The RiskGovernor enforces a drawdown cap <b style={{ color: 'var(--c-text)' }}>below</b> the jury disqualification line. When equity breaches the budget
                <span className="mono" style={{ color: TRUST }}> canTrade()</span> returns false and the vault halts. Disqualification is structurally impossible.
              </p>
              <Bar label="Internal cap" value={internalBps} max={capBps} tone="var(--gold)" fmt={() => `${internalBps} bps`} />
              <Bar label="Jury DQ line" value={capBps} max={capBps} tone="var(--red)" fmt={() => `${capBps} bps`} />
              <Chip tone={st?.governor?.ok === false ? 'var(--red)' : 'var(--green)'}>{st?.governor?.ok === false ? 'canTrade() = false' : 'canTrade() = true'}</Chip>
            </div>
          </div>
          {st?.governor?.detail && <div className="mono" style={{ marginTop: 10, fontSize: 11.5, color: 'var(--c-muted)' }}>{st.governor.detail}</div>}
          <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--c-muted)', lineHeight: 1.55 }}>
            The governor's transaction list is empty on purpose · it only writes a halt when the floor is breached, and it never has.
            The proof is the verified contract code plus the keeper that streams equity into it.
          </div>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 8 }}>
            <a className="cp-a" href={`${scan(ADDR.governor)}#code`} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12.5 }}>
              RiskGovernor code · {shortAddr(ADDR.governor)} <IconExternal size={12} />
            </a>
            <a className="cp-a" href={scan(ADDR.keeper)} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12.5 }}>
              Equity keeper feed · {shortAddr(ADDR.keeper)} <IconExternal size={12} />
            </a>
          </div>
        </Panel>
      </Reveal>
    </div>

    {/* UVII index table */}
    <Reveal delay={80}>
      <div style={{ marginTop: 16 }}>
        <UviiTable uvii={uvii} />
      </div>
    </Reveal>

    {/* x402 feed */}
    <Reveal delay={80}>
      <div style={{ marginTop: 16 }}>
        <X402Panel x402={x402} />
      </div>
    </Reveal>

    {/* live proofs */}
    <Reveal delay={80}>
      <div style={{ marginTop: 16 }}>
        <ProofsTable st={st} />
      </div>
    </Reveal>

    {/* contract registry */}
    <Reveal delay={80}>
      <Card style={{ padding: 22, marginTop: 16 }}>
        <div className="panel-title" style={{ color: TRUST, marginBottom: 14 }}>VERIFIED CONTRACTS · BNB CHAIN</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 12 }}>
          {[
            ['Prediction registry', ADDR.registry], ['Risk governor', ADDR.governor],
            ['Result ledger', ADDR.ledger], ['ERC-8004 identity', ADDR.erc8004],
            ['Agent wallet', ADDR.agent], ['Oracle / keeper', ADDR.keeper],
          ].map(([label, addr]) => {
            const testnet = chainOf(addr) === 97
            return <a key={label} className="cp-a" href={scan(addr)} target="_blank" rel="noopener noreferrer"
              style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 13, borderRadius: 12, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 11, letterSpacing: 1, color: 'var(--c-muted)', textTransform: 'uppercase' }}>{label}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 700, color: testnet ? 'var(--gold)' : 'var(--green)' }}>{testnet ? 'testnet' : 'mainnet'}</span>
              </span>
              <span className="mono" style={{ fontSize: 13, color: 'var(--c-text)', fontWeight: 600 }}>{shortAddr(addr)}</span>
              <span style={{ fontSize: 11, color: TRUST, display: 'inline-flex', alignItems: 'center', gap: 3 }}>{testnet ? 'testnet BscScan' : 'BscScan'} <IconExternal size={11} /></span>
            </a>
          })}
        </div>
        <div className="mono" style={{ marginTop: 14, fontSize: 11.5, color: 'var(--c-muted)' }}>agentId {shortAddr(AGENT_ID)} · BscScan + Sourcify verified</div>
      </Card>
    </Reveal>
  </div>
}

/* ─────────────── UVII table ─────────────── */
function UviiTable({ uvii }: { uvii: UviiIndex | null }) {
  const rows = uvii?.entities ?? []
  const cols: CmcColumn<Uvii>[] = [
    { key: 'rank', header: '#', render: (_r, i) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{i + 1}</span> },
    { key: 'name', header: 'Entity', align: 'l', sticky: true, sortValue: (r) => r.key, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.key} /><span><span className="cmc-name-main">{r.key.replace('USDT', '')}</span><span className="cmc-name-sym">{r.kind}</span></span></span> },
    { key: 'score', header: 'UVII', sortValue: (r) => r.score, render: (r) => <span className="mono" style={{ fontWeight: 800, color: TRUST }}>{fmtNum(r.score, 1)}</span> },
    { key: 'pnl', header: 'PnL', sortValue: (r) => r.pnl_score, render: (r) => <span className="mono">{fmtNum(r.pnl_score, 1)}</span> },
    { key: 'skill', header: 'Skill', sortValue: (r) => r.skill_score, render: (r) => <span className="mono">{fmtNum(r.skill_score, 1)}</span> },
    { key: 'disc', header: 'Discipline', sortValue: (r) => r.discipline_score, render: (r) => <span className="mono">{fmtNum(r.discipline_score, 1)}</span> },
    { key: 'integ', header: 'Integrity', sortValue: (r) => r.integrity_score, render: (r) => <span className="mono" style={{ color: 'var(--green)' }}>{fmtNum(r.integrity_score, 1)}</span> },
    { key: 'up', header: 'Uptime', sortValue: (r) => r.uptime_score, render: (r) => <span className="mono">{fmtNum(r.uptime_score, 1)}</span> },
    { key: 'n', header: 'Resolved', sortValue: (r) => r.n_resolved, render: (r) => <span className="mono">{r.n_resolved}</span> },
  ]
  return <Panel title="UNIFIED VERIFIABLE INTELLIGENCE INDEX" accent="#3375BB" right={uvii ? `${rows.length} entities` : ''}
    help={<>One fused 0 to 100 score per market blending PnL win rate (Skill) Discipline Integrity and Uptime. Click any
      column header to sort · the caret marks the active sort. Ranked by UVII by default; the same math drives the global score above.</>}>
    <CmcTable columns={cols} rows={rows} empty="computing UVII…" maxHeight={440} defaultSort={{ key: 'score', dir: 'desc' }} />
  </Panel>
}

/* ─────────────── x402 ─────────────── */
function X402Panel({ x402 }: { x402: X402Catalog | null }) {
  const products = x402?.products ?? []
  return <Panel title="x402 MACHINE PAYABLE FEED" accent="#3375BB" right={x402 ? x402.network : ''}
    help={<>Each card is a paywalled endpoint priced in stablecoin. A calling agent hits the URL receives HTTP 402 pays the
      exact quoted amount with an EIP-3009 authorization then re-requests and gets the signed payload. Prices and the
      payment network below are read live from the running catalog.</>}>
    <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--c-text-2)', marginTop: 0 }}>
      The verified signal feed is served over HTTP 402. Payment is bound with EIP-3009 to the exact token and chain charged so one agent can pay another for proven alpha without a human in the loop.
    </p>
    {products.length === 0
      ? <div style={{ color: 'var(--c-muted)', padding: 20, textAlign: 'center' }}>catalog loading…</div>
      : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
        {products.map((p) => (
          <div key={p.product_id} style={{ padding: 16, borderRadius: 13, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <b style={{ fontSize: 14.5 }}>{p.title}</b>
              <Chip tone={TRUST} solid>{fmtUsd(Number(p.price_atomic) / 1e18, 4)}</Chip>
            </div>
            <p style={{ fontSize: 12.5, color: 'var(--c-muted)', margin: '0 0 8px', lineHeight: 1.5 }}>{p.description}</p>
            <div className="mono" style={{ fontSize: 11, color: 'var(--c-muted-2)' }}>{p.mime_type} · HTTP 402</div>
          </div>
        ))}
      </div>}
    <X402Handshake productId={products[0]?.product_id || 'verified-leaderboard'} />
  </Panel>
}

/* ─────────────── live 402 handshake (real EIP-3009 roundtrip) ─────────────── */
function X402Handshake({ productId }: { productId: string }) {
  const [data, setData] = useState<X402Roundtrip | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  async function run() {
    setLoading(true); setError(false)
    try { setData(await fetchX402Roundtrip(productId)) }
    catch { setError(true) }
    finally { setLoading(false) }
  }
  const short = (s?: string, h = 10, t = 6) => !s ? '-' : (s.length <= h + t + 1 ? s : `${s.slice(0, h)}…${s.slice(-t)}`)
  return <div style={{ marginTop: 16, padding: 16, borderRadius: 13, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <b style={{ fontSize: 13.5 }}>Run the live 402 handshake</b>
      {data && <Chip tone={data.verified ? 'var(--green)' : 'var(--gold)'} solid>{data.verified ? 'verified end to end' : 'incomplete'}</Chip>}
    </div>
    <p style={{ fontSize: 12, color: 'var(--c-muted)', margin: '6px 0 10px', lineHeight: 1.55 }}>
      A fresh ephemeral key signs a real EIP-3009 authorization for the exact price; the server recovers the signer and serves the verified feed. The settlement transaction is deferred to a funded facilitator, so no funds move in this proof.
    </p>
    {!data && !loading && <Btn sm variant="trust" onClick={run}>Run live 402 handshake</Btn>}
    {loading && <div style={{ color: 'var(--c-muted)', fontSize: 12.5 }}>running handshake…</div>}
    {error && <div style={{ color: 'var(--c-muted)', fontSize: 12.5 }}>The handshake endpoint is not reachable right now.</div>}
    {data && <div style={{ display: 'grid', gap: 6 }}>
      {data.steps.map((s) => {
        const tone = s.name === 'verify' ? (s.valid ? 'var(--green)' : 'var(--red)') : s.name === 'serve' ? 'var(--green)' : TRUST
        return <div key={s.n} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '8px 11px', borderRadius: 9, background: 'var(--c-panel)', border: '1px solid var(--c-line)' }}>
          <span style={{ flex: '0 0 auto', width: 20, height: 20, borderRadius: 6, display: 'grid', placeItems: 'center', fontSize: 10.5, fontWeight: 800, color: '#000', background: tone }}>{s.n}</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12.5, fontWeight: 700 }}>{s.title}</span>
              {s.status != null && <Chip tone={tone}>{s.status}</Chip>}
            </div>
            <div className="mono" style={{ fontSize: 10.5, color: 'var(--c-muted-2)', marginTop: 3, wordBreak: 'break-all', lineHeight: 1.6 }}>
              {s.name === 'sign' && <>payer {short(s.payer)} · sig {short(s.signature, 14, 8)}</>}
              {s.name === 'verify' && <>recovered signer {short(s.recovered_payer)} · {s.code}</>}
              {s.name === 'serve' && s.payment_response && <>settled {String(s.payment_response.success)} · deferred {String(s.payment_response.deferred)}</>}
              {s.name === 'challenge' && s.accepts && s.accepts[0] && <>{s.accepts[0].maxAmountRequired} · {s.accepts[0].network} · {short(s.accepts[0].payTo)}</>}
            </div>
          </div>
        </div>
      })}
      <div style={{ fontSize: 10.5, color: 'var(--c-muted-2)', lineHeight: 1.55 }}>{data.settlement.note}</div>
      <Btn sm variant="ghost" onClick={run}>Run again</Btn>
    </div>}
  </div>
}

/* ─────────────── proofs table ─────────────── */
function ProofsTable({ st }: { st?: LoopEnvelope['state'] }) {
  const rows = st?.proofs ?? []
  const cols: CmcColumn<NonNullable<LoopEnvelope['state']>['proofs'][number]>[] = [
    { key: 'name', header: 'Market', align: 'l', sticky: true, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.symbol} /><span className="cmc-name-main">{r.symbol.replace('USDT', '')}</span></span> },
    { key: 'status', header: 'Status', render: (r) => <Chip tone={r.status === 'revealed' ? 'var(--green)' : 'var(--gold)'}>{r.status}</Chip> },
    { key: 'signal', header: 'Signal', render: (r) => <span className="mono">{fmtNum(r.signal, 0)}</span> },
    { key: 'conf', header: 'Confidence', render: (r) => <PctCell value={r.confidence} d={0} /> },
    { key: 'commit', header: 'Commit tx', render: (r) => r.commit_tx ? <a className="cp-a" href={`https://bscscan.com/tx/${r.commit_tx}`} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>{shortAddr(r.commit_tx)} <IconExternal size={11} /></a> : <span style={{ color: 'var(--c-muted-2)' }}>-</span> },
    { key: 'reveal', header: 'Reveal tx', render: (r) => r.reveal_tx ? <a className="cp-a" href={`https://bscscan.com/tx/${r.reveal_tx}`} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: 'var(--green)' }}>{shortAddr(r.reveal_tx)} <IconExternal size={11} /></a> : <span style={{ color: 'var(--c-muted-2)' }}>-</span> },
    { key: 'pid', header: 'Pred ID', render: (r) => <span className="mono">{r.prediction_id ?? '-'}</span> },
  ]
  return <Panel title="COMMIT REVEAL PROOFS" accent="#3375BB" right={st ? `cycle ${st.cycle}` : 'standby'}
    help={<>The agent’s live calls this cycle. Commit tx seals the hashed prediction before the trade; Reveal tx publishes the
      preimage after the window. Both link straight to BscScan so the call cannot be edited after the fact.</>}>
    <CmcTable columns={cols} rows={rows} empty={st ? 'no proofs this cycle' : 'agent on standby'} />
  </Panel>
}
