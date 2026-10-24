import type { ReactNode } from 'react'
import { daysToFile, fact, useCase } from './applicant/ApplicantApp'
import { Logo } from './icons'

type Section = 'chat' | 'form' | 'interview' | 'reminders' | 'profile'
const href: Record<Section, string> = { chat: '/', form: '/form', interview: '/interview', reminders: '/reminders', profile: '/profile' }

// The app frame: shared sidebar on the left, the page's <main> beside it (they stack when narrower than 800px).
export default function Shell({ active, children }: { active: Section; children: ReactNode }) {
  const { data } = useCase()
  const link = (to: Section, className = 'navlink') => ({ href: href[to], 'data-nav': true, className, 'aria-current': to === active ? ('page' as const) : undefined })
  const done = data.progress.filter((p: any) => p.state === 'done').length
  const days = daysToFile(data)
  const name = [fact(data, 'name.given') ?? data.first_name, fact(data, 'name.family')].filter(Boolean).join(' ')
  return (
    <div className="page">
      <div className="side">
        <nav aria-label="Ellis" className="sidebar">
          <a href="/" data-nav className="wordmark"><Logo /></a>
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
