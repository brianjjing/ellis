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
      <header className="bar">
        <div className="stack" style={{ gap: 4 }}>
          <a href="/clinic" data-nav className="small">← Cases</a>
          <h1 className="h1">{c.full_name} <span className="pill">{c.stage}</span>{c.patient_mode && <span className="pill">patient mode</span>}</h1>
          <span className="small">Reviewer: {c.assigned_reviewer?.name ?? '—'} · link {c.link_status.replace('_', ' ')} · last activity {fmtTime(c.last_activity)}</span>
        </div>
        <div className="btns">
          <button className="btn" onClick={() => act(async () => `New link (old one revoked): ${(await api(`/api/clinic/cases/${id}/link`, { body: {} })).link}`, '')}>Resend link</button>
          <button className="btn" onClick={() => act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { patient_mode: !c.patient_mode } }), 'Saved')}>{c.patient_mode ? 'Patient mode off' : 'Patient mode on'}</button>
          <select className="input sm" value={c.assigned_reviewer?.id ?? ''} aria-label="Reassign reviewer" onChange={(e) => act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { assigned_reviewer: e.target.value } }), 'Reassigned')}>
            {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          {d.clinic.is_demo && <button className="btn" title="Fills the remaining intake with the seeded synthetic answers, labeled simulated" onClick={() => act(() => api(`/api/clinic/cases/${id}/demo_autofill`, { body: {} }), 'Simulated answers written')}>Simulate remaining intake (demo)</button>}
          {(me.role === 'reviewer' || me.role === 'admin') && <button className="btn primary" disabled={!d.gate.passes || !['review', 'evidence', 'intake'].includes(c.state)} onClick={() => act(() => api(`/api/clinic/cases/${id}/ready`, { body: {} }), 'Marked ready: the applicant sees the sign-off screen on next visit')}>Mark ready</button>}
          <button className="btn danger" onClick={() => confirm('Close this case?') && act(() => api(`/api/clinic/cases/${id}`, { method: 'PATCH', body: { close: true } }), 'Closed')}>Close case</button>
        </div>
      </header>
      {msg && <div className="panel" role="status" style={{ margin: '12px 24px' }}>{msg}</div>}
      <div className="panel gate" style={{ margin: '12px 24px' }}>
        <strong>Ready gate: {d.gate.passes ? 'passes' : 'blocked'}</strong>
        {!d.gate.passes && <ul className="small">{d.gate.failing.map((f: any) => <li key={f.code}>{f.message}{f.fields ? ` (${f.fields.slice(0, 6).join(', ')}${f.fields.length > 6 ? '…' : ''})` : ''}</li>)}</ul>}
        {d.derived?.earliest_filing && <span className="small">Rules engine ({d.derived.rule_config_version}): earliest filing {d.derived.earliest_filing}; presence {d.derived.presence_days ?? '—'} days{d.derived.civics_version ? `; civics ${d.derived.civics_version}` : ''}</span>}
      </div>
      <div className="tabs" role="tablist" style={{ margin: '0 24px' }}>
        {TABS.map((t) => <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}{t === 'Review' && d.review_items.filter((r: any) => r.status === 'open').length ? ` (${d.review_items.filter((r: any) => r.status === 'open').length})` : ''}</button>)}
      </div>
      <div className="detail-body">
        {tab === 'Facts' && <Facts d={d} reveal={reveal} onReveal={doReveal} canReveal={me.role !== 'intake'} />}
        {tab === 'Documents' && <Docs d={d} id={id} reload={load} />}
        {tab === 'Review' && <ReviewItems d={d} />}
        {tab === 'Activity' && <Activity d={d} />}
        {tab === 'Memos' && <Memos d={d} id={id} reload={load} />}
        {tab === 'Transcript' && <Transcript d={d} />}
        {tab === 'Packet' && <Packet d={d} id={id} />}
      </div>
    </>
  )
}

function Facts({ d, reveal, onReveal, canReveal }: { d: any; reveal: Record<string, string>; onReveal: (f: string) => void; canReveal: boolean }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  return (
    <table className="table">
      <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Source / provenance</th></tr></thead>
      <tbody>
        {d.facts.map((f: any) => (
          <Fragment key={f.field}>
            <tr className={f.for_review ? 'amber' : ''}>
              <td><span className="small soft">{f.section}</span><br />{f.label}{f.required ? '' : <span className="soft"> (optional)</span>}</td>
              <td><strong>{reveal[f.field] ?? f.current.value}</strong>{f.masked && canReveal && !reveal[f.field] && <button className="link-btn small-btn" onClick={() => onReveal(f.field)}>Reveal</button>}
                {f.current.hedge && <span className="pill">hedged</span>}{f.current.third_party && <span className="pill">third party</span>}{f.for_review && <span className="pill amber">for review</span>}</td>
              <td><span className={`status-chip ${f.current.status}`}>{f.current.status}</span></td>
              <td className="small">{f.current.provenance}{f.current.note ? ` · ${f.current.note}` : ''}
                {f.history.length > 0 && <button className="link-btn small-btn" onClick={() => setOpen({ ...open, [f.field]: !open[f.field] })}>{open[f.field] ? 'hide' : `${f.history.length} earlier`}</button>}</td>
            </tr>
            {open[f.field] && f.history.map((h: any) => (
              <tr key={h.id} className="hist"><td></td><td><s>{h.value}</s></td><td className="small">{h.status}</td><td className="small">{h.provenance} · by {h.proposed_by}{h.note ? ` · ${h.note}` : ''}</td></tr>
            ))}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

function Docs({ d, id, reload }: { d: any; id: string; reload: () => void }) {
  const [type, setType] = useState('green_card')
  const upload = async (f: File) => {
    const fd = new FormData(); fd.append('document_type', type); fd.append('file', f)
    await api(`/api/clinic/cases/${id}/documents`, { form: fd }); setTimeout(reload, 1500)
  }
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="btns">
        <select className="input sm" value={type} onChange={(e) => setType(e.target.value)}>
          {['green_card', 'passport', 'marriage_certificate', 'lease', 'court_record', 'tax_transcript', 'benefit_letter', 'other'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <label className="btn">Upload on applicant's behalf<input type="file" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
      </div>
      {d.documents.map((doc: any) => (
        <div key={doc.id} className="doc-card">
          <a href={`/api/clinic/documents/${doc.id}/file`} target="_blank" rel="noreferrer"><img src={`/api/clinic/documents/${doc.id}/file`} alt={doc.document_type} className="thumb" onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} /></a>
          <div className="stack grow" style={{ gap: 6 }}>
            <strong>{doc.exhibit ? `Exhibit ${doc.exhibit} · ` : ''}{doc.document_type.replace(/_/g, ' ')}</strong>
            <span className="small">{doc.filename} · {doc.status} · quality {doc.quality ?? '—'} · {doc.extractor ?? ''} · uploaded by {doc.uploaded_by} {fmtTime(doc.ts)}</span>
            {doc.extraction && <table className="table mini"><tbody>{Object.entries(doc.extraction).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => <tr key={k}><td>{k}</td><td>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td></tr>)}</tbody></table>}
            {doc.checks && <span className="small">Checks: {Object.entries(doc.checks).filter(([k]) => !['applied_fields', 'supports', 'quality_reasons'].includes(k)).map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}{doc.checks.supports?.length ? ` · supports ${doc.checks.supports.join(', ')}` : ''}</span>}
          </div>
        </div>
      ))}
      <h3 className="h3">Gap list (document checker)</h3>
      {d.gaps.length === 0 ? <p className="soft">No gaps.</p> : d.gaps.map((g: any) => <div key={g.id} className="row" style={{ padding: '8px 0' }}><span className="grow">{g.reason}</span><span className="pill">{g.status}</span></div>)}
    </div>
  )
}

function ReviewItems({ d }: { d: any }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <a className="btn md" href="/clinic/review" data-nav style={{ alignSelf: 'flex-start' }}>Open the review queue</a>
      {d.review_items.map((r: any) => (
        <div key={r.id} className={`panel ${r.speed === 'stop_now' ? 'warn' : ''}`}>
          <div className="stack grow" style={{ gap: 4 }}>
            <span className="label">{r.speed === 'stop_now' ? `STOP-NOW · ${r.category}` : `${r.category} · ${r.speed}`} · {r.status}{r.blocking ? ' · blocking' : ''}</span>
            <span>{r.speed === 'stop_now' ? r.banner : r.facts ?? r.field}</span>
            {r.decision && <span className="small">Decision: {r.decision} — {r.decision_note}</span>}
          </div>
          <span className="small">{fmtTime(r.ts)}</span>
        </div>
      ))}
    </div>
  )
}

function Activity({ d }: { d: any }) {
  const [actor, setActor] = useState('')
  const actors = Array.from(new Set(d.events.map((e: any) => e.actor_type)))
  return (
    <div className="stack" style={{ gap: 8 }}>
      <select className="input sm" value={actor} onChange={(e) => setActor(e.target.value)} style={{ alignSelf: 'flex-start' }}>
        <option value="">All actors</option>{actors.map((a: any) => <option key={a}>{a}</option>)}
      </select>
      <table className="table">
        <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Payload</th></tr></thead>
        <tbody>{d.events.filter((e: any) => !actor || e.actor_type === actor).map((e: any) => (
          <tr key={e.id}><td className="small">{fmtTime(e.ts)}</td><td><strong>{e.kind}</strong></td><td className="small">{e.actor_type} · {e.actor}</td><td className="small mono-s">{JSON.stringify(e.payload)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function Memos({ d, id, reload }: { d: any; id: string; reload: () => void }) {
  const [note, setNote] = useState('')
  const tasks = d.tasks
  return (
    <div className="stack" style={{ gap: 16 }}>
      {['qa', 'status', 'note'].map((k) => {
        const ms = d.memos.filter((m: any) => m.kind === k)
        return (
          <section key={k}>
            <h3 className="h3 rule">{k === 'qa' ? 'QA memo (quality check)' : k === 'status' ? 'Status memo (case coordinator)' : 'Internal notes'}</h3>
            {ms.length === 0 ? <p className="soft">None yet.</p> : <><pre className="memo">{ms[0].body_md}</pre><span className="small">{fmtTime(ms[0].ts)} · {ms[0].proposed_by}{ms.length > 1 ? ` · ${ms.length - 1} earlier versions` : ''}</span></>}
          </section>
        )
      })}
      <div className="btns"><input className="input grow" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an internal note" /><button className="btn md" onClick={async () => { await api(`/api/clinic/cases/${id}/notes`, { body: { body: note } }); setNote(''); reload() }} disabled={!note}>Add note</button></div>
      <section>
        <h3 className="h3 rule">Task board (AI staff)</h3>
        {tasks.map((t: any) => <div key={t.id} className="row" style={{ padding: '8px 0' }}><span className="label green" style={{ minWidth: 140 }}>{t.agent_label}</span><span className="grow">{t.title}</span><span className="pill">{t.kind}</span><span className="small">{fmtTime(t.ts)}</span></div>)}
      </section>
      <section>
        <h3 className="h3 rule">Latest briefing (liaison queue)</h3>
        <pre className="memo">{JSON.stringify(d.briefing, null, 1)}</pre>
      </section>
    </div>
  )
}

function Transcript({ d }: { d: any }) {
  if (!d.transcript) return <p className="soft">Transcripts are off for this clinic (retention setting).</p>
  return (
    <div className="stack" style={{ gap: 6 }}>
      {d.transcript.map((u: any) => (
        <div key={u.id} className={`cap ${u.speaker === 'liaison' ? 'ellis' : 'usted'}`}>
          <span className="label">{u.speaker === 'liaison' ? 'ELLIS' : 'APPLICANT'} · {fmtTime(u.ts)}{u.locked ? ' · locked' : ''}{u.redacted ? ' · redacted' : ''}</span>
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
