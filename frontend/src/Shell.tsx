import type { ReactNode } from 'react'
import { daysToFile, fact, useCase } from './applicant/ApplicantApp'
import { goSignIn } from './auth'

type Section = 'chat' | 'form' | 'interview' | 'reminders' | 'profile'
const href: Record<Section, string> = { chat: '/', form: '/form', interview: '/interview', reminders: '/reminders', profile: '/profile' }

// The app frame: shared sidebar on the left, the page's <main> beside it (they stack when narrower than 800px).
// A guest sees the same sidebar with the account pages marked LOG IN.
export default function Shell({ active, guest, children }: { active: Section; guest?: boolean; children: ReactNode }) {
  const ctx = useCase()
  const link = (to: Section, className = 'navlink') => ({ href: href[to], 'data-nav': true, className, 'aria-current': to === active ? ('page' as const) : undefined })
  if (guest || !ctx) {
    const locked = (to: Section, label: string) => (
      <a href={href[to]} className="navlink" onClick={(e) => { e.preventDefault(); goSignIn(href[to]) }}><span className="grow">{label}</span><span className="badge">LOG IN</span></a>
    )
    return (
      <div className="page">
        <div className="side">
          <nav aria-label="Ellis" className="sidebar">
            <a href="/" data-nav className="wordmark">Ellis</a>
            <div className="nav-list">
              <a {...link('chat')}>Chat with Ellis</a>
              {locked('form', 'N-400 form')}
              {locked('interview', 'Interview prep')}
              {locked('reminders', 'Reminders')}
            </div>
            <div className="nav-list nav-foot">
              <p className="small" style={{ padding: '0 12px' }}>Work at a clinic? <a href="/signin?next=/clinic" data-nav className="link-btn" style={{ textDecoration: 'underline' }}>Staff sign in</a></p>
            </div>
          </nav>
        </div>
        {children}
      </div>
    )
  }
  const { data } = ctx
  const done = data.progress.filter((p: any) => p.state === 'done').length
  const days = daysToFile(data)
  const name = [fact(data, 'name.given') ?? data.first_name, fact(data, 'name.family')].filter(Boolean).join(' ')
  return (
    <div className="page">
      <div className="side">
        <nav aria-label="Ellis" className="sidebar">
          <a href="/" data-nav className="wordmark">Ellis</a>
          {data.clinic.is_demo && <span className="demo-tag" style={{ alignSelf: 'flex-start', margin: '-20px 12px 0' }}>DEMO DATA</span>}
          <div className="nav-list">
            <a {...link('chat')}>Chat with Ellis</a>
            <a {...link('form')}><span className="grow">N-400 form</span><span className="badge">{done} of {data.progress.length}</span></a>
            <a {...link('interview')}>Interview prep</a>
            <a {...link('reminders')}><span className="grow">Reminders</span>{days > 0 && <span className="badge alert">{days} days</span>}</a>
          </div>
          <div className="nav-list nav-foot">
            <a {...link('profile', 'account')}>
              <span aria-hidden="true" className="avatar">{name[0]}</span>
              <span className="stack"><span style={{ fontSize: 15, fontWeight: 700 }}>{name}</span><span className="soft" style={{ fontSize: 13 }}>Profile</span></span>
            </a>
          </div>
        </nav>
      </div>
      {children}
    </div>
  )
}
