import { StrictMode, useEffect, useState, type JSX } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './app.css'
import SignIn from './SignIn'
import Chat from './Chat'
import Form from './Form'
import Interview from './Interview'
import Reminders from './Reminders'
import Profile from './Profile'
import ApplicantApp from './applicant/ApplicantApp'
import { ReviewPage } from './applicant/Review'
import ClinicApp from './clinic/ClinicApp'

// History-API routing: / (chat, the applicant's home) and the other sidebar pages, /signin, /a/:token
// (the clinic's link signs the applicant in), /clinic/* (staff).
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
    if (!path.startsWith('/clinic')) document.title = `Ellis · ${path === '/signin' || path.startsWith('/a/') ? 'Sign in' : title}`
  }, [path, title])

  const m = path.match(/^\/a\/([^/]+)/)
  if (m) return <SignIn token={decodeURIComponent(m[1])} />
  if (path.startsWith('/clinic')) return <ClinicApp path={path} />
  if (path === '/signin') return <SignIn />
  return <ApplicantApp><Page key={url} /></ApplicantApp>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
