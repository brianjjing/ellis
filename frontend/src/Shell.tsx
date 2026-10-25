import type { ReactNode } from 'react'
import { daysToFile, fact, useCase } from './applicant/ApplicantApp'
import { Icon, Logo } from './icons'
import { t } from './applicant/i18n'

type Section = 'chat' | 'form' | 'interview' | 'reminders' | 'profile'
// The N-400 badge's done count: red for the first few parts, a long run through amber, green when complete.
// Lightness drops toward yellow so every step stays readable (≥4.5:1) on the sand sidebar.
function progressColor(done: number, total: number) {
  if (done >= total) return 'var(--green)'
  const t = Math.max(0, done - 1) / Math.max(1, total - 2) // 0 at the first part, 1 at one short
  const h = t <= 2 / 11 ? 4 + t * 99 : 22 + (t - 2 / 11) * 29.33 // hue 4 (red) → 22 by part 3 → 46 (dark yellow)
  return `hsl(${h} 68% ${40 - (h - 4) / 4}%)`
}

const href: Record<Section, string> = { chat: '/', form: '/form', interview: '/interview', reminders: '/reminders', profile: '/profile' }

// The app frame: shared sidebar on the left, the page's <main> beside it (they stack when narrower than 800px).
// Guests see every page; account ones carry a lock and open a sign-up page (GuestLocked).
export default function Shell({ active, guest, children }: { active: Section; guest?: boolean; children: ReactNode }) {
  const ctx = useCase()
  const lock = <><Icon name="lock" color="var(--ink-soft)" /><span className="sr-only">, needs an account</span></>
  const link = (to: Section, className = 'navlink') => ({ href: href[to], 'data-nav': true, className, 'aria-current': to === active ? ('page' as const) : undefined })
  if (guest || !ctx) {
    return (
      <div className="page">
        <div className="side">
          <nav aria-label="Ellis" className="sidebar">
            <a href="/" data-nav className="wordmark"><Logo /></a>
            <div className="nav-list">
              <a {...link('chat')}>Chat with Ellis</a>
              <a {...link('form')}><span className="grow">N-400 form</span>{lock}</a>
              <a {...link('interview')}>Interview prep</a>
              <a {...link('reminders')}><span className="grow">Reminders</span>{lock}</a>
              <a {...link('profile')}><span className="grow">Profile</span>{lock}</a>
            </div>
            <div className="nav-list nav-foot">
              <div className="stack" style={{ gap: 10, padding: '0 12px 12px' }}>
                <p className="small">{t('en', 'saveAccount')}</p>
                <a href={`/signup?next=${encodeURIComponent(href[active])}`} data-nav className="btn primary">Sign up</a>
              </div>
              <p className="small" style={{ padding: '0 12px' }}>Work at a clinic? <a href="/signin?next=/clinic" data-nav className="link-btn">Staff sign in</a></p>
            </div>
          </nav>
        </div>
        {children}
        {/* Mobile bottom nav — guest: the open pages plus sign-up (Profile is in the sidebar; log in is in each page's header) */}
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
          <a href={`/signup?next=${encodeURIComponent(href[active])}`} data-nav>
            <Icon name="lock" size={20} />Sign up
          </a>
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
            <a {...link('form')}><span className="grow">N-400 form</span><span className="badge"><span style={{ color: progressColor(done, data.progress.length), fontWeight: 700 }}>{done}</span> of {data.progress.length}</span></a>
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
