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
  const date = f && new Date(f.earliest_filing + 'T12:00').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase()
  // Ranked on the server (views.reminders), the same list Ellis reads from; the filing date has its own card above.
  const coming = [
    ...data.reminders.filter((r: any) => r.kind !== 'filing').map((r: any) => ({ title: r.title, note: r.note, when: r.when ? r.when[0].toUpperCase() + r.when.slice(1) : '', urgent: r.pressing || !!r.action })),
    ...data.roadmap.future.map((s: string) => ({ title: s, note: '', when: 'Coming soon', urgent: false })),
  ]

  return (
    <Shell active="reminders">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Reminders</h1>
        </header>

        <div className="content" style={{ padding: '48px 24px', gap: 40 }}>
          <section aria-label="Next up" className="dark" style={{ padding: 32, flexWrap: 'wrap', gap: 24, alignItems: 'flex-end', justifyContent: 'space-between' }}>
            <div className="stack" style={{ gap: 8 }}>
              <div style={{ fontSize: 16, lineHeight: '22px', color: 'var(--on-ink-soft)' }}>{!f ? 'Your filing date comes after a few more answers' : days ? 'You can file your N-400 in' : 'You can file your N-400'}</div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 60, lineHeight: '64px', letterSpacing: -0.5 }}>{!f ? 'Not yet' : days ? `${days} days` : 'now'}</div>
              {date && <div className="mono" style={{ fontSize: 14, fontWeight: 700, color: 'var(--gold)' }}>{days ? date : `SINCE ${date}`}</div>}
            </div>
            {f && days > 0 && (
              <a href={ics(f.earliest_filing, 'You can file your N-400')} download="ellis-filing-date.ics" className="btn md" style={{ borderColor: 'var(--on-ink-soft)', background: 'transparent', color: 'var(--white)' }}>Add to my calendar</a>
            )}
          </section>

          <section aria-labelledby="coming">
            <h2 id="coming" className="h1 rule">Coming up</h2>
            {coming.map((c) => (
              <div key={c.title} className="row" style={{ padding: '20px 0' }}>
                <span className="stack" style={{ flex: '1 1 280px', gap: 2 }}>
                  <span style={{ fontSize: 18, fontWeight: 700 }}>{c.title}</span>
                  {c.note && <span className="soft" style={{ fontSize: 15 }}>{c.note}</span>}
                </span>
                <span className={c.urgent ? 'status rust' : 'soft'} style={{ fontSize: 14 }}>{c.when}</span>
              </div>
            ))}
            <p className="soft" style={{ margin: '20px 0 0', fontSize: 15, lineHeight: '22px' }}>When a letter from USCIS arrives, upload a photo of it so your clinic has it.</p>
            <button type="button" className="btn lg primary" style={{ marginTop: 16 }} onClick={() => upload('other')}><Icon name="camera" />Add a USCIS letter</button>
          </section>
        </div>
      </main>
    </Shell>
  )
}
