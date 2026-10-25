import type { ReactNode } from 'react'
import { daysToFile, fact, useCase } from './applicant/ApplicantApp'
import { goSignIn } from './auth'
import { Icon, Logo } from './icons'
import { navigate } from './main'

type Section = 'chat' | 'form' | 'interview' | 'reminders' | 'profile'
const href: Record<Section, string> = { chat: '/', form: '/form', interview: '/interview', reminders: '/reminders', profile: '/profile' }

// The app frame: shared sidebar on the left, the page's <main> beside it (they stack when narrower than 800px).
// Guests see only the chat item; locked pages are hidden rather than marked "Log in".
export default function Shell({ active, guest, children }: { active: Section; guest?: boolean; children: ReactNode }) {
  const ctx = useCase()
  const link = (to: Section, className = 'navlink') => ({ href: href[to], 'data-nav': true, className, 'aria-current': to === active ? ('page' as const) : undefined })
  if (guest || !ctx) {
    return (
      <div className="page">
        <div className="side">
          <nav aria-label="Ellis" className="sidebar">
            <a href="/" data-nav className="wordmark"><Logo /></a>
            <div className="nav-list">
              <a {...link('chat')}>Chat with Ellis</a>
            </div>
            <div className="nav-list nav-foot">
              <p className="small" style={{ padding: '0 12px' }}>Work at a clinic? <a href="/signin?next=/clinic" data-nav className="link-btn">Staff sign in</a></p>
            </div>
          </nav>
        </div>
        {children}
        {/* Mobile bottom nav — guest only has chat and sign-up */}
        <nav aria-label="Ellis" className="bot-nav">
          <a href="/" data-nav aria-current={active === 'chat' ? 'page' : undefined}>
            <Icon name="talk" size={20} />Chat
          </a>
          <button type="button" onClick={() => navigate('/signup')}>
            <Icon name="keyboard" size={20} />Sign up
          </button>
          <button type="button" onClick={() => goSignIn('/')}>
            <Icon name="lock" size={20} />Sign in
          </button>
        </nav>
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
          <a href="/" data-nav className="wordmark"><Logo /></a>
          {data.clinic.is_demo && <span className="demo-tag" style={{ alignSelf: 'flex-start', margin: '-20px 12px 0' }}>Demo data</span>}
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
      {/* Mobile bottom nav */}
      <nav aria-label="Ellis" className="bot-nav">
        <a href="/" data-nav aria-current={active === 'chat' ? 'page' : undefined}>
          <Icon name="talk" size={20} />Chat
        </a>
        <a href="/form" data-nav aria-current={active === 'form' ? 'page' : undefined}>
          <Icon name="keyboard" size={20} />Form
        </a>
        <a href="/interview" data-nav aria-current={active === 'interview' ? 'page' : undefined}>
          <Icon name="check" size={20} />Practice
        </a>
        <a href="/reminders" data-nav aria-current={active === 'reminders' ? 'page' : undefined}>
          <Icon name="send" size={20} />Reminders
        </a>
        <a href="/profile" data-nav aria-current={active === 'profile' ? 'page' : undefined}>
          <Icon name="globe" size={20} />Profile
        </a>
      </nav>
    </div>
  )
}
