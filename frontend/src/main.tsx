import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import './styles.css'
import SignIn from './SignIn'
import Chat from './Chat'
import Form from './Form'
import Interview from './Interview'
import Reminders from './Reminders'
import Advanced from './Advanced'

const pages = {
  signin: [SignIn, 'Sign in'],
  chat: [Chat, 'Chat'],
  form: [Form, 'N-400 form'],
  interview: [Interview, 'Interview prep'],
  reminders: [Reminders, 'Reminders'],
  advanced: [Advanced, 'Advanced'],
} as const

// ponytail: hash routes (#/chat) work on any static host; move to the History API once the backend serves the app.
function route() {
  const r = location.hash.slice(2)
  return Object.hasOwn(pages, r) ? (r as keyof typeof pages) : 'signin'
}

function App() {
  const [nav, setNav] = useState({ route: route(), n: 0 })
  const [Page, title] = pages[nav.route]

  useEffect(() => {
    // Like the design's separate pages, every navigation remounts the page and starts at the top.
    const go = () => {
      flushSync(() => setNav((v) => ({ route: route(), n: v.n + 1 })))
      scrollTo(0, 0)
    }
    // A link to the page you're already on fires no hashchange, but in the design it reloads (and resets) the page.
    const same = (e: MouseEvent) => {
      if ((e.target as Element).closest('a')?.hash === location.hash) go()
    }
    addEventListener('hashchange', go)
    addEventListener('click', same)
    return () => {
      removeEventListener('hashchange', go)
      removeEventListener('click', same)
    }
  }, [])

  useEffect(() => {
    document.title = `Ellis · ${title}`
  }, [title])

  return <Page key={nav.n} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
