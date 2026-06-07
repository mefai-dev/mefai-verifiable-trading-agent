/* BNB HACK · the skill catalog UI.
   One always-open dossier per sponsor capability, plus a filter and search bar.
   Every skill renders its live capability inline under its own title (no click
   to open). Used by the three "Built with" pages (CMC, Trust, BNB) to surface
   every skill. The catalog is data driven from skills.ts, so a new capability is
   one record. SkillModal is retained for the capability-web entry point. */

import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Reveal, LazyMount, Portal } from '../ui'
import { IconClose, IconExternal, IconCheck } from '../icons'
import type { SkillDef, SkillGroup } from '../skills'
import { skillsByGroup, skillById, groupCounts, KIND_LABEL } from '../skills'
import { SKILL_DEMO } from './skillDemos'

function UsedDot({ used, tone }: { used: boolean; tone: string }) {
  return <span className="cp-sk-status" style={{ color: used ? tone : 'var(--c-muted)' }}>
    <span className="cp-sk-dot" style={{ background: used ? tone : 'var(--c-muted-2)' }} />
    {used ? 'Live' : 'Available'}
  </span>
}

/* the dossier body: live capability first, then how MEFAI uses it, the IO
   shape, the invoke line and what it connects to. Shared by the always-open
   catalog card and the capability-web modal. `lazy` defers the live panel
   until it scrolls near the viewport (catalog only). */
function SkillBody({ s, tone, onJump, lazy }: {
  s: SkillDef; tone: string; onJump: (id: string) => void; lazy?: boolean
}) {
  const related = s.related.map(skillById).filter(Boolean) as SkillDef[]
  const demo = SKILL_DEMO[s.id]
  return <>
    {demo && <div className="cp-sk-block">
      <div className="cp-sk-block-h">Live capability</div>
      {lazy ? <LazyMount minHeight={120}>{demo(s)}</LazyMount> : demo(s)}
    </div>}

    <div className="cp-sk-block">
      <div className="cp-sk-block-h">How MEFAI uses it</div>
      <p className="cp-sk-block-b">{s.what}</p>
    </div>

    {(s.inputs || s.outputs) && <div className="cp-sk-io">
      {s.inputs && <Field label="Inputs" v={s.inputs} />}
      {s.outputs && <Field label="Outputs" v={s.outputs} />}
    </div>}

    {s.invoke && <div className="cp-sk-block">
      <div className="cp-sk-block-h">Invoke</div>
      <code className="cp-sk-invoke mono">{s.invoke}</code>
    </div>}

    {related.length > 0 && <div className="cp-sk-block">
      <div className="cp-sk-block-h">Connected to</div>
      <div className="cp-sk-rel">
        {related.map((r) => <button key={r.id} className="cp-sk-rel-pill" onClick={() => onJump(r.id)}>
          <span className="cp-sk-rel-dot" style={{ background: r.used ? tone : 'var(--c-muted-2)' }} />
          {r.name}
        </button>)}
      </div>
    </div>}

    {s.link && <a className="cp-sk-link" href={s.link} target="_blank" rel="noopener noreferrer">
      Open the source <IconExternal size={13} />
    </a>}
  </>
}

/* one always-open skill: the capability sits under its own title, no click. */
function SkillDossier({ s, tone, onJump }: { s: SkillDef; tone: string; onJump: (id: string) => void }) {
  return <article id={`cp-sk-${s.id}`} className="cp-sk-open" style={{ ['--sk-tone' as string]: tone }}>
    <div className="cp-sk-modal-head">
      <span className="cp-sk-kind" style={{ color: tone }}>{KIND_LABEL[s.kind]}</span>
      <UsedDot used={s.used} tone={tone} />
    </div>
    <h3 className="cp-sk-modal-name mono">{s.name}</h3>
    <p className="cp-sk-modal-sum">{s.summary}</p>
    <SkillBody s={s} tone={tone} onJump={onJump} lazy />
  </article>
}

export function SkillModal({ s, tone, onClose, onJump }: {
  s: SkillDef; tone: string; onClose: () => void; onJump: (id: string) => void
}) {
  return <Portal>
    <div className="cp-modal-overlay" onClick={onClose}>
      <div className="cp-modal" onClick={(e) => e.stopPropagation()} style={{ ['--sk-tone' as string]: tone }}>
        <button className="cp-modal-x" onClick={onClose} aria-label="close"><IconClose size={18} /></button>
        <div className="cp-sk-modal-head">
          <span className="cp-sk-kind" style={{ color: tone }}>{KIND_LABEL[s.kind]}</span>
          <UsedDot used={s.used} tone={tone} />
        </div>
        <h3 className="cp-sk-modal-name mono">{s.name}</h3>
        <p className="cp-sk-modal-sum">{s.summary}</p>
        <SkillBody s={s} tone={tone} onJump={onJump} />
      </div>
    </div>
  </Portal>
}

function Field({ label, v }: { label: string; v: string }) {
  return <div className="cp-sk-field">
    <span className="cp-sk-field-l">{label}</span>
    <span className="cp-sk-field-v">{v}</span>
  </div>
}

export function SkillCatalog({ group, tone, intro }: { group: SkillGroup; tone: string; intro?: ReactNode }) {
  const all = useMemo(() => skillsByGroup(group), [group])
  const counts = useMemo(() => groupCounts(group), [group])
  const kinds = useMemo(() => Array.from(new Set(all.map((s) => s.kind))), [all])

  const [q, setQ] = useState('')
  const [kind, setKind] = useState<string>('all')
  const [usedOnly, setUsedOnly] = useState(false)

  /* a "Connected to" pill may point at a capability the current filter hides.
     Clear the filters first so the target is in the list, then scroll to it on
     the next frame once it has rendered. Cross-group targets simply no-op. */
  const jump = useCallback((id: string) => {
    if (!all.some((s) => s.id === id)) return
    setKind('all'); setUsedOnly(false); setQ('')
    /* the target may be filtered out at click time; the state reset above
       mounts it, but the commit + lazy placeholder can take a few frames. Poll
       briefly for the node rather than relying on a single frame. */
    let tries = 0
    const seek = () => {
      const el = document.getElementById(`cp-sk-${id}`)
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); return }
      if (tries++ < 20) requestAnimationFrame(seek)
    }
    requestAnimationFrame(seek)
  }, [all])

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return all.filter((s) => {
      if (kind !== 'all' && s.kind !== kind) return false
      if (usedOnly && !s.used) return false
      if (!needle) return true
      return (s.name + ' ' + s.summary + ' ' + s.what + ' ' + s.tags.join(' ')).toLowerCase().includes(needle)
    })
  }, [all, q, kind, usedOnly])

  return <section className="cp-sk-catalog" style={{ ['--sk-tone' as string]: tone }}>
    {intro}
    <div className="cp-sk-bar">
      <input className="cp-sk-search mono" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={`Search ${counts.total} capabilities`} spellCheck={false} />
      <div className="cp-sk-filters">
        <button className={`cp-sk-f ${kind === 'all' ? 'on' : ''}`} aria-pressed={kind === 'all'} onClick={() => setKind('all')}>All</button>
        {kinds.map((k) => (
          <button key={k} className={`cp-sk-f ${kind === k ? 'on' : ''}`} aria-pressed={kind === k} onClick={() => setKind(k)}>{KIND_LABEL[k]}</button>
        ))}
        <button className={`cp-sk-f ${usedOnly ? 'on' : ''}`} aria-pressed={usedOnly} onClick={() => setUsedOnly((v) => !v)}>
          {usedOnly && <IconCheck size={12} strokeWidth={2.6} />} Live only
        </button>
      </div>
    </div>

    <div className="cp-sk-meta">
      Showing <b>{rows.length}</b> of {counts.total} · <b>{counts.used}</b> wired into the live agent · every capability runs open below
    </div>

    <div className="cp-sk-list">
      {rows.map((s, i) => (
        <Reveal key={s.id} delay={Math.min(i, 6) * 40}>
          <SkillDossier s={s} tone={tone} onJump={jump} />
        </Reveal>
      ))}
      {rows.length === 0 && <div className="cp-sk-empty">No capability matches that filter.</div>}
    </div>
  </section>
}
