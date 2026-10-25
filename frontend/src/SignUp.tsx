import { useEffect, useState } from 'react'
import { Icon, Logo } from './icons'
import { api, ApiError } from './api'
import { landing, useAuth, type Me } from './auth'
import { guestSnapshot } from './GuestChat'

type Kind = 'applicant' | 'clinic'

// One sign-up: an applicant gets an account and their own case; a clinic gets created with this person as admin.
// With a clinic's link (/a/:token, logged out): applicant only, name prefilled, and the case joins the account.
export default function SignUp({ token }: { token?: string }) {
  const { refresh } = useAuth()
  const next = new URLSearchParams(location.search).get('next')
  const [kind, setKind] = useState<Kind>('applicant')
  const [f, setF] = useState({ name: '', email: '', password: '', clinic_name: '' })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState<{ clinic_name: string } | null>(null)
  useEffect(() => {
    if (token) api(`/api/auth/link/${encodeURIComponent(token)}`)
      .then((p) => { setLink(p); setF((f) => ({ ...f, name: `${p.first_name} ${p.last_name}`.trim() })) })
      .catch((e) => setErr(e instanceof ApiError ? e.message : 'Connection lost. Please try again.'))
  }, [token])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })

  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api<Me>('/api/auth/signup', { body: { kind, ...f, link_token: token, guest: kind === 'applicant' ? guestSnapshot() : undefined } })
      landing(await refresh(), next)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Connection lost. Please try again.')
      setBusy(false)
    }
  }

  const opt = (k: Kind, label: string) => (
    <div role="radio" tabIndex={0} aria-checked={kind === k} className="opt" onClick={() => setKind(k)} onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && (e.preventDefault(), setKind(k))}>
      <span aria-hidden="true" className="dot" /><span style={{ fontSize: 17, fontWeight: 700 }}>{label}</span>
    </div>
  )
  return (
    <div className="page col">
      <header className="top">
        <a href="/" data-nav className="wordmark"><Logo /></a>
      </header>

      <main className="signin">
        <div className="enter"><form style={{ display: 'contents' }} onSubmit={(e) => { e.preventDefault(); submit() }}>
          <h1 className="display">{link ? `Join ${link.clinic_name} on Ellis` : 'Create your Ellis account'}</h1>
          <p className="lead soft pull">Your forms and documents are private. Only you and your clinic can open them.</p>
          <div className="card">
            {!token && <div role="radiogroup" aria-label="I am" className="stack" style={{ gap: 8 }}>
              {opt('applicant', 'Applying for U.S. citizenship')}
              {opt('clinic', 'Part of a legal clinic')}
            </div>}
            {kind === 'clinic' && <>
              <label htmlFor="cn" className="field">Clinic name</label>
              <input id="cn" className="input" type="text" autoComplete="organization" value={f.clinic_name} onChange={set('clinic_name')} />
            </>}
            <label htmlFor="nm" className="field">Your name</label>
            <input id="nm" className="input" type="text" autoComplete="name" value={f.name} onChange={set('name')} />
            <label htmlFor="em" className="field">Email</label>
            <input id="em" className="input" type="email" autoComplete="email" value={f.email} onChange={set('email')} />
            <label htmlFor="pw" className="field">Password</label>
            <input id="pw" className="input" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} />
            <p className="small" style={{ margin: 0 }}>At least 8 characters</p>
            {err && <p className="rust" role="alert" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{err}</p>}
            <button type="submit" className="btn lg primary" disabled={busy}><Icon name="lock" />{busy ? 'Creating…' : 'Create account'}</button>
            <p className="small">Ellis is not a law firm and is not part of USCIS.</p>
          </div>
          <p className="switch">Already have an account? <a href={token ? `/signin?next=${encodeURIComponent(`/a/${token}`)}` : `/signin${next ? `?next=${encodeURIComponent(next)}` : ''}`} data-nav className="link-btn">Log in</a></p>
        </form></div>
      </main>
    </div>
  )
}
