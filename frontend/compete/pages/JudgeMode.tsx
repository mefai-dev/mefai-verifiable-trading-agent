/* BNB HACK · Judge mode · the five minute verifiable tour.
   Verifiability is the wedge, so this page makes it impossible to miss. It walks
   a juror through the whole chain in one scroll: a live decision (fusion to
   conviction to bracket to sizing to the safety gate), then the commit hash, the
   reveal, the ledger write, the RiskGovernor cap and the rolled up leaderboard
   and UVII. Every step carries a live proof and a BscScan link. Nothing here is
   mocked; where a feed is briefly down the step says so. */

import type { ReactNode } from 'react'
import {
  Btn, Chip, Gauge, Reveal, Stat, CountUp, CoinLogo,
  fmtNum, shortAddr,
} from '../ui'
import { usePoll, fetchLoopState, fetchLeaderboard, fetchUvii } from '../api'
import type { LoopEnvelope, Leaderboard, UviiIndex } from '../api'
import { ADDR, AGENT_ID, ERC8004_AGENT_ID, GITHUB_URL, TELEGRAM_FEED_URL, scan, chainLabel, chainOf, txHashOf } from '../config'
import { IconExternal } from '../icons'
import { OmniSignalPanel } from './omniSignal'

const GOLD = 'var(--gold)'
const TRUST = 'var(--trust)'
const TOTAL = 6

/* a transaction explorer link on the same chain as the anchoring contract.
   hash may arrive as a full BscScan URL, so normalize to a bare hash first */
const txUrl = (hash: string, addr: string) =>
  `https://${chainOf(addr) === 97 ? 'testnet.bscscan.com' : 'bscscan.com'}/tx/${txHashOf(hash)}`

const STEP_KEYS = [
  'Live trade decision', 'Commit the call', 'Reveal the preimage',
  'Anchor to the ledger', 'Drawdown circuit breaker', 'Rolled up track record',
]

/* ─────────────── one tour step ─────────────── */
function TourStep({ n, title, verify, scanAddr, scanLabel, badge, children }: {
  n: number; title: string; verify: ReactNode; scanAddr?: string
  scanLabel?: string; badge?: ReactNode; children: ReactNode
}) {
  return <Reveal>
    <div className="cp-judge-step">
      <div className="cp-judge-rail" aria-hidden>
        <span className="cp-judge-n">{n}</span>
        {n < TOTAL && <span className="cp-judge-line" />}
      </div>
      <div className="cp-judge-body">
        <div className="cp-judge-head">
          <div style={{ minWidth: 0 }}>
            <div className="cp-judge-of mono">{'Step'} {n} / {TOTAL}</div>
            <h3 className="cp-judge-title">{title}</h3>
          </div>
          {badge}
        </div>
        <p className="cp-judge-verify"><b>{'Verify'}</b> {verify}</p>
        <div className="cp-judge-content">{children}</div>
        {scanAddr && <a className="cp-a cp-judge-scan" href={scan(scanAddr)} target="_blank" rel="noopener noreferrer">
          {scanLabel || 'Open on BscScan'} · {chainLabel(scanAddr)} <IconExternal size={12} />
        </a>}
      </div>
    </div>
  </Reveal>
}

function StatusChip({ ok, loading }: { ok: boolean; loading: boolean }) {
  if (loading) return <Chip tone="var(--c-muted)">{'sync'}</Chip>
  return ok ? <Chip tone="var(--green)" live>{'live'}</Chip> : <Chip tone="var(--red)">{'down'}</Chip>
}

function HashRow({ label, hash, addr }: { label: string; hash: string; addr: string }) {
  const h = txHashOf(hash)
  const placeholder = !h || !/^0x[0-9a-fA-F]+$/.test(h) || /^0x0+$/.test(h)
  return <div className="cp-judge-hashrow">
    <span className="cp-judge-hash-l">{label}</span>
    {placeholder
      ? <span className="cp-judge-hash-pending mono">{'pending broadcast'}</span>
      : <a className="cp-a mono cp-judge-hash" href={txUrl(h, addr)} target="_blank" rel="noopener noreferrer">
          {shortAddr(h)} <IconExternal size={11} />
        </a>}
  </div>
}

/* ─────────────── the page ─────────────── */
export default function JudgeMode({ go }: { go: (p: string) => void }) {
  const loop = usePoll<LoopEnvelope>((s) => fetchLoopState(s), 12_000)
  const lb = usePoll<Leaderboard>((s) => fetchLeaderboard('symbol', 'expectancy', '24h', 8, s), 120_000)
  const uvii = usePoll<UviiIndex>((s) => fetchUvii('symbol', '24h', 8, s), 120_000)

  const st = loop.data?.available ? loop.data.state : undefined
  /* prefer proofs that already carry a real broadcast tx; paper/pending ones follow */
  const hasTx = (h?: string) => { const x = txHashOf(h); return !!x && /^0x[0-9a-fA-F]+$/.test(x) && !/^0x0+$/.test(x) }
  const proofs = [...(st?.proofs || [])]
    .sort((a, b) => Number(hasTx(b.commit_tx)) - Number(hasTx(a.commit_tx))).slice(0, 4)
  const reveals = [...(st?.reveals || [])]
    .sort((a, b) => Number(hasTx(b.tx)) - Number(hasTx(a.tx))).slice(0, 4)
  const gov = st?.governor
  const gi = uvii.data?.global_index
  const capBps = st ? Math.round(st.jury_cap * 10000) : 2000
  const internalBps = st ? Math.round(st.internal_cap * 10000) : 1400
  const ddBps = gov ? Math.round(gov.dd_bps) : 0

  return <div style={{ maxWidth: 1080, margin: '0 auto', padding: '40px 22px 88px' }}>
    {/* ── hero ── */}
    <Reveal>
      <div className="cp-judge-hero">
        <h1 className="cp-judge-h1">{'Verify the whole chain in'} <span style={{ color: GOLD }}>{'five minutes'}</span></h1>
        <p className="cp-judge-lead">
          {'One scroll, six live proofs. A real trade decision is computed, the call is committed as a hash before the outcome is known, revealed after the window, anchored to the result ledger, capped by an on-ledger circuit breaker, and rolled up into one auditable index. Open any BscScan link to check it yourself.'}
        </p>
        <div className="cp-judge-cta">
          <Btn variant="gold" sm onClick={() => go('/compete/protocol')}>{'How the protocol works'}</Btn>
          <Btn variant="ghost" sm href={GITHUB_URL}>{'Read the source'}</Btn>
        </div>
      </div>
    </Reveal>

    {/* ── tour map ── */}
    <Reveal delay={60}>
      <div className="cp-judge-map">
        {STEP_KEYS.map((k, i) => (
          <div key={k} className="cp-judge-map-item">
            <span className="cp-judge-map-n">{i + 1}</span>
            <span className="cp-judge-map-t">{k}</span>
          </div>
        ))}
      </div>
    </Reveal>

    <div className="cp-judge-flow">
      {/* ── 1 · live decision ── */}
      <TourStep n={1} title="Live trade decision"
        verify={'Pick any asset. Every stage below is a live call to the same audited backend the autonomous agent runs each cycle: the CoinMarketCap hub and signal engine blend into one conviction, the council weighs in, a TP/SL bracket is fitted from labeled history, the position is sized against the drawdown budget, and the Trust Wallet safety gate clears or blocks it.'}>
        <OmniSignalPanel />
      </TourStep>

      {/* ── 2 · commit ── */}
      <TourStep n={2} title="Commit the call"
        badge={<StatusChip ok={!!st} loading={loop.loading} />}
        scanAddr={ADDR.registry} scanLabel={'Open the registry'}
        verify={<>{'Before any entry the agent writes'} <span className="mono" style={{ color: TRUST }}>keccak256(symbol, direction, entry, target, stop, expiry, salt)</span> {'to the commit reveal registry. The hash binds the prediction before the outcome exists, so the record cannot be backfilled. These are the latest commits.'}</>}>
        {loop.loading && <p className="cp-judge-note">{'Reading the live agent snapshot'}<span className="cp-ellipsis" /></p>}
        {!loop.loading && proofs.length === 0 && <p className="cp-judge-note">{'No commit is in the current window. The agent commits a hash the moment it takes a position; the registry link above shows the full history.'}</p>}
        {proofs.length > 0 && <div className="cp-judge-proofs">
          {proofs.map((p, i) => (
            <div key={`${p.symbol}-${i}`} className="cp-judge-proof">
              <div className="cp-judge-proof-top">
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontWeight: 700 }}><CoinLogo symbol={p.symbol} size={16} />{p.symbol}</span>
                <Chip tone={p.status === 'revealed' ? 'var(--green)' : 'var(--gold)'}>{p.status || 'committed'}</Chip>
              </div>
              <HashRow label="Commit tx" hash={p.commit_tx} addr={ADDR.registry} />
              {p.prediction_id != null && <div className="cp-judge-pid mono">{'prediction'} #{p.prediction_id}</div>}
            </div>
          ))}
        </div>}
      </TourStep>

      {/* ── 3 · reveal ── */}
      <TourStep n={3} title="Reveal the preimage"
        badge={<StatusChip ok={!!st} loading={loop.loading} />}
        scanAddr={ADDR.registry} scanLabel={'Open the registry'}
        verify={'After the prediction window the agent reveals the preimage and the contract verifies it hashes to the committed value. A reveal that does not match is rejected, so a call cannot be edited after the fact.'}>
        {loop.loading && <p className="cp-judge-note">{'Reading the live agent snapshot'}<span className="cp-ellipsis" /></p>}
        {!loop.loading && reveals.length === 0 && proofs.length === 0 && <p className="cp-judge-note">{'No reveal is in the current window. Reveals follow commits once the window closes; the registry link above shows them.'}</p>}
        {reveals.length > 0 && <div className="cp-judge-proofs">
          {reveals.map((r, i) => (
            <div key={`${r.symbol}-${i}`} className="cp-judge-proof">
              <div className="cp-judge-proof-top">
                <span style={{ fontWeight: 700 }}>{r.symbol}</span>
                <code className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{r.detail}</code>
              </div>
              <HashRow label="Reveal tx" hash={r.tx} addr={ADDR.registry} />
            </div>
          ))}
        </div>}
        {reveals.length === 0 && proofs.length > 0 && <div className="cp-judge-proofs">
          {proofs.filter((p) => hasTx(p.reveal_tx)).map((p, i) => (
            <div key={`${p.symbol}-${i}`} className="cp-judge-proof">
              <div className="cp-judge-proof-top"><span style={{ fontWeight: 700 }}>{p.symbol}</span><Chip tone="var(--green)">{'revealed'}</Chip></div>
              <HashRow label="Reveal tx" hash={p.reveal_tx} addr={ADDR.registry} />
            </div>
          ))}
        </div>}
      </TourStep>

      {/* ── 4 · ledger ── */}
      <TourStep n={4} title="Anchor to the ledger"
        scanAddr={ADDR.ledger} scanLabel={'Open the result ledger'}
        verify={'Each resolved outcome is written to the result ledger on BSC mainnet, where it cannot be deleted or rewritten. This is the same mainnet ledger the project has been writing trade outcomes to, so the track record predates the contest.'}>
        <div className="cp-judge-ledger">
          <Stat label={'Result ledger'} value={shortAddr(ADDR.ledger)} tone={GOLD} sub={'BSC mainnet · immutable'} mono />
          <Stat label={'Agent wallet'} value={shortAddr(ADDR.agent)} sub={'holds the mainnet identity'} mono />
          <Stat label={'ERC-8004 token id'} value={`#${ERC8004_AGENT_ID}`} tone={TRUST} sub={'minted on chain 56'} mono />
          <Stat label={'Commit id'} value={shortAddr(AGENT_ID)} sub={'internal registry seed'} mono />
        </div>
        <p className="cp-judge-note">{'The agent writes its judged commit reveal record on BSC mainnet so the contest record stays un backfillable, and anchors resolved outcomes to the mainnet result ledger. Both are linked from this tour.'}</p>
      </TourStep>

      {/* ── 5 · governor ── */}
      <TourStep n={5} title="Drawdown circuit breaker"
        badge={<StatusChip ok={!!gov} loading={loop.loading} />}
        scanAddr={ADDR.governor} scanLabel={'Open the RiskGovernor'}
        verify={<>{'A chain anchored RiskGovernor enforces the drawdown budget. The keeper feeds live equity to the contract; if drawdown crosses the cap the governor halts trading and no further entry can clear. The jury cap is'} {fmtNum(capBps, 0)} {'bps and the agent runs to a tighter internal cap of'} {fmtNum(internalBps, 0)} {'bps.'}</>}>
        {loop.loading && <p className="cp-judge-note">{'Reading the live agent snapshot'}<span className="cp-ellipsis" /></p>}
        {gov && <div className="cp-judge-gov">
          <Gauge value={Math.min(ddBps, internalBps)} max={internalBps} label={'drawdown'} tone={gov.ok ? 'var(--green)' : 'var(--red)'} size={120}
            sub={`${'cap'} ${fmtNum(internalBps, 0)} bps`} />
          <div className="cp-judge-gov-stats">
            <Stat label={'Governor'} value={gov.ok ? 'OK' : 'HALT'} tone={gov.ok ? 'var(--green)' : 'var(--red)'} sub={'live state'} />
            <Stat label={'Drawdown'} value={`${fmtNum(ddBps, 0)} bps`} tone={GOLD} sub={`${'internal cap'} ${fmtNum(internalBps, 0)}`} />
            {st && <Stat label={'Equity'} value={<CountUp value={st.equity} prefix="$" decimals={2} />} sub={'simulated book · real proofs'} />}
            {gov.record && <Stat label={'Record'} value={gov.record} sub={'keeper feed'} mono />}
          </div>
        </div>}
        {gov?.detail && <p className="cp-judge-note">{gov.detail}</p>}
      </TourStep>

      {/* ── 6 · track record ── */}
      <TourStep n={6} title="Rolled up track record"
        badge={<StatusChip ok={!!gi} loading={uvii.loading} />}
        scanAddr={ADDR.ledger} scanLabel={'Open the result ledger'}
        verify={'Every resolved outcome rolls up into one unified verifiable intelligence index, built only from calls that reached a recorded result. The leaderboard ranks each market by expectancy from the same labeled history. Nothing here counts an unresolved call.'}>
        {(uvii.loading || lb.loading) && !gi && <p className="cp-judge-note">{'Reading the live index'}<span className="cp-ellipsis" /></p>}
        {gi && <div className="cp-judge-uvii">
          <Gauge value={gi.score} max={100} label={'Global UVII'} tone={GOLD} size={120} sub={'0 to 100'} />
          <div className="cp-judge-uvii-stats">
            <Stat label={'Integrity'} value={fmtNum(gi.integrity_score, 1)} tone="var(--green)" sub={'resolved share'} />
            <Stat label={'Skill'} value={fmtNum(gi.skill_score, 1)} tone="var(--cmc)" sub={'win rate'} />
            <Stat label={'Discipline'} value={fmtNum(gi.discipline_score, 1)} tone={GOLD} sub={'drawdown'} />
            <Stat label={'Resolved'} value={<CountUp value={gi.n_resolved} />} sub={'outcomes'} />
          </div>
        </div>}
        {lb.data && lb.data.entries.length > 0 && <div className="cp-judge-lb">
          {lb.data.entries.slice(0, 6).map((e) => (
            <div key={e.key} className="cp-judge-lb-row">
              <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 700, fontSize: 12.5 }}><CoinLogo symbol={e.key} size={15} />{e.key.replace('.P', '')}</span>
              <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span className="mono" style={{ fontSize: 11, color: 'var(--c-muted)' }}>{fmtNum(e.n_resolved, 0)} {'res'}</span>
                <span className="mono" style={{ fontSize: 12.5, fontWeight: 700, color: e.expectancy >= 0 ? 'var(--green)' : 'var(--red)', minWidth: 52, textAlign: 'right' }}>{fmtNum(e.expectancy, 3)}</span>
              </span>
            </div>
          ))}
        </div>}
      </TourStep>
    </div>

    {/* ── close · prose lead, then a row of identical actions ── */}
    <Reveal>
      <div className="cp-judge-close">
        <h3 style={{ margin: 0, fontSize: 19, fontWeight: 800 }}>{'That is the whole loop, verified.'}</h3>
        <p style={{ color: 'var(--c-text-2)', lineHeight: 1.65, fontSize: 14, margin: '10px 0 16px' }}>
          {'A decision you can reproduce, a commit you can check before the outcome, a reveal that has to match, a ledger that cannot be edited, a circuit breaker that cannot be talked past, and an index built only from proven calls. Want to watch it happen in real time? Start @mefainews_bot in Telegram and it sends you a direct message for every trade leg during the judged window, each with a BscScan link · read only. Explore the live cockpit or read the protocol in full.'}
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Btn variant="gold" sm onClick={() => go('/compete/agent')}>{'Live agent cockpit'}</Btn>
          <Btn variant="gold" sm onClick={() => go('/compete/protocol')}>{'Verifiable protocol'}</Btn>
          <Btn variant="gold" sm href={TELEGRAM_FEED_URL}>{'Get trade alerts on Telegram'}</Btn>
          <Btn variant="gold" sm onClick={() => go('/compete/docs')}>{'Full documentation'}</Btn>
        </div>
      </div>
    </Reveal>
  </div>
}
