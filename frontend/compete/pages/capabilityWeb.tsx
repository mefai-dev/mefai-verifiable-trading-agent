/* BNB HACK · the capability web.
   The cross sponsor money shot: CoinMarketCap data converges into MEFAI's
   decision engine, flows out through Trust Wallet execution, and settles as
   proof on BNB Chain. Every node is a real capability from skills.ts and clicks
   through to its dossier, so a judge can trace one trade from data to proof and
   see all three sponsors wired into a single flow. Lightweight hand drawn SVG,
   theme aware, no chart library. */

import { useState } from 'react'
import { SkillModal } from './skillCatalog'
import { GROUP_TONE, skillById } from '../skills'

type Lane = { key: string; title: string; tone: string; ids: string[] }

const MEFAI_TONE = '#A78BFA'

const LANES: Lane[] = [
  { key: 'cmc', title: 'CoinMarketCap', tone: GROUP_TONE.cmc, ids: ['cmc-global', 'cmc-quotes', 'cmc-narratives', 'cmc-deriv', 'cmc-orderflow'] },
  { key: 'mefai', title: 'MEFAI decision', tone: MEFAI_TONE, ids: ['bnb-omni', 'bnb-fusion', 'bnb-council', 'bnb-sizing', 'bnb-tpsl'] },
  { key: 'trust', title: 'Trust Wallet', tone: GROUP_TONE.trust, ids: ['tw-risk', 'tw-swap', 'tw-transfer', 'tw-serve'] },
  { key: 'bnb', title: 'BNB Chain', tone: GROUP_TONE.bnb, ids: ['bnb-registry', 'bnb-ledger', 'bnb-identity', 'bnb-x402'] },
]

const STAGE_TAG: Record<string, string> = {
  cmc: 'data', mefai: 'decision', trust: 'execution', bnb: 'settlement',
}

/* short, readable labels for the graph; the dossier keeps the full name */
const LABEL: Record<string, string> = {
  'cmc-global': 'Global metrics', 'cmc-quotes': 'Live quotes', 'cmc-narratives': 'Narratives',
  'cmc-deriv': 'Derivatives', 'cmc-orderflow': 'Order flow',
  'bnb-omni': 'Omni Signal', 'bnb-fusion': 'Signal fusion', 'bnb-council': 'AI council', 'bnb-sizing': 'Kelly sizing',
  'bnb-tpsl': 'TP/SL optimizer',
  'tw-risk': 'Safety gate', 'tw-swap': 'Swap', 'tw-transfer': 'Transfer', 'tw-serve': 'Autonomous loop',
  'bnb-registry': 'Commit reveal', 'bnb-ledger': 'Result ledger', 'bnb-identity': 'ERC-8004 identity', 'bnb-x402': 'x402 feed',
}

/* cross stage flow: data converges, decision sizes, execution acts, chain proves */
const EDGES: [string, string][] = [
  ['cmc-global', 'bnb-omni'], ['cmc-quotes', 'bnb-omni'], ['cmc-narratives', 'bnb-omni'],
  ['cmc-deriv', 'bnb-omni'], ['cmc-orderflow', 'bnb-omni'],
  ['bnb-omni', 'tw-risk'], ['bnb-tpsl', 'tw-risk'], ['bnb-sizing', 'tw-swap'],
  ['tw-swap', 'bnb-registry'], ['tw-transfer', 'bnb-registry'], ['tw-serve', 'bnb-registry'],
]
/* within stage chains, drawn as a thin spine */
const SPINE: [string, string][] = [
  ['bnb-omni', 'bnb-fusion'], ['bnb-fusion', 'bnb-council'], ['bnb-council', 'bnb-sizing'], ['bnb-sizing', 'bnb-tpsl'],
  ['bnb-registry', 'bnb-ledger'], ['bnb-ledger', 'bnb-identity'], ['bnb-identity', 'bnb-x402'],
]

/* ─────────────── geometry ─────────────── */
const VW = 1000, VH = 392
const NODE_W = 190, NODE_H = 44, STEP = 60
const NODES_TOP = 74
const MAX_N = 5
const laneX = (i: number) => 70 + i * ((VW - 140) / (LANES.length - 1))

type Pos = { x: number; y: number; cx: number; cy: number; tone: string; laneKey: string; id: string }

function buildPositions(): Record<string, Pos> {
  const map: Record<string, Pos> = {}
  LANES.forEach((lane, li) => {
    const cx = laneX(li)
    const n = lane.ids.length
    const offset = ((MAX_N - n) * STEP) / 2
    lane.ids.forEach((id, ni) => {
      const cy = NODES_TOP + offset + ni * STEP + NODE_H / 2
      map[id] = { x: cx - NODE_W / 2, y: cy - NODE_H / 2, cx, cy, tone: lane.tone, laneKey: lane.key, id }
    })
  })
  return map
}
const POS = buildPositions()

function edgePath(a: Pos, b: Pos): string {
  const sx = a.cx + NODE_W / 2, sy = a.cy
  const tx = b.cx - NODE_W / 2, ty = b.cy
  const dx = (tx - sx) * 0.5
  return `M${sx},${sy} C${sx + dx},${sy} ${tx - dx},${ty} ${tx},${ty}`
}
function spinePath(a: Pos, b: Pos): string {
  const sx = a.cx, sy = a.cy + NODE_H / 2
  const ty = b.cy - NODE_H / 2
  return `M${sx},${sy} L${sx},${ty}`
}

export function CapabilityWeb() {
  const [hover, setHover] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const touches = (id: string, e: [string, string]) => e[0] === id || e[1] === id
  const active = open ? skillById(open) : undefined
  const activeTone = active ? (LANES.find((l) => l.ids.includes(active.id))?.tone || GROUP_TONE[active.group]) : ''

  return <section className="cp-web-wrap">
    <div className="cp-web-scroll">
      <svg className="cp-web" viewBox={`0 0 ${VW} ${VH}`} role="img" aria-label="Capability web: data to decision to execution to proof">
        {/* lane headers */}
        {LANES.map((lane, li) => (
          <g key={lane.key}>
            <text x={laneX(li)} y={32} textAnchor="middle" className="cp-web-lane-t" fill={lane.tone}>{lane.title}</text>
            <text x={laneX(li)} y={48} textAnchor="middle" className="cp-web-lane-s">{STAGE_TAG[lane.key]}</text>
          </g>
        ))}

        {/* spine within stages */}
        {SPINE.map(([a, b]) => {
          const pa = POS[a], pb = POS[b]
          if (!pa || !pb) return null
          const on = hover === a || hover === b
          return <path key={`sp-${a}-${b}`} d={spinePath(pa, pb)} className="cp-web-spine"
            stroke={pa.tone} style={{ opacity: hover && !on ? 0.12 : 0.4 }} />
        })}

        {/* cross stage flow edges */}
        {EDGES.map(([a, b]) => {
          const pa = POS[a], pb = POS[b]
          if (!pa || !pb) return null
          const on = !hover || touches(hover, [a, b])
          return <path key={`e-${a}-${b}`} d={edgePath(pa, pb)} className={`cp-web-edge ${on ? 'on' : ''}`}
            stroke={pa.tone} style={{ opacity: on ? 0.55 : 0.08 }} />
        })}

        {/* nodes */}
        {LANES.flatMap((lane) => lane.ids.map((id) => {
          const p = POS[id]; const sk = skillById(id)
          if (!p || !sk) return null
          const dim = hover && hover !== id && !EDGES.some((e) => touches(hover, e) && touches(id, e))
            && !SPINE.some((e) => touches(hover, e) && touches(id, e))
          return <g key={id} className="cp-web-node" transform={`translate(${p.x},${p.y})`}
            role="button" tabIndex={0} aria-label={`${sk.name} · open dossier`}
            onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(id)} onBlur={() => setHover(null)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(id) } }}
            onClick={() => setOpen(id)} style={{ opacity: dim ? 0.32 : 1 }}>
            <rect width={NODE_W} height={NODE_H} rx={10} className="cp-web-rect"
              style={{ stroke: hover === id ? p.tone : 'var(--c-line)' }} />
            <rect width={3.5} height={NODE_H} rx={2} fill={p.tone} opacity={sk.used ? 1 : 0.4} />
            <circle cx={NODE_W - 14} cy={13} r={3} fill={sk.used ? p.tone : 'var(--c-muted-2)'} />
            <text x={NODE_W / 2 + 4} y={NODE_H / 2 + 5} textAnchor="middle" className="cp-web-node-t">{LABEL[id] || sk.name}</text>
          </g>
        }))}
      </svg>
    </div>
    <div className="cp-web-legend">
      <span className="cp-web-leg"><span className="cp-web-leg-dot" style={{ background: 'var(--c-text-2)' }} /> {'Live capability'}</span>
      <span className="cp-web-leg"><span className="cp-web-leg-dot" style={{ background: 'var(--c-muted-2)' }} /> {'Available'}</span>
      <span className="cp-web-leg-note">{'Tap any node to open its dossier · follow one trade from CoinMarketCap data to BNB Chain proof.'}</span>
    </div>

    {active && <SkillModal s={active} tone={activeTone} onClose={() => setOpen(null)} onJump={(id) => setOpen(id)} />}
  </section>
}
