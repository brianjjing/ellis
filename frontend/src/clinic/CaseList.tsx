// C1 Case list + New case.
import { useEffect, useState } from 'react'
import { api, fmtTime, relTime } from '../api'
import type { Me } from './ClinicApp'

// Sort: stop-now first → blocking → inactive → active by last_activity descending
function sortRows(rows: any[]): any[] {
  return [...rows].sort((a, b) => {
    const stopA = a.has_stop_now ? 2 : a.open_blocking > 0 ? 1 : 0
    const stopB = b.has_stop_now ? 2 : b.open_blocking > 0 ? 1 : 0
    if (stopB !== stopA) return stopB - stopA
    return (b.last_activity ?? '').localeCompare(a.last_activity ?? '')
  })
}

export default function CaseList({ me, tick }: { me: Me; tick: number }) {
  const [rows, setRows] = useState<any[]>([])
  const [reviewers, setReviewers] = useState<any[]>([])
  const [f, setF] = useState({ stage: '', stop_now: false, needs_you: false, mine: false, inactive: false })
  const [creating, setCreating] = useState(false)
  useEffect(() => {
    const q = new URLSearchParams()
    if (f.stage) q.set('stage', f.stage)
    if (f.stop_now) q.set('stop_now', 'true')
    if (f.mine) q.set('mine', 'true')
    if (f.inactive) q.set('inactive', 'true')
    api(`/api/clinic/cases?${q}`).then((r) => { setRows(r.cases); setReviewers(r.reviewers) })
  }, [tick, f])

  const visible = f.needs_you
    ? sortRows(rows).filter((r) => r.has_stop_now || r.open_blocking > 0)
    : sortRows(rows)

  const needsYouCount = rows.filter((r) => r.has_stop_now || r.open_blocking > 0).length

  return (
    <>
      <header className="bar">
        <h1 className="h1">Cases</h1>
        {needsYouCount > 0 && <span className="badge-count red">{needsYouCount} need{needsYouCount === 1 ? 's' : ''} you</span>}
        <button className="btn md primary" onClick={() => setCreating(true)}>New case</button>
      </header>
      <div className="filters">
        <select className="input sm" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })} aria-label="Stage">
          <option value="">All stages</option>
          {['consent_pending', 'intake', 'evidence', 'review', 'ready', 'signed', 'referred_out', 'closed'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {([['needs_you', 'Needs you'], ['stop_now', 'Has stop-now'], ['mine', 'Assigned to me'], ['inactive', 'Inactive > 7 days']] as const).map(([k, l]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={(f as any)[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} /> {l}
          </label>
        ))}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Applicant</th><th>Stage</th><th>Progress</th><th>Open review items</th>
              <th>Assigned reviewer</th><th>Last activity</th><th>Client link</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan={7} className="soft" style={{ padding: '20px 10px', textAlign: 'center' }}>
                {rows.length === 0 ? 'No cases yet.' : 'No cases match the current filters.'}
              </td></tr>
            )}
            {visible.map((r) => {
              const blocking = r.open_blocking > 0
              const blockingText = r.has_stop_now
                ? `${r.open_blocking} · stop now`
                : r.open_blocking > 0 ? `${r.open_blocking} blocking` : null
              return (
                <tr key={r.id} className={r.has_stop_now ? 'amber' : ''}>
                  <td>
                    <a href={`/clinic/cases/${r.id}`} data-nav><strong>{r.applicant}</strong></a>
                    {r.has_stop_now && <span className="badge-count red" style={{ marginLeft: 6, fontSize: 11 }}>stop now</span>}
                    {r.patient_mode && <span className="pill" title="This client receives a slower voice and longer pauses.">Extra support</span>}
                  </td>
                  <td>{r.stage}</td>
                  <td>
                    <div className="bar-mini"><div style={{ width: `${(100 * r.progress.have) / Math.max(1, r.progress.total)}%` }} /></div>
                    <span className="small">{r.progress.have}/{r.progress.total}</span>
                  </td>
                  <td>
                    {blocking ? <span className={`badge-count ${r.has_stop_now ? 'red' : ''}`}>{blockingText}</span> : '—'}
                  </td>
                  <td>{r.assigned_reviewer?.name ?? '—'}</td>
                  <td className="small">
                    <span title={fmtTime(r.last_activity)}>{relTime(r.last_activity)}</span>
                  </td>
                  <td className="small">{r.link_status.replace('_', ' ')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {creating && <NewCase reviewers={reviewers} me={me} onClose={() => setCreating(false)} />}
    </>
  )
}

const LANGUAGE_OPTIONS = [
  { value: 'en-US', label: 'English (US)' },
  { value: 'en-GB', label: 'English (UK)' },
  { value: 'es-MX', label: 'Spanish (Mexico)' },
  { value: 'es-US', label: 'Spanish (US)' },
  { value: 'es-ES', label: 'Spanish (Spain)' },
]

function NewCase({ reviewers, onClose }: { reviewers: any[]; me: Me; onClose: () => void }) {
  const [v, setV] = useState({ first_name: '', last_name: '', phone: '', language: 'en-US', patient_mode: false, assigned_reviewer: reviewers[0]?.id ?? '' })
  const [link, setLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    try {
      const r = await api('/api/clinic/cases', { body: { ...v, assigned_reviewer: v.assigned_reviewer || null } })
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
        <label className="field">Language <span className="soft">(the applicant can change this themselves before talking)</span>
          <select className="input" value={v.language} onChange={(e) => setV({ ...v, language: e.target.value })}>
            {LANGUAGE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="check"><input type="checkbox" checked={v.patient_mode} onChange={(e) => setV({ ...v, patient_mode: e.target.checked })} /> Extra support mode (slower voice, longer pauses)</label>
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
