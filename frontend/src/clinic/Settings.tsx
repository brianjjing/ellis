// C4 Settings (admin): branding, staff, referral text overrides, retention, audit log + CSV.
import { useEffect, useState } from 'react'
import { api, fmtTime } from '../api'
import type { Me } from './ClinicApp'

export default function Settings({ tick }: { me: Me; tick: number }) {
  const [s, setS] = useState<any>(null)
  const [staff, setStaff] = useState<any[]>([])
  const [audit, setAudit] = useState<any[]>([])
  const [inv, setInv] = useState({ name: '', email: '', role: 'intake', password: '' })
  const [msg, setMsg] = useState<string | null>(null)
  const load = () => {
    api('/api/clinic/settings').then(setS)
    api('/api/clinic/staff').then((r) => setStaff(r.staff))
    api('/api/clinic/audit?limit=200').then((r) => setAudit(r.events))
  }
  useEffect(load, [tick])
  if (!s) return null
  const st = s.settings ?? {}
  const save = async (patch: any) => { await api('/api/clinic/settings', { method: 'PATCH', body: patch }); setMsg('Saved'); load() }
  return (
    <>
      <header className="bar"><h1 className="h1">Settings</h1>{msg && <span className="green">{msg}</span>}</header>
      <div className="detail-body stack" style={{ gap: 28 }}>
        <section className="stack" style={{ gap: 8, maxWidth: 560 }}>
          <h2 className="h3 rule">Clinic</h2>
          <label className="field">Name shown to applicants<input className="input" defaultValue={s.name} onBlur={(e) => e.target.value !== s.name && save({ name: e.target.value })} /></label>
          <label className="field">Phone shown to applicants<input className="input" defaultValue={st.phone} onBlur={(e) => save({ settings: { phone: e.target.value } })} /></label>
        </section>
        <section>
          <h2 className="h3 rule">Staff</h2>
          <table className="table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th></tr></thead>
            <tbody>{staff.map((u) => (
              <tr key={u.id}><td>{u.name}</td><td>{u.email}</td>
                <td><select className="input sm" value={u.role} onChange={async (e) => { await api(`/api/clinic/staff/${u.id}`, { method: 'PATCH', body: { role: e.target.value } }); load() }}>{['intake', 'reviewer', 'admin'].map((r) => <option key={r}>{r}</option>)}</select></td>
                <td><button className="btn" onClick={async () => { await api(`/api/clinic/staff/${u.id}`, { method: 'PATCH', body: { active: !u.active } }); load() }}>{u.active ? 'Deactivate' : 'Activate'}</button></td></tr>
            ))}</tbody></table>
          <div className="btns" style={{ marginTop: 12 }}>
            <input className="input sm" placeholder="Name" value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} />
            <input className="input sm" placeholder="Email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />
            <select className="input sm" value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })}>{['intake', 'reviewer', 'admin'].map((r) => <option key={r}>{r}</option>)}</select>
            <input className="input sm" placeholder="Temporary password" value={inv.password} onChange={(e) => setInv({ ...inv, password: e.target.value })} />
            <button className="btn md" disabled={!inv.email || !inv.password} onClick={async () => { await api('/api/clinic/staff', { body: inv }); setInv({ name: '', email: '', role: 'intake', password: '' }); load() }}>Invite</button>
          </div>
        </section>
        <section className="stack" style={{ gap: 8, maxWidth: 720 }}>
          <h2 className="h3 rule">Referral card text (Spanish)</h2>
          {(['flag_continue', 'stop_now'] as const).map((k) => (
            <label key={k} className="field">{k === 'stop_now' ? 'Stop-now title' : 'Flag-and-continue title'} <span className="soft">(default: {s.referral_defaults[k].title})</span>
              <input className="input" defaultValue={st.referral_text?.[k] ?? ''} placeholder={s.referral_defaults[k].title}
                onBlur={(e) => save({ settings: { referral_text: { ...(st.referral_text ?? {}), [k]: e.target.value } } })} />
            </label>
          ))}
        </section>
        <section className="stack" style={{ gap: 8, maxWidth: 560 }}>
          <h2 className="h3 rule">Retention</h2>
          <label className="field">Transcripts
            <select className="input" defaultValue={String(st.retention?.transcripts_days ?? 90)} onChange={(e) => save({ settings: { retention: { ...(st.retention ?? {}), transcripts_days: e.target.value === 'none' ? 'none' : Number(e.target.value) } } })}>
              <option value="30">Keep 30 days</option><option value="90">Keep 90 days</option><option value="none">No transcripts</option>
            </select>
          </label>
          <label className="field">Delete closed cases after (days)<input className="input" type="number" defaultValue={st.retention?.closed_case_delete_days ?? 90} onBlur={(e) => save({ settings: { retention: { ...(st.retention ?? {}), closed_case_delete_days: Number(e.target.value) } } })} /></label>
        </section>
        <section>
          <h2 className="h3 rule">Audit log <a className="btn" href="/api/clinic/audit?format=csv&limit=5000">Export CSV</a></h2>
          <table className="table"><thead><tr><th>Time</th><th>Case</th><th>Event</th><th>Actor</th></tr></thead>
            <tbody>{audit.map((e) => <tr key={e.id}><td className="small">{fmtTime(e.ts)}</td><td className="small">{e.case_id ?? '—'}</td><td>{e.kind}</td><td className="small">{e.actor_type} · {e.actor}</td></tr>)}</tbody></table>
        </section>
      </div>
    </>
  )
}
