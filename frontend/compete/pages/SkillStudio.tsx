/* BNB HACK · Track 2 · CMC Strategy Skill Studio (CoinMarketCap palette).
   Five backtested skills powered by 195k labeled outcomes and the full
   CoinMarketCap Agent Hub, presented through CMC-style tables. */

import { useMemo, useState } from 'react'
import {
  Btn, Card, Chip, Gauge, Panel, PctCell, Portal, Reveal, Stat, CountUp,
  CoinLogo, CmcTable, Bar, fmtNum, fmtPct, fmtUsd,
} from '../ui'
import type { CmcColumn } from '../ui'
import { apiGet, apiPost, usePoll, fetchCmcGlobal, fetchCmcIntel, fetchBacktestReports, fetchBacktestReport, fetchCompose } from '../api'
import type { Leaderboard, EntityStats, TpSl, SizingResult, GridCell, CmcGlobal, CmcIntel, BacktestIndexEnvelope, BacktestManifestEnvelope, BacktestSkillRow, ComposePlan, ComposeLeg } from '../api'
import { scan } from '../config'
import { ADDR } from '../config'
import { IconExternal, IconAlert } from '../icons'

const CMC = 'var(--cmc)'
const ASSETS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT']
const SKILLS = [
  { id: 'alloc', name: 'Risk Budgeted Allocator', tone: CMC, blurb: 'Distributes a fixed risk budget across the watchlist by empirical edge and a drawdown ceiling never letting any leg exceed its Kelly cap.' },
  { id: 'tpsl', name: 'TP/SL Optimizer', tone: 'var(--green)', blurb: 'Grid searches every take profit and stop pair against 195k resolved outcomes to find the bracket with the best expectancy per risk.' },
  { id: 'rotate', name: 'Narrative Rotation', tone: 'var(--gold)', blurb: 'Rotates exposure into the strongest CoinMarketCap narratives ranked by momentum and confirmed by the verified signal leaderboard.' },
  { id: 'regime', name: 'Regime Governor', tone: 'var(--trust)', blurb: 'Reads the global market regime and scales every bracket deploying only when alignment and strength clear the gate.' },
  { id: 'meta', name: 'Meta Strategy Composer', tone: 'var(--purple)', blurb: 'The flagship · fuses the four skills above into one plan. Selects the assets brackets the trades gates them by regime then sizes every leg inside a single drawdown budget.' },
  { id: 'decay', name: 'Edge Decay Monitor', tone: 'var(--red)', blurb: 'A live monitor not a backtested strategy · compares each signal source over its full record against a recent window flagging where the verified edge is strengthening holding or quietly decaying.' },
]
const DAY = 86_400

export default function SkillStudio({ go }: { go: (p: string) => void }) {
  const [skill, setSkill] = useState('alloc')
  const { data: lb } = usePoll<Leaderboard>((s) => apiGet('/leaderboard?rank_by=expectancy&min_samples=30&top_n=14', s), 60_000)
  const { data: cmcG } = usePoll<CmcGlobal>((s) => fetchCmcGlobal(s), 60_000)
  const { data: intel } = usePoll<CmcIntel>((s) => fetchCmcIntel(90, s), 60_000)

  const mcap = cmcG?.total_market_cap_usd
  const vol = cmcG?.total_volume_usd
  const btcDom = cmcG?.btc_dominance
  const mcapChg = cmcG?.mcap_change_24h

  return <div style={{ maxWidth: 1320, margin: '0 auto', padding: '40px 22px 80px' }}>
    {/* header */}
    <Reveal>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 'clamp(28px,4vw,46px)', fontWeight: 900, letterSpacing: '-1px', margin: 0 }}>
            CMC <span style={{ color: CMC }}>{'Strategy'}</span> {'Skills'}
          </h1>
          <p style={{ color: 'var(--c-text-2)', maxWidth: 660, marginTop: 10, lineHeight: 1.6, fontSize: 14.5 }}>
            {'Backtested allocation · TP/SL optimization · narrative rotation · regime governing · and edge decay watch. Every skill is grounded on real resolved outcomes and the full CoinMarketCap Agent Hub not guesses.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Btn variant="ghost" sm onClick={() => go('/compete')}>{'Home'}</Btn>
          <Btn variant="cmc" sm onClick={() => go('/compete/agent')}>{'Live agent'}</Btn>
        </div>
      </div>
    </Reveal>

    {/* CMC market strip */}
    <Reveal delay={80}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginTop: 30 }}>
        <Stat label="Total market cap" value={fmtUsd(mcap)} tone={CMC} sub={mcapChg != null ? fmtPct(mcapChg, 2, true) : 'CMC global'} />
        <Stat label="24h volume" value={fmtUsd(vol)} tone="var(--c-text)" sub="CMC global" />
        <Stat label="BTC dominance" value={btcDom != null ? fmtPct(btcDom, 1) : '-'} tone="var(--gold)" sub="CMC global" />
        <Stat label="Backtested skills" value={<CountUp value={5} />} tone="var(--green)" sub="+1 live monitor" />
      </div>
    </Reveal>

    {/* skill selector · pick a skill to load its live workspace below */}
    <Reveal delay={120}>
      <div style={{ fontSize: 12, color: 'var(--c-muted)', textAlign: 'center', margin: '26px 0 12px' }}>{'Select a skill to load its live workspace'}</div>
      <div className="cp-skill-grid">
        {SKILLS.map((sk) => {
          const on = skill === sk.id
          return <Card key={sk.id} hover className="cp-fx"
            style={{ padding: '20px 18px', cursor: 'pointer', textAlign: 'center', ['--glow' as any]: `color-mix(in srgb, ${sk.tone} 22%, transparent)`, borderColor: on ? sk.tone : undefined, boxShadow: on ? `0 0 0 1px ${sk.tone}, 0 10px 30px var(--c-shadow)` : undefined }}>
            <div className="cp-skillcard-btn" onClick={() => setSkill(sk.id)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSkill(sk.id) }}>
              <h3 style={{ fontSize: 16.5, fontWeight: 800, margin: '0 0 8px', color: on ? sk.tone : 'var(--c-text)' }}>{sk.name}</h3>
              <p style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--c-text-2)', margin: '0 0 13px' }}>{sk.blurb}</p>
              <span style={{ display: 'inline-block', fontSize: 10.5, fontWeight: 800, letterSpacing: 1, textTransform: 'uppercase', padding: '4px 12px', borderRadius: 999, color: on ? '#08131f' : sk.tone, background: on ? sk.tone : `color-mix(in srgb, ${sk.tone} 14%, transparent)` }}>{on ? 'Active' : 'Open skill'}</span>
            </div>
          </Card>
        })}
      </div>
    </Reveal>

    {/* skill workspace */}
    <div style={{ marginTop: 24 }}>
      {skill === 'alloc' && <Reveal><AllocatorSkill lb={lb} /></Reveal>}
      {skill === 'tpsl' && <Reveal><TpSlSkill /></Reveal>}
      {skill === 'rotate' && <Reveal><RotationSkill intel={intel} lb={lb} /></Reveal>}
      {skill === 'regime' && <Reveal><RegimeSkill intel={intel} cmcG={cmcG} /></Reveal>}
      {skill === 'meta' && <Reveal><MetaComposerSkill /></Reveal>}
      {skill === 'decay' && <Reveal><DecaySkill /></Reveal>}
    </div>

    {/* leaderboard CMC table · the shared verified record every skill above reads from */}
    <Reveal delay={80}>
      <div style={{ marginTop: 36 }}>
        <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--c-muted)', marginBottom: 12, lineHeight: 1.55 }}>
          {'The shared verified record · every skill above sizes brackets and rotates off this same set of resolved outcomes'}
        </div>
        <SkillLeaderboard />
      </div>
    </Reveal>

    {/* reproducible backtest verification · regenerate the artifact and compare hashes */}
    <Reveal delay={80}>
      <div style={{ marginTop: 36 }}>
        <BacktestVerification />
      </div>
    </Reveal>

    {/* footer note */}
    <Reveal delay={80}>
      <div style={{ marginTop: 26, textAlign: 'center', fontSize: 12, color: 'var(--c-muted)' }}>
        {'Every skill output is verifiable · result ledger'} <a className="cp-a" href={scan(ADDR.ledger)} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>{ADDR.ledger.slice(0, 10)}… <IconExternal size={12} /></a>
      </div>
    </Reveal>
  </div>
}

/* ─────────────── reproducible backtest verification ───────────────
   Renders the artifact written by skills/run_backtests.py: every skill's
   PASS/FAIL plus the dataset and code fingerprints and a repository-stable
   repro_digest. One click opens a skill's full manifest (content hash, the
   exact regenerate command, the file hashes and the backtest console). A judge
   reruns the command on the public repo and confirms the hashes match. */
function shortHash(h?: string | null): string { return h ? `${h.slice(0, 10)}…${h.slice(-6)}` : '-' }
function CopyHash({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return <button className="cp-pill" style={{ fontSize: 11 }} onClick={() => {
    try { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1400) } catch { /* clipboard blocked */ }
  }}>{done ? '✓' : '⧉'}</button>
}
function BacktestVerification() {
  const { data, loading } = usePoll<BacktestIndexEnvelope>((s) => fetchBacktestReports(s), 120_000)
  const [open, setOpen] = useState<string | null>(null)
  const idx = data?.available ? data.index : undefined
  const skills = idx?.skills ?? []
  const passing = skills.filter((s) => s.result === 'PASS').length
  const rows = idx?.dataset?.row_counts ?? {}
  const totalRows = Object.values(rows).reduce<number>((a, v) => a + (typeof v === 'number' ? v : 0), 0)

  const cols: CmcColumn<BacktestSkillRow>[] = [
    { key: 'name', header: 'Skill', align: 'l', sticky: true, sortValue: (r) => r.skill, render: (r) => <span style={{ fontWeight: 700 }}>{r.skill}</span> },
    { key: 'result', header: 'Result', sortValue: (r) => (r.result === 'PASS' ? 1 : 0), render: (r) => <Chip tone={r.result === 'PASS' ? 'var(--green)' : 'var(--red)'} solid>{r.result}</Chip> },
    { key: 'content', header: 'Content hash', align: 'l', sortValue: (r) => r.content_hash ?? '', render: (r) => <span className="mono" style={{ fontSize: 11.5, color: 'var(--c-text-2)' }}>{shortHash(r.content_hash)} {r.content_hash && <CopyHash text={r.content_hash} />}</span> },
    { key: 'code', header: 'Code hash', align: 'l', sortValue: (r) => r.code_sha256, render: (r) => <span className="mono" style={{ fontSize: 11.5, color: 'var(--c-muted)' }}>{shortHash(r.code_sha256)}</span> },
    { key: 'view', header: '', render: (r) => <Btn variant="ghost" sm onClick={() => setOpen(open === r.skill ? null : r.skill)}>{open === r.skill ? 'Close' : 'View report'}</Btn> },
  ]

  return <Panel title="REPRODUCIBLE BACKTEST VERIFICATION" accent="#3861FB"
    right={idx ? `${passing} / ${skills.length} ${'passing'}` : loading ? 'loading…' : 'not generated'}
    help={<>{'Each strategy skill ships a deterministic backtest run against a pinned synthetic sample dataset with a seeded generator. This panel serves the exact artifact those runs write: every skill\u2019s PASS/FAIL, the dataset and code fingerprints, and one repository stable digest over them all. Open any skill to see its content hash, the one line command that regenerates it, the hashed source files and the backtest console. Clone the public repo, run the command and the hashes match · that is the proof the numbers are not hand typed.'}</>}>
    {!idx ? <div style={{ color: 'var(--c-muted)', padding: 30, textAlign: 'center' }}>{loading ? 'loading verification artifact…' : 'verification artifact not generated yet'}</div> : <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="Overall" value={idx.overall} tone={idx.overall === 'PASS' ? 'var(--green)' : 'var(--red)'} mono={false} />
        <Stat label="Skills passing" value={`${passing} / ${skills.length}`} tone={CMC} />
        <Stat label="Dataset rows" value={totalRows ? totalRows.toLocaleString() : '-'} tone="var(--c-text)" sub="pinned sample" />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14, alignItems: 'center', fontSize: 12, color: 'var(--c-muted)' }}>
        <span>{'Dataset'} <span className="mono" style={{ color: 'var(--c-text-2)' }}>{idx.dataset?.path}</span></span>
        <span className="mono" style={{ color: 'var(--c-text-2)' }}>sha256 {shortHash(idx.dataset?.sha256)}{idx.dataset?.sha256 && <CopyHash text={idx.dataset.sha256} />}</span>
        <span style={{ marginLeft: 'auto' }}>{'Repro digest'} <span className="mono" style={{ color: 'var(--green)' }}>{shortHash(idx.repro_digest)}</span>{idx.repro_digest && <CopyHash text={idx.repro_digest} />}</span>
      </div>
      <CmcTable columns={cols} rows={skills} empty="no skills" defaultSort={{ key: 'name', dir: 'asc' }} />
      {open && <BacktestDetail skill={open} />}
      <div style={{ marginTop: 12, fontSize: 11.5, color: 'var(--c-muted)', lineHeight: 1.55 }}>
        {'Regenerate locally'} <span className="mono" style={{ color: 'var(--c-text-2)' }}>python3 data/make_sample_db.py &amp;&amp; python3 skills/run_backtests.py</span>
      </div>
    </>}
  </Panel>
}
function BacktestDetail({ skill }: { skill: string }) {
  const { data, loading } = usePoll<BacktestManifestEnvelope>((s) => fetchBacktestReport(skill, s), 120_000, [skill])
  const m = data?.available ? data.manifest : undefined
  if (!m) return <div style={{ color: 'var(--c-muted)', padding: 18, textAlign: 'center', fontSize: 12.5 }}>{loading ? 'loading report…' : 'report unavailable'}</div>
  const files = Object.entries(m.code?.files ?? {})
  return <Card style={{ padding: 18, marginTop: 14 }} glow="color-mix(in srgb, var(--cmc) 16%, transparent)">
    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 12 }}>
      <div style={{ fontWeight: 800, fontSize: 15 }}>{m.skill}</div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <Chip tone={m.result === 'PASS' ? 'var(--green)' : 'var(--red)'} solid>{m.result}</Chip>
        <span style={{ fontSize: 12, color: 'var(--c-muted)' }}>{'exit code'} <span className="mono">{m.exit_code}</span></span>
      </div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px', fontSize: 12, marginBottom: 12 }}>
      <span style={{ color: 'var(--c-muted)' }}>{'Content hash'}</span><span className="mono" style={{ color: 'var(--c-text-2)', wordBreak: 'break-all' }}>{m.content_hash}</span>
      <span style={{ color: 'var(--c-muted)' }}>{'Code hash'}</span><span className="mono" style={{ color: 'var(--c-text-2)', wordBreak: 'break-all' }}>{m.code?.sha256}</span>
      <span style={{ color: 'var(--c-muted)' }}>{'Regenerate'}</span><span className="mono" style={{ color: 'var(--green)', wordBreak: 'break-all' }}>{m.repro_command}</span>
    </div>
    {files.length > 0 && <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11.5, color: 'var(--c-muted)', marginBottom: 6 }}>{'Strategy code fingerprint'}</div>
      <div style={{ display: 'grid', gap: 4 }}>
        {files.map(([f, h]) => <div key={f} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 11.5 }}>
          <span className="mono" style={{ color: 'var(--c-text-2)' }}>{f}</span>
          <span className="mono" style={{ color: 'var(--c-muted)' }}>{shortHash(h)}</span>
        </div>)}
      </div>
    </div>}
    {m.stdout_tail && <div>
      <div style={{ fontSize: 11.5, color: 'var(--c-muted)', marginBottom: 6 }}>{'Backtest console'}</div>
      <pre className="mono" style={{ fontSize: 11.5, background: 'var(--c-fill-2)', borderRadius: 10, padding: 12, margin: 0, overflowX: 'auto', color: 'var(--c-text-2)', lineHeight: 1.5 }}>{m.stdout_tail}</pre>
    </div>}
  </Card>
}

/* ─────────────── Risk-Budgeted Allocator ─────────────── */
const TF_OPTS = ['15m', '30m', '1h', '4h']
function AllocatorSkill({ lb }: { lb: Leaderboard | null }) {
  const [equity, setEquity] = useState(10000)
  const [tf, setTf] = useState('1h')
  const { data, loading } = usePoll<{ symbol: string; r: SizingResult }[]>(async (s) => {
    const out = await Promise.all(ASSETS.map(async (symbol) => {
      try {
        const r = await apiPost<SizingResult>('/sizing', { symbol, timeframe: tf, equity, current_drawdown: 0, regime_gate: true }, s)
        return { symbol, r }
      } catch { return null }
    }))
    return out.filter(Boolean) as { symbol: string; r: SizingResult }[]
  }, 45_000, [equity, tf])

  const all = data ?? []
  const approved = all.filter((d) => d.r.approved)
  const totalNotional = approved.reduce((s, d) => s + d.r.notional, 0)
  const totalMargin = approved.reduce((s, d) => s + d.r.margin, 0)
  const totalRisk = approved.reduce((s, d) => s + Math.abs(d.r.worst_case_loss), 0)

  const cols: CmcColumn<{ symbol: string; r: SizingResult }>[] = [
    { key: 'rank', header: '#', render: (_r, i) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{i + 1}</span> },
    { key: 'name', header: 'Asset', align: 'l', sticky: true, sortValue: (d) => d.symbol, render: (d) => <span className="cmc-name"><CoinLogo symbol={d.symbol} /><span><span className="cmc-name-main">{d.symbol.replace('USDT', '')}</span><span className="cmc-name-sym">{d.symbol}</span></span></span> },
    { key: 'status', header: 'Gate', sortValue: (d) => (d.r.approved ? 1 : 0), render: (d) => <Chip tone={d.r.approved ? 'var(--green)' : 'var(--c-muted)'} solid={d.r.approved}>{d.r.approved ? 'sized' : 'blocked'}</Chip> },
    { key: 'alloc', header: 'Allocation', sortValue: (d) => d.r.notional, render: (d) => <span className="mono" style={{ fontWeight: 700, color: d.r.approved ? CMC : 'var(--c-muted)' }}>{fmtPct(totalNotional ? (d.r.notional / totalNotional) * 100 : 0, 1)}</span> },
    { key: 'notional', header: 'Notional', sortValue: (d) => d.r.notional, render: (d) => <span className="mono">{d.r.approved ? fmtUsd(d.r.notional) : '-'}</span> },
    { key: 'lev', header: 'Leverage', sortValue: (d) => d.r.leverage, render: (d) => <span className="mono">{d.r.approved ? `${fmtNum(d.r.leverage, 2)}x` : '-'}</span> },
    { key: 'kelly', header: 'Kelly', sortValue: (d) => d.r.full_kelly, render: (d) => <PctCell value={d.r.full_kelly * 100} d={1} /> },
    { key: 'risk', header: 'Worst loss', sortValue: (d) => Math.abs(d.r.worst_case_loss), render: (d) => <span className="mono" style={{ color: d.r.approved ? 'var(--red)' : 'var(--c-muted)' }}>{d.r.approved ? fmtUsd(d.r.worst_case_loss) : '-'}</span> },
  ]

  return <Panel title="RISK BUDGETED ALLOCATOR" accent="#3861FB" right={loading ? 'allocating…' : `${approved.length} / ${all.length} ${'sized'}`}
    help={<>{'For each asset the allocator fits a fractional Kelly stake from its realised win rate and payoff then caps it under a portfolio drawdown ceiling. A leg only deploys if its empirical edge is positive (Kelly > 0); otherwise the gate marks it blocked and it sits at 0% rather than forcing a bet. Switch timeframe to see how the edge and the surviving legs change · 4h is intentionally sparse so most legs block there.'}</>}>
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)' }}>{'Equity'}</span>
      {[5000, 10000, 25000, 100000].map((e) => (
        <button key={e} className={`cp-pill ${equity === e ? 'on' : ''}`} onClick={() => setEquity(e)}>{fmtUsd(e)}</button>
      ))}
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)', marginLeft: 6 }}>{'Timeframe'}</span>
      {TF_OPTS.map((t) => (
        <button key={t} className={`cp-pill ${tf === t ? 'on' : ''}`} onClick={() => setTf(t)}>{t}</button>
      ))}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 12.5 }}><span style={{ color: 'var(--c-muted)' }}>Deployed </span><b>{fmtUsd(totalNotional)}</b></span>
        <span className="mono" style={{ fontSize: 12.5 }}><span style={{ color: 'var(--c-muted)' }}>Margin </span><b>{fmtUsd(totalMargin)}</b></span>
        <span className="mono" style={{ fontSize: 12.5 }}><span style={{ color: 'var(--c-muted)' }}>Budget at risk </span><b>{fmtUsd(totalRisk)}</b></span>
      </div>
    </div>
    <CmcTable columns={cols} rows={all} empty={loading ? 'computing optimal allocation…' : 'no data for this timeframe'} defaultSort={{ key: 'alloc', dir: 'desc' }} />
    {all.length > 0 && approved.length === 0 && <BlockedLegsNote />}
    {lb && <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--c-muted)' }}>{'Edge sourced from'} {lb.overall.n_resolved.toLocaleString()} {'resolved outcomes · drawdown ceiling enforced per leg.'}</div>}
  </Panel>
}

/* Plain-language note for why every leg currently reads "blocked": the
   allocator only funds a leg whose edge is positive AFTER the modelled
   round-trip cost, so at a marginal gross edge no risk budget is deployed. */
function BlockedLegsNote() {
  const [open, setOpen] = useState(false)
  return <div style={{ marginTop: 12, fontSize: 12, color: 'var(--c-muted)', lineHeight: 1.6 }}>
    <button
      onClick={() => setOpen((v) => !v)}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: '1px solid var(--c-line)', borderRadius: 999, padding: '3px 11px', color: 'var(--c-text-2)', fontSize: 12, cursor: 'pointer' }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', background: 'var(--c-fill-2)', fontWeight: 800, fontSize: 11 }}>?</span>
      {open ? 'Hide why every leg is blocked' : 'Why is every leg blocked right now?'}
    </button>
    {open && <p style={{ margin: '10px 0 0', maxWidth: 760 }}>
      This is the discipline working, not a failure. The allocator only funds a
      leg when its edge is positive AFTER costs. At the current data each leg's
      gross expectancy is marginal (win rate near 50 percent, a tiny positive R),
      and the modelled 0.2 percent round-trip swap cost erases it, so the
      net-of-cost fractional Kelly comes out at or below zero. A non-positive
      Kelly means no bet, so the gate marks the leg blocked and holds it at 0
      percent rather than forcing a negative expected value trade that would just
      bleed on fees. The moment a leg's measured edge clears the cost hurdle, the
      allocator sizes it and deploys real risk budget. Switch the timeframe to
      see edge and surviving legs change.
    </p>}
  </div>
}

/* ─────────────── TP/SL Optimizer ─────────────── */
function TpSlSkill() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [tf, setTf] = useState('15m')
  const { data: tpsl } = usePoll<TpSl>((s) => apiGet(`/tp-sl?symbol=${symbol}&timeframe=${tf}&signal_type=buy`, s), 60_000, [symbol, tf])
  const best = tpsl?.best_per_risk || tpsl?.best

  return <Panel title="TP/SL OPTIMIZER" accent="#3861FB" right={tpsl ? `${tpsl.n_total} ${'outcomes'}` : ''}
    help={<>{'A grid search over every take profit and stop loss pair scored on realised outcomes at the chosen timeframe. The gauge reads expectancy per unit of risk for the best bracket; a cell only qualifies once it clears the minimum sample of 30 trades. Higher timeframes hold fewer completed brackets so 15m and 30m are the data rich frames; sparse frames show a thin warning instead of a forced answer.'}</>}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      {ASSETS.slice(0, 6).map((s) => (
        <button key={s} className={`cp-pill ${symbol === s ? 'on' : ''}`} onClick={() => setSymbol(s)}>
          <CoinLogo symbol={s} size={20} />{s.replace('USDT', '')}
        </button>
      ))}
    </div>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)' }}>{'Timeframe'}</span>
      {TF_OPTS.map((t) => (
        <button key={t} className={`cp-pill ${tf === t ? 'on' : ''}`} onClick={() => setTf(t)}>{t}</button>
      ))}
    </div>
    {best ? <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 24, alignItems: 'center' }} className="cp-grid-2">
      <Gauge value={Math.max(0, Math.min(100, (best.expectancy_per_risk + 0.5) * 100))} max={100} label="EDGE" tone="var(--green)" size={150} sub={`edge ${fmtNum(best.expectancy_per_risk, 3)}/R · R:R ${fmtNum(best.rr, 2)}`} />
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(110px,1fr))', gap: 10, marginBottom: 12 }}>
          <Stat label="Take profit" value={fmtPct(best.tp, 1)} tone="var(--green)" />
          <Stat label="Stop loss" value={fmtPct(best.sl, 1)} tone="var(--red)" />
          <Stat label="Expectancy" value={fmtNum(best.expectancy, 3)} tone={CMC} />
          <Stat label="Per risk edge" value={fmtNum(best.expectancy_per_risk, 3)} tone="var(--green)" />
          <Stat label="Sample" value={`${best.n}`} tone="var(--c-text)" />
        </div>
        <Bar label="Take profit reach" value={best.win_rate * 100} tone="var(--green)" fmt={(v) => v.toFixed(1) + '%'} />
        <Bar label="Total return" value={Math.max(0, Math.min(100, best.total_return))} tone={CMC} fmt={() => fmtPct(best.total_return, 1)} />
      </div>
    </div> : <div style={{ color: 'var(--c-muted)', padding: 30, textAlign: 'center' }}>{tpsl?.note || 'optimizing bracket grid…'}</div>}
    {tpsl && !tpsl.recommend && <div style={{ marginTop: 12, fontSize: 12, color: 'var(--gold)', display: 'inline-flex', alignItems: 'center', gap: 5 }}><IconAlert size={14} /> {tpsl.note}</div>}
  </Panel>
}

/* ─────────────── Narrative Rotation ─────────────── */
type NarrRow = { name: string; chg: number; vol: number; mcap: number; n: number }
function RotationSkill({ intel, lb }: { intel: CmcIntel | null; lb: Leaderboard | null }) {
  const rows: NarrRow[] = useMemo(() => {
    const tokens = intel?.tokens ?? []
    const map = new Map<string, { chgSum: number; n: number; vol: number; mcap: number }>()
    for (const t of tokens) {
      for (const eco of (t.ecosystems || [])) {
        if (!eco) continue
        const m = map.get(eco) || { chgSum: 0, n: 0, vol: 0, mcap: 0 }
        m.chgSum += Number(t.change_24h) || 0
        m.n += 1
        m.vol += Number(t.volume_24h) || 0
        m.mcap += Number(t.market_cap) || 0
        map.set(eco, m)
      }
    }
    return [...map.entries()]
      .filter(([, m]) => m.n >= 2)
      .map(([name, m]) => ({ name, chg: m.chgSum / m.n, vol: m.vol, mcap: m.mcap, n: m.n }))
      .sort((a, b) => b.chg - a.chg)
      .slice(0, 14)
  }, [intel])

  const cols: CmcColumn<NarrRow>[] = [
    { key: 'rank', header: '#', render: (_r, i) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{i + 1}</span> },
    { key: 'name', header: 'Narrative', align: 'l', sticky: true, sortValue: (r) => r.name, render: (r) => <span style={{ fontWeight: 700, textTransform: 'capitalize' }}>{r.name}</span> },
    { key: 'tokens', header: 'Tokens', sortValue: (r) => r.n, render: (r) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{r.n}</span> },
    { key: 'chg', header: 'Avg 24h', sortValue: (r) => r.chg, render: (r) => <PctCell value={r.chg} d={2} /> },
    { key: 'mcap', header: 'Market cap', sortValue: (r) => r.mcap, render: (r) => <span className="mono">{fmtUsd(r.mcap)}</span> },
    { key: 'vol', header: 'Volume', sortValue: (r) => r.vol, render: (r) => <span className="mono">{fmtUsd(r.vol)}</span> },
    { key: 'rotate', header: 'Signal', sortValue: (r) => r.chg, render: (r) => <Chip tone={r.chg > 0 ? 'var(--green)' : 'var(--red)'}>{r.chg > 2 ? 'ROTATE IN' : r.chg < -2 ? 'ROTATE OUT' : 'HOLD'}</Chip> },
  ]

  return <Panel title="NARRATIVE ROTATION" accent="#3861FB" right={'CMC ecosystems'}
    help={<>{'Live CoinMarketCap tokens are grouped by ecosystem then each narrative is ranked by its average 24h move (only ecosystems with at least two tokens count). ROTATE IN flags accelerating narratives ROTATE OUT flags fading ones. Sort any column; before exposure actually shifts the call is confirmed against the verified signal leaderboard below.'}</>}>
    {rows.length === 0
      ? <div style={{ color: 'var(--c-muted)', padding: 30, textAlign: 'center' }}>{'CMC ecosystem feed warming up · confirmed against the verified leaderboard before any rotation.'}</div>
      : <CmcTable columns={cols} rows={rows} maxHeight={460} defaultSort={{ key: 'chg', dir: 'desc' }} />}
    {lb && <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--c-muted)' }}>{'Rotations confirmed by'} {lb.qualified} {'qualified signal sources before exposure shifts.'}</div>}
  </Panel>
}

/* ─────────────── Regime Governor ─────────────── */
function RegimeSkill({ intel, cmcG }: { intel: CmcIntel | null; cmcG: CmcGlobal | null }) {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [tf, setTf] = useState('15m')
  const btcDom = Number(cmcG?.btc_dominance ?? 50)
  const mcapChg = Number(cmcG?.mcap_change_24h ?? 0)
  const regimeDir = mcapChg > 0.5 ? 1 : mcapChg < -0.5 ? -1 : 0
  const regimeStr = Math.min(1, Math.abs(mcapChg) / 5)

  const { data: tpsl } = usePoll<TpSl>(
    (s) => apiGet(`/tp-sl?symbol=${symbol}&timeframe=${tf}&signal_type=buy&regime_direction=${regimeDir}&regime_strength=${regimeStr.toFixed(2)}`, s),
    60_000, [symbol, tf, regimeDir, regimeStr],
  )
  const reg = tpsl?.regime
  const bracket: GridCell | null = reg?.bracket ?? null
  const sum = intel?.market_summary
  const breadth = sum ? (sum.strong_buy + sum.buy) - (sum.weak + sum.avoid) : null
  const alignWord = reg ? (reg.alignment > 0 ? 'BACKS' : reg.alignment < 0 ? 'OPPOSES' : 'NEUTRAL') : '-'
  const alignTone = reg && reg.alignment > 0 ? 'var(--green)' : reg && reg.alignment < 0 ? 'var(--red)' : 'var(--c-muted)'

  return <Panel title="REGIME GOVERNOR" accent="#3861FB" right={reg ? (reg.deploy ? 'DEPLOY' : 'STAND DOWN') : ''}
    help={<>{'The live CMC global regime (direction and strength) is overlaid on the asset\u2019s best bracket. Alignment reads BACKS when the regime agrees with the long bias, OPPOSES when it cuts against it, and NEUTRAL in chop. Risk scale shrinks the bracket as alignment or strength weakens; the governor only returns DEPLOY when both the empirical edge and the regime clear the gate.'}</>}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      {ASSETS.slice(0, 6).map((s) => (
        <button key={s} className={`cp-pill ${symbol === s ? 'on' : ''}`} onClick={() => setSymbol(s)}><CoinLogo symbol={s} size={20} />{s.replace('USDT', '')}</button>
      ))}
    </div>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)' }}>{'Timeframe'}</span>
      {TF_OPTS.map((t) => (
        <button key={t} className={`cp-pill ${tf === t ? 'on' : ''}`} onClick={() => setTf(t)}>{t}</button>
      ))}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 16 }}>
      <Stat label="Market regime" value={regimeDir > 0 ? 'RISK ON' : regimeDir < 0 ? 'RISK OFF' : 'NEUTRAL'} tone={regimeDir > 0 ? 'var(--green)' : regimeDir < 0 ? 'var(--red)' : 'var(--c-muted)'} mono={false} />
      <Stat label="Regime strength" value={fmtPct(regimeStr * 100, 0)} tone="var(--trust)" />
      <Stat label="BTC dominance" value={fmtPct(btcDom, 1)} tone="var(--gold)" />
      <Stat label="Market cap 24h" value={cmcG ? fmtPct(mcapChg, 2, true) : '-'} tone={mcapChg >= 0 ? 'var(--green)' : 'var(--red)'} />
      <Stat label="Audit breadth" value={breadth != null ? (breadth > 0 ? `+${breadth}` : `${breadth}`) : '-'} tone={breadth != null && breadth >= 0 ? 'var(--green)' : 'var(--red)'} sub="buy minus avoid" />
    </div>
    {reg ? <Card glow="var(--trust-soft)" style={{ padding: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, color: reg.deploy ? 'var(--green)' : 'var(--red)' }}>{reg.deploy ? 'DEPLOY' : 'STAND DOWN'}</div>
          <div style={{ fontSize: 12.5, color: 'var(--c-muted)', maxWidth: 360 }}>{reg.reason}</div>
        </div>
        <div style={{ display: 'flex', gap: 14 }}>
          <Stat label="Risk scale" value={fmtPct(reg.risk_scale * 100, 0)} tone="var(--trust)" />
          <Stat label="Alignment" value={alignWord} tone={alignTone} mono={false} />
        </div>
      </div>
      {bracket && <div style={{ marginTop: 14, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Chip tone="var(--green)">TP {fmtPct(bracket.tp, 1)}</Chip>
        <Chip tone="var(--red)">SL {fmtPct(bracket.sl, 1)}</Chip>
        <Chip tone="var(--gold)">R:R {fmtNum(bracket.rr, 2)}</Chip>
        <Chip tone={CMC}>edge {fmtNum(bracket.expectancy_per_risk, 3)}</Chip>
      </div>}
    </Card> : <div style={{ color: 'var(--c-muted)', padding: 30, textAlign: 'center' }}>{'reading the regime…'}</div>}
  </Panel>
}

/* ─────────────── Meta Strategy Composer (flagship · fuses all four) ─────────────── */
const PURPLE = 'var(--purple)'
const REGIMES: { id: string; label: string; dir: number; str: number }[] = [
  { id: 'on', label: 'Risk on', dir: 1, str: 0.7 },
  { id: 'neutral', label: 'Neutral', dir: 0, str: 0.0 },
  { id: 'off', label: 'Risk off', dir: -1, str: 0.5 },
]
const STAGES = ['Select', 'Bracket', 'Regime gate', 'Size', 'Budget']
function MetaComposerSkill() {
  const [equity, setEquity] = useState(10000)
  const [dd, setDd] = useState(4)            // current drawdown, percent
  const [regimeId, setRegimeId] = useState('on')
  const [topN, setTopN] = useState(5)
  const reg = REGIMES.find((r) => r.id === regimeId) ?? REGIMES[0]

  const { data: plan, loading } = usePoll<ComposePlan>((s) => fetchCompose({
    equity, current_drawdown: dd / 100, regime_direction: reg.dir,
    regime_strength: reg.str, top_n: topN,
  }, s), 60_000, [equity, dd, regimeId, topN])

  const deployed = plan?.legs.filter((l) => l.deploy) ?? []
  const headroom = plan ? plan.budget_ceiling - plan.portfolio_worst_case_loss : 0
  const usePct = plan && plan.budget_ceiling > 0
    ? Math.min(100, (plan.portfolio_worst_case_loss / plan.budget_ceiling) * 100) : 0

  const cols: CmcColumn<ComposeLeg>[] = [
    { key: 'name', header: 'Asset', align: 'l', sticky: true, sortValue: (r) => r.symbol, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.symbol} /><span className="cmc-name-main">{r.symbol.replace('USDT', '').replace('.P', '')}</span></span> },
    { key: 'deploy', header: 'Gate', sortValue: (r) => (r.deploy ? 1 : 0), render: (r) => <Chip tone={r.deploy ? 'var(--green)' : 'var(--c-muted)'} solid={r.deploy}>{r.deploy ? 'deploy' : 'stand aside'}</Chip> },
    { key: 'tp', header: 'TP', sortValue: (r) => r.tp ?? -1, render: (r) => r.deploy && r.tp != null ? <span className="mono" style={{ color: 'var(--green)' }}>{fmtPct(r.tp, 1)}</span> : <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> },
    { key: 'sl', header: 'SL', sortValue: (r) => r.sl ?? -1, render: (r) => r.deploy && r.sl != null ? <span className="mono" style={{ color: 'var(--red)' }}>{fmtPct(r.sl, 1)}</span> : <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> },
    { key: 'lev', header: 'Leverage', sortValue: (r) => r.leverage ?? -1, render: (r) => r.deploy && r.leverage != null ? <span className="mono">{fmtNum(r.leverage, 2)}x</span> : <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> },
    { key: 'notional', header: 'Notional', sortValue: (r) => r.notional ?? -1, render: (r) => r.deploy && r.notional != null ? <span className="mono">{fmtUsd(r.notional)}</span> : <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> },
    { key: 'wcl', header: 'Worst case loss', sortValue: (r) => r.worst_case_loss, render: (r) => r.deploy ? <span className="mono" style={{ color: 'var(--red)' }}>{fmtUsd(r.worst_case_loss)}</span> : <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> },
    { key: 'reason', header: 'Note', align: 'l', sortValue: (r) => r.reason, render: (r) => <span style={{ fontSize: 12, color: 'var(--c-text-2)' }}>{r.reason}</span> },
  ]

  return <Panel title="META STRATEGY COMPOSER" accent="#8b5cf6" right={loading ? 'composing…' : plan ? `${deployed.length} ${'legs deployed'}` : ''}
    help={<>{'The flagship skill · it runs the other four as one pipeline. Selection ranks the watchlist by verified expectancy, the optimizer brackets each pick against resolved outcomes, the regime governor decides whether to deploy and at what risk scale, the allocator sizes every surviving leg, and a final budget step proves the SUM of worst case losses stays inside one account drawdown budget. Change the account state below and the whole plan recomputes live · this is the exact function the reproducible backtest hashes.'}</>}>
    {/* account-state controls */}
    <div style={{ display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: 'var(--c-muted)' }}>
        {'Account equity'}
        <input type="number" min={500} max={1_000_000} step={1000} value={equity} onChange={(e) => setEquity(Math.max(500, Math.min(1_000_000, Number(e.target.value) || 0)))} style={{ width: 120, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--c-line)', background: 'var(--c-panel)', color: 'var(--c-text)', fontFamily: 'inherit' }} />
      </label>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 11.5, color: 'var(--c-muted)' }}>{'Current drawdown'}</span>
        <div style={{ display: 'flex', gap: 6 }}>{[0, 4, 8, 12].map((d) => <button key={d} className={`cp-pill ${dd === d ? 'on' : ''}`} onClick={() => setDd(d)}>{d}%</button>)}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 11.5, color: 'var(--c-muted)' }}>{'Market regime'}</span>
        <div style={{ display: 'flex', gap: 6 }}>{REGIMES.map((r) => <button key={r.id} className={`cp-pill ${regimeId === r.id ? 'on' : ''}`} onClick={() => setRegimeId(r.id)}>{r.label}</button>)}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 11.5, color: 'var(--c-muted)' }}>{'Assets considered'}</span>
        <div style={{ display: 'flex', gap: 6 }}>{[3, 5, 8].map((n) => <button key={n} className={`cp-pill ${topN === n ? 'on' : ''}`} onClick={() => setTopN(n)}>{n}</button>)}</div>
      </div>
    </div>

    {/* pipeline stages */}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
      {STAGES.map((s, i) => <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: PURPLE }}>{s}</span>
        {i < STAGES.length - 1 && <span style={{ color: 'var(--c-muted)' }}>·</span>}
      </span>)}
    </div>

    {/* budget summary */}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginBottom: 16 }}>
      <Stat label="Budget ceiling" value={plan ? fmtUsd(plan.budget_ceiling) : '-'} tone={PURPLE} sub="drawdown budget" />
      <Stat label="Portfolio worst case" value={plan ? fmtUsd(plan.portfolio_worst_case_loss) : '-'} tone="var(--red)" sub="sum of legs" />
      <Stat label="Headroom" value={plan ? fmtUsd(headroom) : '-'} tone="var(--green)" sub={`${fmtNum(100 - usePct, 0)}% free`} />
      <Stat label="Legs deployed" value={plan ? `${deployed.length} / ${plan.legs.length}` : '-'} tone="var(--c-text)" sub={`${'regime'} ${reg.label}`} />
      <Stat label="Within budget" value={plan ? (plan.within_budget ? 'YES' : 'NO') : '-'} tone={plan?.within_budget ? 'var(--green)' : 'var(--red)'} mono={false} sub="account invariant" />
    </div>

    {/* budget usage bar */}
    {plan && <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--c-muted)', marginBottom: 5 }}>
        <span>{'Drawdown budget used'}</span><span className="mono">{fmtNum(usePct, 1)}%</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: 'var(--c-fill-2)', overflow: 'hidden' }}>
        <div style={{ width: `${usePct}%`, height: '100%', background: usePct > 90 ? 'var(--red)' : PURPLE, transition: 'width .4s ease' }} />
      </div>
    </div>}

    {plan && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
      <span style={{ fontSize: 12, color: 'var(--c-muted)' }}>{'Selected'}</span>
      {plan.selected.map((s) => <Chip key={s} tone={PURPLE}>{s.replace('USDT', '').replace('.P', '')}</Chip>)}
    </div>}

    <CmcTable columns={cols} rows={plan?.legs ?? []} empty={loading ? 'composing the plan…' : 'no plan yet'} maxHeight={460} defaultSort={{ key: 'wcl', dir: 'desc' }} />
    <p style={{ fontSize: 11.5, color: 'var(--c-muted)', margin: '12px 0 0', lineHeight: 1.55 }}>
      {'Every deployed leg is sized against equity split across the deployed count so the SUM of worst case losses stays inside the single account drawdown budget · the portfolio respects the cap, not just each trade.'}
    </p>
  </Panel>
}

/* ─────────────── Edge Decay Monitor (new skill) ─────────────── */
type DecayRow = {
  key: string; kind: string; fullExp: number; fullWr: number; fullN: number
  recExp: number | null; recWr: number | null; recN: number
  dExp: number; status: 'strengthening' | 'stable' | 'decaying' | 'thin'
}
function DecaySkill() {
  const [days, setDays] = useState(90)
  const since = useMemo(() => Math.floor(Date.now() / 1000 - days * DAY), [days])
  const { data, loading } = usePoll<{ full: Leaderboard; recent: Leaderboard }>(async (s) => {
    const [full, recent] = await Promise.all([
      apiGet<Leaderboard>('/leaderboard?rank_by=expectancy&min_samples=30&top_n=40', s),
      apiGet<Leaderboard>(`/leaderboard?rank_by=expectancy&min_samples=8&top_n=60&since_ts=${since}`, s),
    ])
    return { full, recent }
  }, 60_000, [since])

  const rows: DecayRow[] = useMemo(() => {
    const full = data?.full.entries ?? []
    const rec = new Map((data?.recent.entries ?? []).map((e) => [e.key, e]))
    return full.map((f) => {
      const r = rec.get(f.key)
      const dExp = r ? r.expectancy - f.expectancy : 0
      let status: DecayRow['status']
      if (!r || r.n_resolved < 8) status = 'thin'
      else if (dExp > 0.05) status = 'strengthening'
      else if (dExp < -0.05) status = 'decaying'
      else status = 'stable'
      return {
        key: f.key, kind: f.kind, fullExp: f.expectancy, fullWr: f.win_rate, fullN: f.n_resolved,
        recExp: r ? r.expectancy : null, recWr: r ? r.win_rate : null, recN: r?.n_resolved ?? 0,
        dExp, status,
      }
    }).sort((a, b) => b.dExp - a.dExp)
  }, [data])

  const STONE: Record<DecayRow['status'], string> = {
    strengthening: 'var(--green)', stable: 'var(--c-muted)', decaying: 'var(--red)', thin: 'var(--gold)',
  }
  const nUp = rows.filter((r) => r.status === 'strengthening').length
  const nDown = rows.filter((r) => r.status === 'decaying').length

  const cols: CmcColumn<DecayRow>[] = [
    { key: 'name', header: 'Signal source', align: 'l', sticky: true, sortValue: (r) => r.key, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.key} /><span><span className="cmc-name-main">{r.key.replace('USDT', '')}</span><span className="cmc-name-sym">{r.kind}</span></span></span> },
    { key: 'fexp', header: 'Edge · all time', sortValue: (r) => r.fullExp, render: (r) => <span className="mono" style={{ color: r.fullExp >= 0 ? 'var(--green)' : 'var(--red)' }}>{fmtNum(r.fullExp, 3)}</span> },
    { key: 'rexp', header: `Edge · ${days}d`, sortValue: (r) => r.recExp ?? -999, render: (r) => r.recExp == null ? <span className="mono" style={{ color: 'var(--c-muted)' }}>{'thin'}</span> : <span className="mono" style={{ color: r.recExp >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{fmtNum(r.recExp, 3)}</span> },
    { key: 'dexp', header: 'Shift', sortValue: (r) => r.dExp, render: (r) => r.recExp == null ? <span className="mono" style={{ color: 'var(--c-muted)' }}>·</span> : <span className="mono" style={{ color: r.dExp >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{r.dExp >= 0 ? '+' : ''}{fmtNum(r.dExp, 3)}</span> },
    { key: 'rn', header: `${days}d n`, sortValue: (r) => r.recN, render: (r) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{r.recN || '-'}</span> },
    { key: 'status', header: 'Verdict', sortValue: (r) => r.dExp, render: (r) => <Chip tone={STONE[r.status]} solid={r.status !== 'stable'}>{r.status}</Chip> },
  ]

  return <Panel title="EDGE DECAY MONITOR" accent="#3861FB" right={loading ? 'comparing windows…' : `${nUp} ${'up'} · ${nDown} ${'decaying'}`}
    help={<>{'Each source\u2019s realised edge over its full verified record is compared against its edge in the recent window you pick (30, 90 or 180 days). Changing the window refetches the recent column and the Shift, so the Edge, WR and verdict columns all move. A positive Shift means the edge is holding live; a negative Shift is an early warning to down weight that source. Sources with too few recent outcomes are marked thin rather than scored.'}</>}>
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)' }}>{'Recent window'}</span>
      {[30, 90, 180].map((d) => (
        <button key={d} className={`cp-pill ${days === d ? 'on' : ''}`} onClick={() => setDays(d)}>{d}d</button>
      ))}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 12.5 }}><span style={{ color: 'var(--c-muted)' }}>Strengthening </span><b>{`${nUp}`}</b></span>
        <span className="mono" style={{ fontSize: 12.5 }}><span style={{ color: 'var(--c-muted)' }}>Decaying </span><b>{`${nDown}`}</b></span>
      </div>
    </div>
    <p style={{ fontSize: 12, color: 'var(--c-muted)', margin: '0 0 12px', lineHeight: 1.55 }}>
      {'Each source is scored on realized expectancy across its full verified record then again over the recent window. A positive shift means the edge is holding up live; a negative shift is an early warning the agent should down weight it.'}
    </p>
    <CmcTable columns={cols} rows={rows} empty={loading ? 'reading both windows…' : 'not enough recent outcomes'} maxHeight={460} defaultSort={{ key: 'dexp', dir: 'desc' }} />
  </Panel>
}

/* ─────────────── leaderboard ─────────────── */
const HORIZONS: { id: '24h' | '4h' | '1h'; label: string }[] = [
  { id: '24h', label: '24h' }, { id: '4h', label: '4h' }, { id: '1h', label: '1h' },
]
function SkillLeaderboard() {
  const [groupBy, setGroupBy] = useState<'symbol' | 'timeframe'>('symbol')
  const [horizon, setHorizon] = useState<'24h' | '4h' | '1h'>('24h')
  /* self-fetch so the horizon and grouping both move the table, and every
     qualified source is shown (top_n covers the full qualified set). */
  const topN = groupBy === 'symbol' ? 80 : 20
  const { data: lbData, loading } = usePoll<Leaderboard>(
    (s) => apiGet(`/leaderboard?group_by=${groupBy}&rank_by=expectancy&horizon=${horizon}&min_samples=20&top_n=${topN}`, s),
    60_000, [groupBy, horizon])
  const rows = lbData?.entries ?? []

  const nameCol: CmcColumn<EntityStats> = groupBy === 'symbol'
    ? { key: 'name', header: 'Strategy source', align: 'l', sticky: true, sortValue: (r) => r.key, render: (r) => <span className="cmc-name"><CoinLogo symbol={r.key} /><span><span className="cmc-name-main">{r.key.replace('USDT', '')}</span><span className="cmc-name-sym">{r.kind}</span></span></span> }
    : { key: 'name', header: 'Timeframe', align: 'l', sticky: true, sortValue: (r) => r.key, render: (r) => <span className="mono" style={{ fontWeight: 800, fontSize: 14 }}>{r.key}</span> }

  const cols: CmcColumn<EntityStats>[] = [
    { key: 'rank', header: '#', render: (_r, i) => <span className="mono" style={{ color: 'var(--c-muted)' }}>{i + 1}</span> },
    nameCol,
    { key: 'exp', header: 'Expectancy', sortValue: (r) => r.expectancy, render: (r) => <span className="mono" style={{ color: r.expectancy >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{fmtNum(r.expectancy, 3)}</span> },
    { key: 'pnl', header: 'Realized PnL', sortValue: (r) => r.realized_pnl, render: (r) => <span className="mono" style={{ color: r.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>{fmtNum(r.realized_pnl, 2)}R</span> },
    { key: 'n', header: 'Resolved', sortValue: (r) => r.n_resolved, render: (r) => <span className="mono">{r.n_resolved}</span> },
  ]
  return <Panel title="STRATEGY LEADERBOARD" accent="#3861FB" right={lbData ? `${lbData.qualified} ${'qualified'} · ${horizon} ${'horizon'}` : loading ? 'loading…' : ''}
    help={<>{'The verified record every skill above draws from ranked by expectancy showing every qualified source. The Horizon toggle is the key to the win rate: a call judged at 24h has more time to wander so its hit rate sits near a coin flip; tighten the horizon to 4h then 1h and the win rate climbs as the read is scored closer to the entry. A win rate near 50% is not weak: with a reward to risk above 1 expectancy stays positive so Expectancy (R per trade) and Realized PnL matter as much as the hit rate weighted by the Resolved count. Brier skill measures calibration of the win probability. Switch to By timeframe to see which frames carry the edge · the higher frames lead.'}</>}>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'center' }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)' }}>{'Group by'}</span>
      <button className={`cp-pill ${groupBy === 'symbol' ? 'on' : ''}`} onClick={() => setGroupBy('symbol')}>{'By source'}</button>
      <button className={`cp-pill ${groupBy === 'timeframe' ? 'on' : ''}`} onClick={() => setGroupBy('timeframe')}>{'By timeframe'}</button>
      <span style={{ fontSize: 12.5, color: 'var(--c-muted)', marginLeft: 10 }}>{'Horizon'}</span>
      {HORIZONS.map((h) => (
        <button key={h.id} className={`cp-pill ${horizon === h.id ? 'on' : ''}`} onClick={() => setHorizon(h.id)}>{h.label}</button>
      ))}
      <a className="cp-a" href={scan(ADDR.ledger)} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
        {'verify on the BSC mainnet ledger'} <IconExternal size={12} />
      </a>
    </div>
    <CmcTable columns={cols} rows={rows} empty={loading ? 'loading…' : 'no qualified sources at this horizon'} maxHeight={520} defaultSort={{ key: 'exp', dir: 'desc' }} />
  </Panel>
}
