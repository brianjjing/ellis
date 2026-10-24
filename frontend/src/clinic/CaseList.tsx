// C1 Case list + New case.
import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from './ClinicApp'

export default function CaseList({ me, tick }: { me: Me; tick: number }) {
  const [rows, setRows] = useState<any[]>([])
  const [reviewers, setReviewers] = useState<any[]>([])
  const [f, setF] = useState({ stage: '', stop_now: false, mine: false, inactive: false })
  const [creating, setCreating] = useState(false)
  useEffect(() => {
    const q = new URLSearchParams()
    if (f.stage) q.set('stage', f.stage)
    if (f.stop_now) q.set('stop_now', 'true')
    if (f.mine) q.set('mine', 'true')
    if (f.inactive) q.set('inactive', 'true')
    api(`/api/clinic/cases?${q}`).then((r) => { setRows(r.cases); setReviewers(r.reviewers) })
  }, [tick, f])
  return (
    <>
      <header className="bar">
        <h1 className="h1">Cases</h1>
        <button className="btn md primary" onClick={() => setCreating(true)}>New case</button>
      </header>
      <div className="filters">
        <select className="input sm" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })} aria-label="Stage">
          <option value="">All stages</option>
          {['consent_pending', 'intake', 'evidence', 'review', 'ready', 'signed', 'referred_out', 'closed'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {([['stop_now', 'Has stop-now'], ['mine', 'Assigned to me'], ['inactive', 'Inactive > 7 days']] as const).map(([k, l]) => (
          <label key={k} className="check"><input type="checkbox" checked={(f as any)[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} /> {l}</label>
        ))}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Applicant</th><th>Stage</th><th>Progress</th><th>Open review items</th><th>Assigned reviewer</th><th>Last activity</th><th>Link</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><a href={`/clinic/cases/${r.id}`} data-nav><strong>{r.applicant}</strong></a>{r.patient_mode && <span className="pill">patient</span>}</td>
                <td>{r.stage}</td>
                <td><div className="bar-mini"><div style={{ width: `${(100 * r.progress.have) / Math.max(1, r.progress.total)}%` }} /></div><span className="small">{r.progress.have}/{r.progress.total}</span></td>
                <td>{r.open_blocking > 0 ? <span className={`badge-count ${r.has_stop_now ? 'red' : ''}`}>{r.open_blocking}{r.has_stop_now ? ' · stop-now' : ''}</span> : '—'}</td>
                <td>{r.assigned_reviewer?.name ?? '—'}</td>
                <td className="small">{fmtTime(r.last_activity)}</td>
                <td className="small">{r.link_status.replace('_', ' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && <NewCase reviewers={reviewers} me={me} onClose={() => setCreating(false)} />}
    </>
  )
}

function NewCase({ reviewers, onClose }: { reviewers: any[]; me: Me; onClose: () => void }) {
  const [v, setV] = useState({ first_name: '', last_name: '', phone: '', patient_mode: false, assigned_reviewer: reviewers[0]?.id ?? '' })
  const [link, setLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    try {
      const r = await api('/api/clinic/cases', { body: { ...v, language: 'es-MX', assigned_reviewer: v.assigned_reviewer || null } })
      setLink(r.link)
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <dialog ref={(d) => { if (d && !d.open) d.showModal() }} onClose={onClose} className="dialog wide">
      <h2 className="h1">New case</h2>
      {!link ? <>
        <label className="field">First name<input className="input" value={v.first_name} onChange={(e) => setV({ ...v, first_name: e.target.value })} /></label>
        <label className="field">Last name<input className="input" value={v.last_name} onChange={(e) => setV({ ...v, last_name: e.target.value })} /></label>
        <label className="field">Phone (optional)<input className="input" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} /></label>
        <label className="field">Language<select className="input" disabled><option>Spanish (es-MX) — only option in Phase 1</option></select></label>
        <label className="check"><input type="checkbox" checked={v.patient_mode} onChange={(e) => setV({ ...v, patient_mode: e.target.checked })} /> Patient mode (slower voice, longer pauses)</label>
        <label className="field">Assigned reviewer
          <select className="input" value={v.assigned_reviewer} onChange={(e) => setV({ ...v, assigned_reviewer: e.target.value })}>
            {reviewers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        {err && <p className="rust">{err}</p>}
        <div className="btns"><button className="btn md primary" onClick={save} disabled={!v.first_name || !v.last_name}>Create case and link</button><button className="btn md" onClick={onClose}>Cancel</button></div>
      </> : <>
        <p className="lead">Send this link to the applicant. It expires 72 hours after issue (30 days after last use once opened).</p>
        <input className="input" readOnly value={link} onFocus={(e) => e.target.select()} />
        <div className="btns">
          <button className="btn md primary" onClick={() => navigator.clipboard?.writeText(link)}>Copy</button>
          <button className="btn md" disabled title="SMS is Phase 2+">Send by SMS</button>
          <button className="btn md" onClick={onClose}>Done</button>
        </div>
      </>}
    </dialog>
  )
}
