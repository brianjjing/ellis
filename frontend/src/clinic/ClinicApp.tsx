// Clinic workspace (/clinic): English, desktop-first. Intake staff, reviewers (attorneys / DOJ-accredited
// representatives) and admins. Every view is scoped to the signed-in user's clinic.
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, debounce, stream } from '../api'
import { navigate } from '../main'
import CaseDetail from './CaseDetail'
import CaseList from './CaseList'
import ReviewQueue from './ReviewQueue'
import Settings from './Settings'

export type Me = { id: string; name: string; email: string; role: string; clinic: { id: string; name: string; is_demo: boolean; settings: any } }

export default function ClinicApp({ path }: { path: string }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined)
  const [tick, setTick] = useState(0)
  useEffect(() => { api('/api/clinic/me').then(setMe).catch(() => setMe(null)) }, [])
  useEffect(() => {
    if (!me) return
    const bump = debounce(() => setTick((t) => t + 1), 400)
    return stream('/api/clinic/stream', (m) => { if (m.type !== 'ping') bump() })
  }, [me])
  const logout = async () => { await api('/api/clinic/logout', { body: {} }); setMe(null); navigate('/clinic') }

  if (me === undefined) return <div className="page col clinic"><p className="lead" style={{ padding: 24 }}>Loading…</p></div>
  if (me === null) return <Login onIn={setMe} />

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

function Login({ onIn }: { onIn: (m: Me) => void }) {
  const [email, setEmail] = useState('dana@valle.demo')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const submit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    try { onIn(await api('/api/clinic/login', { body: { email, password: pw } })) } catch (x) { setErr(x instanceof ApiError ? x.message : 'Sign-in failed') }
  }, [email, pw])
  return (
    <div className="page col" lang="en">
      <header className="top"><span className="wordmark">Ellis</span><span className="soft">Clinic workspace</span></header>
      <main className="signin">
        <form className="card" onSubmit={submit}>
          <h1 className="h1">Sign in</h1>
          <label htmlFor="em" className="field">Email</label>
          <input id="em" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          <label htmlFor="pw" className="field">Password</label>
          <input id="pw" className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
          {err && <p className="rust">{err}</p>}
          <button className="btn lg primary" type="submit">Sign in</button>
          <p className="small">Demo: dana@valle.demo (reviewer), sam@valle.demo (intake), admin@valle.demo — password ellis-demo</p>
        </form>
      </main>
    </div>
  )
}
