import { StrictMode, useEffect, useState, type JSX } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './app.css'
import SignIn from './SignIn'
import SignUp from './SignUp'
import GuestChat from './GuestChat'
import { AuthProvider, goSignIn, useAuth } from './auth'
import Chat from './Chat'
import Form from './Form'
import Interview from './Interview'
import Reminders from './Reminders'
import Profile from './Profile'
import ApplicantApp from './applicant/ApplicantApp'
import { ReviewPage } from './applicant/Review'
import ClinicApp from './clinic/ClinicApp'

// History-API routing: / (chat: the applicant's home, or the guest chat when logged out) and the other sidebar
// pages, /signin, /signup, /a/:token (the clinic's link signs the applicant in), /clinic/* (staff only).
export function navigate(to: string, replace = false) {
  history[replace ? 'replaceState' : 'pushState'](null, '', to)
  dispatchEvent(new PopStateEvent('popstate'))
}

const pages: Record<string, [() => JSX.Element, string]> = {
  '/': [Chat, 'Chat'],
  '/form': [Form, 'N-400 form'],
  '/interview': [Interview, 'Interview prep'],
  '/reminders': [Reminders, 'Reminders'],
  '/profile': [Profile, 'Profile'],
  '/review': [ReviewPage, 'Review and sign'],
}

function App() {
  const [url, setUrl] = useState(location.pathname + location.search)
  const path = url.split('?')[0]
  useEffect(() => {
    const on = () => { setUrl(location.pathname + location.search); scrollTo(0, 0) }
    addEventListener('popstate', on)
    // In-app links: <a data-nav href="/form">
    const click = (e: MouseEvent) => {
      const a = (e.target as Element).closest('a[data-nav]') as HTMLAnchorElement | null
      if (a && !e.metaKey && !e.ctrlKey && a.origin === location.origin) {
        e.preventDefault()
        navigate(a.pathname + a.search)
      }
    }
    addEventListener('click', click)
    return () => { removeEventListener('popstate', on); removeEventListener('click', click) }
  }, [])
  const [Page, title] = pages[path] ?? pages['/']
  useEffect(() => {
    document.title = path.startsWith('/clinic') ? 'Ellis · Clinic' : `Ellis · ${path === '/signin' || path.startsWith('/a/') ? 'Sign in' : path === '/signup' ? 'Sign up' : title}`
  }, [path, title])

  const { me } = useAuth()
  const kind = me?.kind
  const m = path.match(/^\/a\/([^/]+)/)
  const clinic = path.startsWith('/clinic')
  // Redirects run after render; a guest on an account page goes to sign-in, staff off /clinic go home to it.
  useEffect(() => {
    if (kind === 'staff' && !clinic && path !== '/signin' && path !== '/signup' && !m) navigate('/clinic', true)
    else if (kind && kind !== 'staff' && clinic) goSignIn(path)
    else if (kind === 'guest' && path in pages && path !== '/') goSignIn(path)
  }, [kind, path])

  if (m) return <SignIn token={decodeURIComponent(m[1])} />
  if (path === '/signin') return <SignIn />
  if (path === '/signup') return <SignUp />
  if (!me) return <div className="page" />
  if (clinic) return me.kind === 'staff' ? <ClinicApp path={path} /> : <div className="page" />
  if (me.kind === 'guest') return path === '/' || !(path in pages) ? <GuestChat /> : <div className="page" />
  if (me.kind === 'staff') return <div className="page" />
  return <ApplicantApp><Page key={url} /></ApplicantApp>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider><App /></AuthProvider>
  </StrictMode>,
)
