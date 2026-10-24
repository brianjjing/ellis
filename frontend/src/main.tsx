import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './app.css'
import Home from './Home'
import ApplicantApp from './applicant/ApplicantApp'
import ClinicApp from './clinic/ClinicApp'

// History-API routing: /a/:token (applicant), /clinic/* (staff), / (landing).
export function navigate(to: string) {
  history.pushState(null, '', to)
  dispatchEvent(new PopStateEvent('popstate'))
}

function App() {
  const [path, setPath] = useState(location.pathname)
  useEffect(() => {
    const on = () => { setPath(location.pathname); scrollTo(0, 0) }
    addEventListener('popstate', on)
    // In-app links: <a data-nav href="/clinic/...">
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
  const m = path.match(/^\/a\/([^/]+)/)
  if (m) return <ApplicantApp token={decodeURIComponent(m[1])} />
  if (path.startsWith('/clinic')) return <ClinicApp path={path} />
  return <Home />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
