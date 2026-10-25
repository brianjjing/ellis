import { useEffect, useState } from 'react'
import { Icon, Logo } from './icons'
import { api, ApiError } from './api'
import { navigate } from './main'
import { landing, useAuth, type Me } from './auth'

const headings: Record<string, string> = { '/form': 'Log in to start your N-400', '/conversations': 'Log in to see your conversations' }

// One sign-in for everyone: email and password (the account decides where you land), plus the clinic's
// private link or code (/a/:token opens a link-only session, as before).
export default function SignIn({ token }: { token?: string }) {
  const { me, refresh } = useAuth()
  const next = new URLSearchParams(location.search).get('next')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [showCode, setShowCode] = useState(!!token)
  const [code, setCode] = useState(token ?? '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(!!token)
  const [lang, setLang] = useState<'en' | 'es' | null>(null)

  const fail = (e: unknown) => { setErr(e instanceof ApiError ? e.message : 'Connection lost. Please try again.'); setBusy(false) }
  // The header's language pick applies to the applicant's case once they're in (staff work in English).
  const applyLang = async () => { if (lang) await api('/api/a/language', { body: { locale: lang === 'en' ? 'en-US' : 'es-MX' } }).catch(() => undefined) }

  const logIn = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api<Me>('/api/auth/login', { body: { email, password: pw } })
      const m = await refresh()
      if (m.kind === 'applicant') await applyLang()
      landing(m, next)
    } catch (e) { fail(e) }
  }

  const useCode = async (raw = code) => {
    const t = raw.trim().split('/a/').pop()!.split(/[?#]/)[0]
    if (!t) return
    setBusy(true)
    setErr(null)
    try {
      // A logged-in applicant claims the clinic's case into their account; otherwise a link-only session.
      const claim = me?.kind === 'applicant' && me.account
      await api(claim ? '/api/a/link' : '/api/a/session', { body: { token: decodeURIComponent(t) } })
      await applyLang()
      await refresh()
      navigate('/', true)
    } catch (e) { fail(e) }
  }
  useEffect(() => { if (token) useCode(token) }, [])

  const heading = next ? headings[next] ?? 'Log in to continue' : 'Log in to Ellis'
  return (
    <div className="page col">
      <header className="top">
        <a href="/" data-nav className="wordmark"><Logo /></a>
        <button type="button" className="btn" onClick={() => setLang(lang === 'es' ? 'en' : 'es')}><Icon name="globe" />{lang === 'es' ? 'Español' : 'English'}</button>
      </header>

      <main className="signin">
        <div className="enter"><form style={{ display: 'contents' }} onSubmit={(e) => { e.preventDefault(); showCode ? useCode() : logIn() }}>
          <h1 className="display">{heading}</h1>
          <p className="lead soft pull">Your forms and documents are private. Only you and your clinic can open them.</p>
          <div className="card">
            {showCode ? <>
              <label htmlFor="code" className="field">Code</label>
              <input id="code" type="text" autoComplete="one-time-code" autoCapitalize="off" spellCheck={false} placeholder="Paste the link or code from your clinic" className="input" value={code} onChange={(e) => setCode(e.target.value)} />
            </> : <>
              <label htmlFor="em" className="field">Email</label>
              <input id="em" className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              <label htmlFor="pw" className="field">Password</label>
              <input id="pw" className="input" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
            </>}
            {err && <p className="rust" role="alert" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{err}</p>}
            <button type="submit" className="btn lg primary" disabled={busy}><Icon name="lock" />{busy ? 'Signing in…' : 'Log in'}</button>
            <div className="or">or</div>
            <button type="button" className="btn lg strong" onClick={() => { setShowCode(!showCode); setErr(null) }}>
              {showCode ? 'Log in with email instead' : 'I have a link or code from a clinic'}
            </button>
            <p className="small">Ellis is not a law firm and is not part of USCIS.</p>
          </div>
          <p className="switch">New to Ellis? <a href={`/signup${next ? `?next=${encodeURIComponent(next)}` : ''}`} data-nav className="link-btn">Create an account</a></p>
        </form></div>
      </main>
    </div>
  )
}
