import type { ReactNode } from 'react'

type Section = 'chat' | 'form' | 'interview' | 'reminders' | 'advanced'

// The app frame: shared sidebar on the left, the page's <main> beside it (they stack when narrower than 800px).
export default function Shell({ active, children }: { active: Section; children: ReactNode }) {
  const link = (to: Section) => ({ href: `#/${to}`, className: 'navlink', 'aria-current': to === active ? ('page' as const) : undefined })
  return (
    <div className="page">
      <div className="side">
        <nav aria-label="Ellis" className="sidebar">
          <a href="#/chat" className="wordmark">Ellis</a>
          <div className="nav-list">
            <a {...link('chat')}>Chat with Ellis</a>
            <a {...link('form')}><span className="grow">N-400 form</span><span className="badge">6 of 10</span></a>
            <a {...link('interview')}>Interview prep</a>
            <a {...link('reminders')}><span className="grow">Reminders</span><span className="badge alert">11 days</span></a>
          </div>
          <div className="nav-list nav-foot">
            <a {...link('advanced')}>Advanced</a>
            <a href="#/advanced" className="account">
              <span aria-hidden="true" className="avatar">M</span>
              <span className="stack"><span style={{ fontSize: 15, fontWeight: 700 }}>Maria Alvarez</span><span className="soft" style={{ fontSize: 13 }}>Account</span></span>
            </a>
          </div>
        </nav>
      </div>
      {children}
    </div>
  )
}
