// Clinic workspace (/clinic): English, desktop-first. Intake staff, reviewers (attorneys / DOJ-accredited
// representatives) and admins. Every view is scoped to the signed-in user's clinic.
import { useEffect, useState } from 'react'
import { debounce, stream } from '../api'
import { signOut, useAuth } from '../auth'
import CaseDetail from './CaseDetail'
import CaseList from './CaseList'
import ReviewQueue from './ReviewQueue'
import Settings from './Settings'

export type Me = { id: string; name: string; email: string; role: string; clinic: { id: string; name: string; is_demo: boolean; settings: any } }

export default function ClinicApp({ path }: { path: string }) {
  const auth = useAuth()
  const me = auth.me as Me // main.tsx only renders this for staff
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!me) return
    const bump = debounce(() => setTick((t) => t + 1), 400)
    return stream('/api/clinic/stream', (m) => { if (m.type !== 'ping') bump() })
  }, [me])
  const logout = () => signOut(auth.refresh)

  const caseMatch = path.match(/^\/clinic\/cases\/([^/]+)/)
  const section = caseMatch ? 'cases' : path.startsWith('/clinic/review') ? 'review' : path.startsWith('/clinic/settings') ? 'settings' : 'cases'
  const link = (to: string, key: string, label: string) => (
    <a href={to} data-nav className="navlink" aria-current={section === key ? 'page' : undefined}>{label}</a>
  )
  return (
    <div className="page clinic" lang="en">
      <div className="side">
        <nav className="sidebar" aria-label="Clinic">
          <a href="/clinic" data-nav className="wordmark">Ellis</a>
          <div className="stack" style={{ padding: '0 12px', gap: 2 }}>
            <strong>{me.clinic.name}</strong>
            {me.clinic.is_demo && <span className="demo-tag">Synthetic demo data</span>}
          </div>
          <div className="nav-list">
            {link('/clinic', 'cases', 'Cases')}
            {(me.role === 'reviewer' || me.role === 'admin') && link('/clinic/review', 'review', 'Review queue')}
            {me.role === 'admin' && link('/clinic/settings', 'settings', 'Settings')}
          </div>
          <div className="nav-list nav-foot">
            <div className="account">
              <span aria-hidden="true" className="avatar">{me.name[0]}</span>
              <span className="stack"><strong style={{ fontSize: 15 }}>{me.name}</strong><span className="soft" style={{ fontSize: 13 }}>{me.role}</span></span>
            </div>
            <button className="btn" onClick={logout}>Sign out</button>
          </div>
        </nav>
      </div>
      <main className="main">
        {caseMatch ? <CaseDetail id={caseMatch[1]} me={me} tick={tick} />
          : section === 'review' ? <ReviewQueue me={me} tick={tick} />
          : section === 'settings' ? <Settings me={me} tick={tick} />
          : <CaseList me={me} tick={tick} />}
      </main>
    </div>
  )
}
