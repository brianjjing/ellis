import Shell from './Shell'
import { Icon } from './icons'
import { daysToFile, useCase } from './applicant/ApplicantApp'

// An all-day calendar event as a downloadable .ics file.
function ics(date: string, title: string) {
  const d = date.replaceAll('-', '')
  return 'data:text/calendar;charset=utf-8,' + encodeURIComponent(
    `BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Ellis//EN\r\nBEGIN:VEVENT\r\nUID:${d}@ellis\r\nDTSTAMP:${d}T000000Z\r\nDTSTART;VALUE=DATE:${d}\r\nSUMMARY:${title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`)
}

export default function Reminders() {
  const { data, upload } = useCase()
  const f = data.filing_window
  const days = daysToFile(data)
  const date = f && new Date(f.earliest_filing + 'T12:00').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' })
  // The rules engine's window is timing only: until the form is signed, the card shows the next step instead.
  const left = data.progress.filter((p: any) => p.state !== 'done').length
  const next = data.state === 'signed' ? null
    : left > 0 ? { text: `${left} part${left > 1 ? 's' : ''} left on your form`, href: '/form', cta: 'Finish my form' }
    : data.state === 'ready' ? { text: 'Review and sign your form', href: '/review', cta: 'Review and sign' }
    : { text: 'Your clinic is checking your form', href: null, cta: null }
  const ghost = { borderColor: 'var(--on-ink-soft)', background: 'transparent', color: 'var(--white)' }
  const stages: { key: string; label: string }[] = data.roadmap.stages
  const current: number = data.roadmap.current
  // Ranked on the server (views.reminders), the same list Ellis reads from; the filing date has its own card above.
  const coming = data.reminders.filter((r: any) => r.kind !== 'filing').map((r: any) => ({
    title: r.title, note: r.note, when: r.when ? r.when[0].toUpperCase() + r.when.slice(1) : '', urgent: r.pressing || !!r.action,
  }))

  return (
    <Shell active="reminders">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Reminders</h1>
        </header>

        <div className="content" style={{ padding: '48px 24px', gap: 40 }}>
          {/* Next step card */}
          <section aria-label="Next step" className="dark" style={{ padding: 32, flexWrap: 'wrap', gap: 24, alignItems: 'flex-end', justifyContent: 'space-between' }}>
            <div className="stack" style={{ gap: 8 }}>
              <div style={{ fontSize: 14, lineHeight: '20px', color: 'var(--on-ink-soft)', fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase' }}>
                {!f ? 'Filing date' : days > 0 ? 'You can file your N-400 in' : next ? 'Your filing window is open' : 'You can file your N-400'}
              </div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 40, lineHeight: '48px', letterSpacing: -0.5 }}>
                {!f ? 'Complete your form to unlock your filing date' : days > 0 ? `${days} days` : next ? next.text : 'Now'}
              </div>
              {date && <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--gold)' }}>{days > 0 ? date : `Open since ${date}`}</div>}
              {f && <div style={{ fontSize: 13, color: 'var(--on-ink-soft)' }}>Your clinic will review this date.</div>}
            </div>
            {f && days > 0 && (
              <a href={ics(f.earliest_filing, 'You can file your N-400')} download="ellis-filing-date.ics" className="btn md" style={ghost}>Add to my calendar</a>
            )}
            {f && days === 0 && next?.href && <a href={next.href} data-nav className="btn md" style={ghost}>{next.cta}</a>}
          </section>

          {/* Roadmap stepper */}
          <section aria-labelledby="roadmap-heading">
            <h2 id="roadmap-heading" className="h1 rule" style={{ marginBottom: 24 }}>Your roadmap</h2>
            <div className="stack" style={{ gap: 0 }}>
              {stages.map((s, idx) => {
                const done = idx < current
                const active = idx === current
                return (
                  <div key={s.key} style={{ display: 'flex', gap: 16, alignItems: 'flex-start', paddingBottom: idx < stages.length - 1 ? 0 : 0 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: done ? 'var(--green)' : active ? 'var(--ink)' : 'var(--sand)',
                        color: done || active ? 'var(--white)' : 'var(--ink-soft)',
                        fontSize: 13, fontWeight: 700,
                      }}>
                        {done ? <Icon name="check" size={14} /> : idx + 1}
                      </div>
                      {idx < stages.length - 1 && (
                        <div style={{ width: 2, height: 32, background: done ? 'var(--green)' : 'var(--line-strong)', margin: '2px 0' }} />
                      )}
                    </div>
                    <div style={{ paddingTop: 4, paddingBottom: idx < stages.length - 1 ? 34 : 0 }}>
                      <span style={{ fontSize: 17, fontWeight: active ? 700 : done ? 600 : 400, color: active ? 'var(--ink)' : done ? 'var(--ink-soft)' : 'var(--ink-soft)' }}>
                        {s.label}
                      </span>
                      {active && <span className="status green" style={{ marginLeft: 10, fontSize: 12 }}>Current</span>}
                    </div>
                  </div>
                )
              })}
              {/* Future steps placeholder */}
              <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                <div style={{ width: 28, flexShrink: 0 }} />
                <p className="soft" style={{ fontSize: 15, lineHeight: '22px', paddingTop: 4 }}>Dates appear here once your clinic files.</p>
              </div>
            </div>
          </section>

          {coming.length > 0 && (
            <section aria-labelledby="coming">
              <h2 id="coming" className="h1 rule">Coming up</h2>
              {coming.map((c: any) => (
                <div key={c.title} className="row" style={{ padding: '20px 0' }}>
                  <span className="stack" style={{ flex: '1 1 280px', gap: 2 }}>
                    <span style={{ fontSize: 18, fontWeight: 700 }}>{c.title}</span>
                    {c.note && <span className="soft" style={{ fontSize: 15 }}>{c.note}</span>}
                  </span>
                  <span className={c.urgent ? 'status rust' : 'soft'} style={{ fontSize: 14 }}>{c.when}</span>
                </div>
              ))}
            </section>
          )}

          <section aria-label="USCIS letters">
            <p className="soft" style={{ fontSize: 15, lineHeight: '22px' }}>When a letter from USCIS arrives, upload a photo of it so your clinic has it.</p>
            <button type="button" className="btn lg primary" style={{ marginTop: 16 }} onClick={() => upload('other')}><Icon name="camera" />Add a USCIS letter</button>
          </section>
        </div>
      </main>
    </Shell>
  )
}
