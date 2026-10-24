import { useEffect, useState } from 'react'
import { Icon } from './icons'
import { api, ApiError } from './api'
import { navigate } from './main'

// The applicant's credential is the private link their clinic sends (/a/:token). Opening it signs in here;
// the code field takes the same link (or just its code) pasted in.
export default function SignIn({ token }: { token?: string }) {
  const [code, setCode] = useState(token ?? '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(!!token)
  const [lang, setLang] = useState<'en' | 'es' | null>(null)

  const signIn = async (raw = code) => {
    const t = raw.trim().split('/a/').pop()!.split(/[?#]/)[0]
    if (!t) return
    setBusy(true)
    setErr(null)
    try {
      await api('/api/a/session', { body: { token: decodeURIComponent(t) } })
      if (lang) await api('/api/a/language', { body: { locale: lang === 'en' ? 'en-US' : 'es-MX' } }).catch(() => undefined)
      navigate('/', true)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Connection lost. Please try again.')
      setBusy(false)
    }
  }
  useEffect(() => { if (token) signIn(token) }, [])

  return (
    <div className="page col">
      <header className="top">
        <span className="wordmark">Ellis</span>
        <button type="button" className="btn" onClick={() => setLang(lang === 'es' ? 'en' : 'es')}><Icon name="globe" />{lang === 'es' ? 'Español' : 'English'}</button>
      </header>

      <main className="signin">
        <div className="enter"><form style={{ display: 'contents' }} onSubmit={(e) => { e.preventDefault(); signIn() }}>
          <h1 className="display">Sign in to Ellis</h1>
          <p className="lead soft pull">Your forms and documents are private. Only you and your clinic can open them.</p>
          <div className="card">
            <label htmlFor="code" className="field">Code</label>
            <input id="code" type="text" autoComplete="one-time-code" autoCapitalize="off" spellCheck={false} placeholder="Paste the link or code from your clinic" className="input" value={code} onChange={(e) => setCode(e.target.value)} />
            {err && <p className="rust" role="alert" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{err}</p>}
            <button type="submit" className="btn lg primary" disabled={busy}><Icon name="lock" />{busy ? 'Signing in…' : 'Sign in'}</button>
            <p className="small">Your clinic sends you a private link by text or email. Opening it signs you in. Ellis is not a law firm and is not part of USCIS.</p>
          </div>
          <p className="switch">Work at a clinic? <a href="/clinic" data-nav className="link-btn" style={{ textDecoration: 'underline' }}>Staff sign in</a></p>
        </form></div>
      </main>
    </div>
  )
}
