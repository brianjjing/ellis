import Shell from './Shell'
import { Icon } from './icons'
import { goSignIn } from './auth'

type Locked = { active: 'form' | 'reminders' | 'profile'; title: string; head: string; body: string; sections: string[] }

// Account pages a guest can open: the page's real section headings over blocked-off rows, and the way in.
export const locked: Record<string, Locked> = {
  '/form': { active: 'form', title: 'N-400 form', head: 'Your N-400 answers live in your account', body: 'Ellis fills in your form as you talk. Create a free account to see your answers, part by part.', sections: ['Parts of the form'] },
  '/reminders': { active: 'reminders', title: 'Reminders', head: 'Your filing date and next steps need an account', body: 'They come from your answers. Your clinic will confirm them.', sections: ['Your roadmap', 'Coming up'] },
  '/profile': { active: 'profile', title: 'Profile', head: 'Your documents and case details need an account', body: 'Create a free account to keep your documents and case details in one place.', sections: ['Documents', 'Case details', 'Attorney'] },
  '/review': { active: 'form', title: 'Review and sign', head: 'Reviewing and signing need an account', body: 'Your clinic reviews your form, then you confirm every answer and sign.', sections: [] },
}

export default function GuestLocked({ path }: { path: string }) {
  const p = locked[path]
  const signup = `/signup?next=${encodeURIComponent(path)}`
  return (
    <Shell active={p.active} guest>
      <main className="main">
        <header className="bar">
          <h1 className="h1">{p.title}</h1>
          <div className="btns">
            <button type="button" className="btn" onClick={() => goSignIn(path)}>Log in</button>
            <a href={signup} data-nav className="btn primary">Sign up</a>
          </div>
        </header>
        <div className="content enter" style={{ padding: '48px 24px', gap: 40 }}>
          <section aria-labelledby="locked-head" className="card">
            <span className="label" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon name="lock" />Needs an account</span>
            <h2 id="locked-head" className="display">{p.head}</h2>
            <p className="lead soft">{p.body}</p>
            <div className="btns" style={{ alignItems: 'center', gap: 16 }}>
              <a href={signup} data-nav className="btn lg primary">Create a free account</a>
              <span className="small">Already have one? <button type="button" className="link-btn" onClick={() => goSignIn(path)}>Log in</button></span>
            </div>
            <p className="small">No account yet? You can still <a href="/" data-nav className="link-btn">chat with Ellis</a> or <a href="/interview" data-nav className="link-btn">practice the interview</a>.</p>
          </section>
          {p.sections.map((s) => (
            <section key={s} aria-hidden="true" className="ghost">
              <h2 className="h1 rule">{s}</h2>
              {[0, 1, 2].map((i) => <div key={i} className="row ghost-row"><span /><span /></div>)}
            </section>
          ))}
        </div>
      </main>
    </Shell>
  )
}
