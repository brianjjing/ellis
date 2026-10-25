// C2 Case detail: Facts, Documents, Review, Activity, Memos, Transcript, Packet; case actions.
import { Fragment, useEffect, useState } from 'react'
import { api, ApiError, fmtTime } from '../api'
import type { Me } from './ClinicApp'

const TABS = ['Facts', 'Documents', 'Review', 'Activity', 'Memos', 'Transcript', 'Packet'] as const

export default function CaseDetail({ id, me, tick }: { id: string; me: Me; tick: number }) {
  const [d, setD] = useState<any>(null)
  const [tab, setTab] = useState<(typeof TABS)[number]>('Facts')
  const [msg, setMsg] = useState<string | null>(null)
  const [reveal, setReveal] = useState<Record<string, string>>({})
  const [reviewers, setReviewers] = useState<any[]>([])
  const load = () => api(`/api/clinic/cases/${id}`).then(setD).catch((e) => setMsg(e.message))
  useEffect(() => { load() }, [id, tick])
  useEffect(() => { api('/api/clinic/cases').then((r) => setReviewers(r.reviewers)) }, [])
  if (!d) return <p className="lead" style={{ padding: 24 }}>{msg ?? 'Loading…'}</p>
  const c = d.case
  const act = async (fn: () => Promise<any>, ok: string) => { setMsg(null); try { const r = await fn(); setMsg(typeof r === 'string' ? r : ok); load() } catch (e) { setMsg(e instanceof ApiError ? `${e.message}${e.details ? ': ' + e.details.map((f: any) => f.message).join('; ') : ''}` : 'failed') } }
  const doReveal = (field: string) => act(async () => { const r = await api(`/api/clinic/cases/${id}/reveal`, { body: { field } }); setReveal((x) => ({ ...x, [field]: r.value })); return 'Revealed (audit event written)' }, '')
  return (
    <>
      <header className="bar case-bar">
        <div className="stack" style={{ gap: 4 }}>
          <a href="/clinic" data-nav className="small">← Cases</a>
          <h1 className="h1">{c.full_name} <span className="pill">{c.stage}</span>{c.patient_mode && <span className="pill" title="Slower voice and longer pauses.">Extra support</span>}</h1>
          <span className="small">Reviewer: {c.assigned_reviewer?.name ?? '—'} · link {c.link_status.replace('_', ' ')} · last activity {fmtTime(c.last_activity)}</span>
        </div>
        <div className="case-actions">
          {(me.role === 'reviewer' || me.role === 'admin') && (
            <button className="btn primary" disabled={!d.gate.passes || !['review', 'evidence', 'intake'].includes(c.state)} onClick={() => act(() => api(`/api/clinic/cases/${id}/ready`, { body: {} }), 'Marked ready: the applicant sees the sign-off screen on next visit')}>
              Mark ready
            </button>
          )}
          <div className="case-secondary">
            <button className="btn sm" onClick={() => act(async () => `New link (old one revoked): ${(await api(`/api/clinic/cases/${id}/link`, { body: {} })).link}`, '')}>Resend link</button>
            <button className="btn sm" onClick={() => act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { patient_mode: !c.patient_mode } }), 'Saved')}>{c.patient_mode ? 'Extra support off' : 'Extra support on'}</button>
            <select className="input sm" value={c.assigned_reviewer?.id ?? ''} aria-label="Reassign reviewer" onChange={(e) => act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { assigned_reviewer: e.target.value } }), 'Reassigned')}>
              {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
            <details className="more-menu">
              <summary className="btn sm" aria-label="More actions">⋯</summary>
              <div className="more-menu-body">
                {d.clinic.is_demo && (
                  <button className="btn" title="Fills the remaining intake with seeded synthetic answers" onClick={() => act(() => api(`/api/clinic/cases/${id}/demo_autofill`, { body: {} }), 'Simulated answers written')}>Simulate intake (demo)</button>
                )}
                <button className="btn danger" onClick={() => confirm(`Close the case for ${c.full_name}?`) && act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { close: true } }), 'Closed')}>Close case</button>
              </div>
            </details>
          </div>
        </div>
      </header>
      {msg && <div className="panel" role="status" style={{ margin: '12px 24px' }}>{msg}</div>}
      <GatePanel d={d} id={id} onTabChange={setTab} />
      <div className="tabs" role="tablist" style={{ margin: '0 24px' }}>
        {TABS.map((t) => <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}{t === 'Review' && d.review_items.filter((r: any) => r.status === 'open').length ? ` (${d.review_items.filter((r: any) => r.status === 'open').length})` : ''}</button>)}
      </div>
      <div className="detail-body">
        {tab === 'Facts' && <Facts d={d} reveal={reveal} onReveal={doReveal} canReveal={me.role !== 'intake'} />}
        {tab === 'Documents' && <Docs d={d} id={id} reload={load} />}
        {tab === 'Review' && <ReviewItems d={d} id={id} reload={load} />}
        {tab === 'Activity' && <Activity d={d} />}
        {tab === 'Memos' && <Memos d={d} id={id} reload={load} />}
        {tab === 'Transcript' && <Transcript d={d} />}
        {tab === 'Packet' && <Packet d={d} id={id} />}
      </div>
    </>
  )
}

// b. Ready gate panel — grouped blockers with labels, links to fix location, collapsible field lists
function GatePanel({ d, id: _id, onTabChange }: { d: any; id: string; onTabChange: (t: any) => void }) {
  const [showFields, setShowFields] = useState<Record<string, boolean>>({})
  const gate = d.gate
  const CODE_META: Record<string, { label: string; tab?: string; fix?: string }> = {
    unconfirmed_fields: { label: 'Unconfirmed required fields', tab: 'Facts', fix: 'confirm or defer in the Facts tab' },
    blocking_review_items: { label: 'Blocking review items open', tab: 'Review', fix: 'decide in the Review tab' },
    qa_memo_missing: { label: 'QA memo not written', tab: 'Memos', fix: 'add a QA memo in the Memos tab' },
    qa_memo_stale: { label: 'QA memo is out of date', tab: 'Memos', fix: 'update the QA memo in the Memos tab' },
    derived_stale: { label: 'Rules engine needs a rerun', fix: 'happens automatically on next fact change' },
    rules_validation_error: { label: 'Rules engine validation error', tab: 'Facts' },
    document_extracting: { label: 'A document is still being read', tab: 'Documents', fix: 'wait for extraction to finish' },
  }
  return (
    <div className="panel gate" style={{ margin: '12px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <strong>Ready gate</strong>
        <span className={`status-chip ${gate.passes ? 'confirmed' : 'disputed'}`}>{gate.passes ? 'Passes' : 'Blocked'}</span>
      </div>
      {!gate.passes && (
        <div className="stack" style={{ gap: 6, marginTop: 8 }}>
          {gate.failing.map((f: any) => {
            const meta = CODE_META[f.code] ?? { label: f.message }
            const fields: string[] = f.fields ?? []
            const items: string[] = f.items ?? []
            const PREVIEW = 4
            const expanded = showFields[f.code]
            return (
              <div key={f.code} className="gate-blocker">
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{meta.label}</span>
                  {meta.tab && (
                    <button className="link-btn small-btn" onClick={() => onTabChange(meta.tab as any)}>→ {meta.tab}</button>
                  )}
                  {meta.fix && <span className="soft small">({meta.fix})</span>}
                </div>
                {fields.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <span className="small">{(expanded ? fields : fields.slice(0, PREVIEW)).map((k) => labelOf(d, k)).join(', ')}</span>
                    {fields.length > PREVIEW && (
                      <button className="link-btn small-btn" onClick={() => setShowFields({ ...showFields, [f.code]: !expanded })}>
                        {expanded ? 'show less' : `+${fields.length - PREVIEW} more`}
                      </button>
                    )}
                  </div>
                )}
                {items.length > 0 && <span className="small">{items.length} item{items.length > 1 ? 's' : ''}</span>}
              </div>
            )
          })}
        </div>
      )}
      {d.derived?.earliest_filing && (
        <span className="small soft" style={{ marginTop: 6 }}>
          Rules {d.derived.rule_config_version}: earliest filing {d.derived.earliest_filing}; presence {d.derived.presence_days ?? '—'} days{d.derived.civics_version ? `; civics ${d.derived.civics_version}` : ''}
        </span>
      )}
    </div>
  )
}

// Status badge labels for facts
const STATUS_LABELS: Record<string, string> = {
  confirmed: 'Confirmed', disputed: 'Disputed', proposed: 'Proposed',
  deferred: 'Deferred', superseded: 'Superseded',
}

// d. Facts tab — status badges, source links to documents
function Facts({ d, reveal, onReveal, canReveal }: { d: any; reveal: Record<string, string>; onReveal: (f: string) => void; canReveal: boolean }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (!d.facts.length) return <p className="soft" style={{ padding: '20px 0' }}>No facts recorded yet.</p>
  const docLink = (prov: string) => {
    const m = prov.match(/\(([a-z0-9_-]+)\)/)
    return m ? m[1] : null
  }
  return (
    <table className="table">
      <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Source</th></tr></thead>
      <tbody>
        {d.facts.map((f: any) => (
          <Fragment key={f.field}>
            <tr className={f.for_review ? 'amber' : ''}>
              <td>
                <span className="small soft">{f.section}</span><br />
                {f.label}{f.required ? '' : <span className="soft"> (opt)</span>}
                {f.for_review && <span className="pill amber">open flag</span>}
              </td>
              <td>
                <strong>{reveal[f.field] ?? f.current.value}</strong>
                {f.masked && canReveal && !reveal[f.field] && <button className="link-btn small-btn" onClick={() => onReveal(f.field)}>Reveal</button>}
                {f.current.hedge && <span className="pill">hedged</span>}
                {f.current.third_party && <span className="pill">third party</span>}
              </td>
              <td><span className={`status-chip ${f.current.status}`}>{STATUS_LABELS[f.current.status] ?? f.current.status}</span></td>
              <td className="small">
                {f.current.source === 'document' && docLink(f.current.provenance) ? (
                  <a href={`/api/clinic/documents/${docLink(f.current.provenance)}/file`} target="_blank" rel="noreferrer" className="link-btn">Document ↗</a>
                ) : f.current.provenance}
                {f.current.note ? ` · ${f.current.note}` : ''}
                {f.history.length > 0 && (
                  <button className="link-btn small-btn" onClick={() => setOpen({ ...open, [f.field]: !open[f.field] })}>
                    {open[f.field] ? 'hide' : `${f.history.length} earlier`}
                  </button>
                )}
              </td>
            </tr>
            {open[f.field] && f.history.map((h: any) => (
              <tr key={h.id} className="hist">
                <td></td>
                <td><s>{h.value}</s></td>
                <td><span className={`status-chip ${h.status}`}>{STATUS_LABELS[h.status] ?? h.status}</span></td>
                <td className="small">{h.provenance} · by {h.proposed_by}{h.note ? ` · ${h.note}` : ''}</td>
              </tr>
            ))}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

// e. Documents tab — expected-document checklist + uploaded files
const EXPECTED_DOCS = [
  { key: 'green_card', label: 'Green card (front and back)' },
  { key: 'passport', label: 'Passport' },
]

function Docs({ d, id, reload }: { d: any; id: string; reload: () => void }) {
  const [type, setType] = useState('green_card')
  const upload = async (f: File) => {
    const fd = new FormData(); fd.append('document_type', type); fd.append('file', f)
    await api(`/api/clinic/cases/${id}/documents`, { form: fd }); setTimeout(reload, 1500)
  }
  const uploadedTypes = new Set(d.documents.map((doc: any) => doc.document_type))
  const gapTypes = new Set(d.gaps.map((g: any) => g.document_type))
  // Build checklist: standard expected + any from open gaps
  const gapExtras = d.gaps.filter((g: any) => !EXPECTED_DOCS.some((e) => e.key === g.document_type))
  const checklist = [
    ...EXPECTED_DOCS,
    ...gapExtras.map((g: any) => ({ key: g.document_type, label: labelOf(d, g.document_type) })),
  ]
  const docStatus = (key: string) => {
    const uploaded = d.documents.filter((doc: any) => doc.document_type === key)
    if (!uploaded.length) return gapTypes.has(key) ? 'missing-flagged' : 'missing'
    if (uploaded.some((doc: any) => doc.quality === 'low')) return 'needs-attention'
    return 'received'
  }
  const statusLabel: Record<string, string> = {
    received: 'Received', 'missing': 'Missing', 'missing-flagged': 'Required', 'needs-attention': 'Needs attention',
  }
  const statusClass: Record<string, string> = {
    received: 'confirmed', 'missing': '', 'missing-flagged': 'disputed', 'needs-attention': 'disputed',
  }
  return (
    <div className="stack" style={{ gap: 20 }}>
      <section>
        <h3 className="h3 rule">Expected documents</h3>
        <div className="stack" style={{ gap: 8 }}>
          {checklist.length === 0 && <p className="soft">No expected documents defined.</p>}
          {checklist.map((e) => {
            const status = docStatus(e.key)
            const docs = d.documents.filter((doc: any) => doc.document_type === e.key)
            return (
              <div key={e.key} className="row" style={{ padding: '10px 0', alignItems: 'center', gap: 12 }}>
                <span style={{ flex: '1 1 200px', fontSize: 15, fontWeight: 600 }}>{e.label}</span>
                <span className={`status-chip ${statusClass[status]}`}>{statusLabel[status]}</span>
                {docs.length > 0 && (
                  <a href={`/api/clinic/documents/${docs[0].id}/file`} target="_blank" rel="noreferrer" className="small link-btn">View ↗</a>
                )}
              </div>
            )
          })}
        </div>
      </section>
      <section>
        <h3 className="h3 rule">Uploaded files</h3>
        <div className="btns" style={{ marginBottom: 12 }}>
          <select className="input sm" value={type} onChange={(e) => setType(e.target.value)} aria-label="Document type">
            {(d.document_types || []).map((t: { key: string; label: string }) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
          <label className="btn">Upload on applicant's behalf<input type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
        </div>
        {d.documents.length === 0 && <p className="soft">No files uploaded yet.</p>}
        {d.documents.map((doc: any) => (
          <div key={doc.id} className="doc-card">
            <a href={`/api/clinic/documents/${doc.id}/file`} target="_blank" rel="noreferrer"><img src={`/api/clinic/documents/${doc.id}/file`} alt={doc.document_type} className="thumb" onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} /></a>
            <div className="stack grow" style={{ gap: 6 }}>
              <strong>{doc.exhibit ? `Exhibit ${doc.exhibit} · ` : ''}{doc.document_label || labelOf(d, doc.document_type)}</strong>
              <span className="small">{doc.filename} · {doc.status}{doc.quality === 'low' ? ' · ⚠ unclear photo' : ''} · uploaded by {doc.uploaded_by} {fmtTime(doc.ts)}</span>
              {doc.extraction && <table className="table mini"><tbody>{Object.entries(doc.extraction).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => <tr key={k}><td>{labelOf(d, k)}</td><td>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td></tr>)}</tbody></table>}
            </div>
          </div>
        ))}
        {d.gaps.length > 0 && (
          <>
            <h4 className="h3 rule" style={{ marginTop: 12 }}>Document gaps</h4>
            {d.gaps.map((g: any) => (
              <div key={g.id} className="row" style={{ padding: '8px 0', gap: 8 }}>
                <span className="grow small">{g.reason}</span>
                <span className={`status-chip ${uploadedTypes.has(g.document_type) ? 'confirmed' : ''}`}>{g.status}</span>
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  )
}

// f. Review tab — severity badge, plain description, linked sources, next step
const SEVERITY_META: Record<string, { label: string; cls: string }> = {
  stop_now: { label: 'Stop now', cls: 'disputed' },
  blocking: { label: 'Blocking', cls: 'disputed' },
  normal: { label: 'Review', cls: 'proposed' },
  informational: { label: 'Info', cls: '' },
}
const NEXT_STEP: Record<string, string> = {
  stop_now: 'Resolve before any further intake.',
  blocking: 'Decide or request more info before marking ready.',
  normal: 'Review and close when satisfied.',
  informational: 'No action required; close when noted.',
}

function ReviewItems({ d, id, reload }: { d: any; id: string; reload: () => void }) {
  const [active, setActive] = useState<{ itemId: string; action: 'resolve' | 'question' | 'memo' } | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const openItems = d.review_items.filter((r: any) => r.status === 'open' || r.status === 'case_blocked')
  const closed = d.review_items.filter((r: any) => r.status !== 'open' && r.status !== 'case_blocked')

  const commit = async () => {
    if (!active || !note.trim()) return
    setBusy(true)
    setErr(null)
    try {
      if (active.action === 'resolve') {
        await api(`/api/clinic/review/${active.itemId}/decision`, { body: { decision: 'clear', note } })
      } else if (active.action === 'question') {
        await api(`/api/clinic/review/${active.itemId}/decision`, { body: { decision: 'needs_more_info', note } })
      } else {
        await api(`/api/clinic/cases/${id}/notes`, { body: { body: note } })
      }
      setActive(null)
      setNote('')
      reload()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'failed')
    } finally {
      setBusy(false)
    }
  }

  const renderItem = (r: any, isOpenItem: boolean) => {
    const speed = r.speed === 'stop_now' ? 'stop_now' : r.blocking ? 'blocking' : r.speed ?? 'normal'
    const meta = SEVERITY_META[speed] ?? SEVERITY_META.normal
    const isActive = active?.itemId === r.id
    return (
      <div key={r.id} className={`panel ${r.speed === 'stop_now' ? 'warn' : ''}`} style={{ flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className={`status-chip ${meta.cls}`}>{meta.label}</span>
          <span className="label">{r.category.replace(/_/g, ' ')}</span>
          <span className="soft small">{r.status}{r.blocking ? ' · blocking' : ''}</span>
          <span className="soft small" style={{ marginLeft: 'auto' }}>{fmtTime(r.ts)}</span>
        </div>
        <p style={{ margin: 0, fontSize: 15 }}>{r.speed === 'stop_now' ? r.banner : r.facts ?? labelOf(d, r.field ?? '')}</p>
        {r.evidence?.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {r.evidence.map((ev: any) => (
              <a key={ev.id} href={`/api/clinic/documents/${ev.id}/file`} target="_blank" rel="noreferrer" className="pill" style={{ textDecoration: 'none' }}>
                {ev.document_type.replace(/_/g, ' ')} ↗
              </a>
            ))}
          </div>
        )}
        {r.agent_notes?.length > 0 && (
          <div className="stack" style={{ gap: 4 }}>
            {r.agent_notes.map((n: any, i: number) => (
              <p key={i} className="small soft" style={{ margin: 0 }}>{n.note} — {n.by.split('@')[0].replace(/_/g, ' ')}</p>
            ))}
          </div>
        )}
        {isOpenItem && !r.decision && (
          <>
            <p className="small" style={{ margin: 0, fontWeight: 700 }}>Next step: {NEXT_STEP[speed] ?? NEXT_STEP.normal}</p>
            {isActive && active ? (
              <div className="stack" style={{ gap: 8, marginTop: 4 }}>
                <label className="small soft" htmlFor={`note-${r.id}`}>
                  {active.action === 'resolve' ? 'Resolution note (required)' : active.action === 'question' ? 'Question to send to client (required)' : 'Internal memo (required)'}
                </label>
                <textarea id={`note-${r.id}`} className="input area" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="btns">
                  <button className="btn sm primary" disabled={!note.trim() || busy} onClick={commit}>
                    {active.action === 'resolve' ? 'Confirm resolve' : active.action === 'question' ? 'Send question' : 'Add memo'}
                  </button>
                  <button className="btn sm" onClick={() => { setActive(null); setNote('') }}>Cancel</button>
                </div>
                {err && <p className="rust small" style={{ margin: 0 }}>{err}</p>}
              </div>
            ) : (
              <div className="btns" style={{ marginTop: 4 }}>
                <button className="btn sm" onClick={() => { setActive({ itemId: r.id, action: 'resolve' }); setNote('') }}>Resolve</button>
                <button className="btn sm" onClick={() => { setActive({ itemId: r.id, action: 'question' }); setNote('') }}>Send to client as a question</button>
                <button className="btn sm" onClick={() => { setActive({ itemId: r.id, action: 'memo' }); setNote('') }}>Write memo</button>
              </div>
            )}
          </>
        )}
        {r.decision && <p className="small soft" style={{ margin: 0 }}>Decision: {r.decision} — {r.decision_note}</p>}
      </div>
    )
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      <a className="btn md" href="/clinic/review" data-nav style={{ alignSelf: 'flex-start' }}>Open review queue</a>
      {openItems.length === 0 && <p className="soft">No open review items.</p>}
      {openItems.map((r: any) => renderItem(r, true))}
      {closed.length > 0 && (
        <details>
          <summary className="small link-btn">{closed.length} closed item{closed.length > 1 ? 's' : ''}</summary>
          <div className="stack" style={{ gap: 10, marginTop: 8 }}>{closed.map((r: any) => renderItem(r, false))}</div>
        </details>
      )}
    </div>
  )
}

// c. Activity tab — actor filter, links to related fact/doc/review/memo
const ACTOR_LABELS: Record<string, string> = {
  applicant: 'Client', staff: 'Staff', agent: 'AI staff', system: 'System',
}

function Activity({ d }: { d: any }) {
  const [actorFilter, setActorFilter] = useState<string>('all')
  const events = d.events as any[]
  const actorTypes = ['all', ...Array.from(new Set(events.map((e) => e.actor_type || 'system')))]
  const visible = actorFilter === 'all' ? events : events.filter((e) => (e.actor_type || 'system') === actorFilter)

  const eventLink = (e: any) => {
    const p = e.payload ?? {}
    if (p.document_id) return { href: `/api/clinic/documents/${p.document_id}/file`, label: 'View document ↗', external: true }
    if (e.kind?.startsWith('fact.') && p.field) return { href: `#facts-${p.field}`, label: 'View field', external: false }
    return null
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="btns">
        <label className="small" htmlFor="actor-filter" style={{ fontWeight: 700 }}>Filter:</label>
        <select id="actor-filter" className="input sm" value={actorFilter} onChange={(e) => setActorFilter(e.target.value)}>
          {actorTypes.map((t) => <option key={t} value={t}>{t === 'all' ? 'All actors' : ACTOR_LABELS[t] ?? t}</option>)}
        </select>
      </div>
      {visible.length === 0 && <p className="soft">No activity{actorFilter !== 'all' ? ` for ${ACTOR_LABELS[actorFilter] ?? actorFilter}` : ''} yet.</p>}
      {visible.map((e: any) => {
        const link = eventLink(e)
        return (
          <article key={e.id} className="panel" style={{ flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
              <span className="label">{ACTOR_LABELS[e.actor_type ?? 'system'] ?? e.actor_type}</span>
              <span className="soft small">{fmtTime(e.ts)}</span>
              {link && (
                link.external
                  ? <a href={link.href} target="_blank" rel="noreferrer" className="small link-btn">{link.label}</a>
                  : <a href={link.href} className="small link-btn">{link.label}</a>
              )}
            </div>
            <p style={{ margin: 0, fontSize: 15 }}>{e.sentence}</p>
          </article>
        )
      })}
    </div>
  )
}

function labelOf(d: any, key: string) {
  if (!key) return ''
  if (d.labels?.[key]) return d.labels[key]
  const base = key.split('.').pop()!.replace(/[\[\]]/g, ' ').replace(/_/g, ' ')
  return base.replace(/\b\w/g, (c) => c.toUpperCase())
}

function Briefing({ d }: { d: any }) {
  const [raw, setRaw] = useState(false)
  const b = d.briefing
  if (!b) return <p className="soft">No briefing yet.</p>
  const queue = b.queue || []
  return (
    <div className="stack" style={{ gap: 10 }}>
      {queue.length === 0 ? <p className="soft">Nothing queued.</p> : (
        <ol>
          {queue.map((q: any, i: number) => (
            <li key={i}>
              <strong>{labelOf(d, q.field || q.document_type || q.section || q.kind)}</strong>
              {q.reason ? ` — ${q.reason}` : ''}
            </li>
          ))}
        </ol>
      )}
      <p>Flags the client can see: {(b.applicant_visible_flags || []).join(', ') || 'none'}.</p>
      <p>Topics Ellis must not mention: {(b.do_not_mention || []).join(', ') || 'none'}.</p>
      {b.tone_hint && <p>Tone: {b.tone_hint}</p>}
      <button type="button" className="btn" onClick={() => setRaw(!raw)}>{raw ? 'Hide raw data' : 'Show raw data'}</button>
      {raw && <pre className="memo">{JSON.stringify(b, null, 1)}</pre>}
    </div>
  )
}

// g. Memos — task cards per agent, formatted QA/status memos
function Memos({ d, id, reload }: { d: any; id: string; reload: () => void }) {
  const [note, setNote] = useState('')
  const tasks = d.tasks as any[]
  // Group tasks by agent
  const agentGroups: Record<string, any[]> = {}
  for (const t of tasks) {
    const key = t.agent_label || t.agent
    agentGroups[key] = agentGroups[key] ?? []
    agentGroups[key].push(t)
  }
  return (
    <div className="stack" style={{ gap: 20 }}>
      <section>
        <h3 className="h3 rule">AI staff task board</h3>
        {tasks.length === 0 && <p className="soft">No tasks yet.</p>}
        {Object.entries(agentGroups).map(([agent, agentTasks]) => (
          <div key={agent} className="agent-card">
            <div className="agent-card-head">
              <span style={{ fontWeight: 700 }}>{agent}</span>
              <span className="soft small">{agentTasks.length} task{agentTasks.length > 1 ? 's' : ''}</span>
            </div>
            <div className="stack" style={{ gap: 4 }}>
              {agentTasks.map((t: any) => (
                <div key={t.id} className="row" style={{ padding: '4px 0', gap: 8 }}>
                  <span className="grow small">{t.title}</span>
                  <span className={`status-chip ${t.status === 'done' ? 'confirmed' : t.status === 'failed' ? 'disputed' : 'proposed'}`}>{t.status ?? t.kind}</span>
                  <span className="soft small">{fmtTime(t.ts)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>
      {(['qa', 'status', 'note'] as const).map((k) => {
        const ms = d.memos.filter((m: any) => m.kind === k)
        const heading = k === 'qa' ? 'QA memo' : k === 'status' ? 'Status memo' : 'Internal notes'
        return (
          <section key={k}>
            <h3 className="h3 rule">{heading}</h3>
            {ms.length === 0 ? (
              <p className="soft">None yet.</p>
            ) : (
              <div className="stack" style={{ gap: 6 }}>
                <pre className="memo">{ms[0].body_md}</pre>
                <span className="small soft">{fmtTime(ms[0].ts)} · {ms[0].proposed_by}{ms.length > 1 ? ` · ${ms.length - 1} earlier version${ms.length > 2 ? 's' : ''}` : ''}</span>
              </div>
            )}
          </section>
        )
      })}
      <section>
        <h3 className="h3 rule">Add a note</h3>
        <div className="btns">
          <input className="input grow" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an internal note" />
          <button className="btn md" onClick={async () => { await api(`/api/clinic/cases/${id}/notes`, { body: { body: note } }); setNote(''); reload() }} disabled={!note}>Add note</button>
        </div>
      </section>
      <section>
        <h3 className="h3 rule">What Ellis will ask next</h3>
        <Briefing d={d} />
      </section>
    </div>
  )
}

function Transcript({ d }: { d: any }) {
  if (!d.transcript) return <p className="soft">Transcripts are off for this clinic (retention setting).</p>
  if (!d.transcript.length) return <p className="soft">No conversation yet.</p>
  return (
    <div className="stack" style={{ gap: 6 }}>
      {d.transcript.map((u: any) => (
        <div key={u.id} className={`cap ${u.speaker === 'liaison' ? 'ellis' : 'usted'}`}>
          <span className="label">{u.speaker === 'liaison' ? 'Ellis' : 'Applicant'} · {fmtTime(u.ts)}{u.locked ? ' · locked' : ''}{u.redacted ? ' · redacted' : ''}</span>
          <p>{u.text.startsWith('[STOP:') ? '[STOP]' : u.text}</p>
        </div>
      ))}
    </div>
  )
}

function Packet({ d, id }: { d: any; id: string }) {
  const open = async (pid: string) => { const r = await api(`/api/clinic/cases/${id}/packet/${pid}`); window.open(r.url, '_blank') }
  if (!d.packets.length) return <p className="soft">The packet is built when the applicant signs.</p>
  return (
    <table className="table">
      <thead><tr><th>File</th><th>Status</th><th>sha256</th><th>Built</th></tr></thead>
      <tbody>{d.packets.map((p: any) => <tr key={p.id}><td><button className="link-btn" onClick={() => open(p.id)}>{p.filename}</button></td><td>{p.status}</td><td className="small mono-s">{p.sha256.slice(0, 16)}…</td><td className="small">{fmtTime(p.ts)}</td></tr>)}</tbody>
    </table>
  )
}
