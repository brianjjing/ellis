import Shell from './Shell'
import { Icon } from './icons'

const coming = [
  { title: 'Get your birth certificate translated', note: 'You need it before you file.', when: 'Before Nov 4', urgent: true },
  { title: 'Biometrics appointment', note: 'Fingerprints and a photo at a USCIS office.', when: 'Date comes by letter' },
  { title: 'Your interview', note: 'Includes the English and civics tests.', when: 'Date comes by letter' },
  { title: 'Oath ceremony', note: 'The day you become a citizen.', when: 'Date comes by letter' },
]

export default function Reminders() {
  return (
    <Shell active="reminders">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Reminders</h1>
        </header>

        <div className="content" style={{ padding: '48px 24px', gap: 40 }}>
          <section aria-label="Next up" className="dark" style={{ padding: 32, flexWrap: 'wrap', gap: 24, alignItems: 'flex-end', justifyContent: 'space-between' }}>
            <div className="stack" style={{ gap: 8 }}>
              <div style={{ fontSize: 16, lineHeight: '22px', color: 'var(--on-ink-soft)' }}>You can file your N-400 in</div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 60, lineHeight: '64px', letterSpacing: -0.5 }}>11 days</div>
              <div className="mono" style={{ fontSize: 14, fontWeight: 700, color: 'var(--gold)' }}>WEDNESDAY, NOV 4, 2026</div>
            </div>
            <button type="button" className="btn md" style={{ borderColor: 'var(--on-ink-soft)', background: 'transparent', color: 'var(--white)' }}>Add to my calendar</button>
          </section>

          <section aria-labelledby="coming">
            <h2 id="coming" className="h1 rule">Coming up</h2>
            {coming.map((c) => (
              <div key={c.title} className="row" style={{ padding: '20px 0' }}>
                <span className="stack" style={{ flex: '1 1 280px', gap: 2 }}>
                  <span style={{ fontSize: 18, fontWeight: 700 }}>{c.title}</span>
                  <span className="soft" style={{ fontSize: 15 }}>{c.note}</span>
                </span>
                <span className={c.urgent ? 'status rust' : 'soft'} style={{ fontSize: 14 }}>{c.when}</span>
              </div>
            ))}
            <p className="soft" style={{ margin: '20px 0 0', fontSize: 15, lineHeight: '22px' }}>When a letter from USCIS arrives, upload a photo of it. I'll add the date and remind you.</p>
            <button type="button" className="btn lg primary" style={{ marginTop: 16 }}><Icon name="camera" />Add a USCIS letter</button>
          </section>

          <section aria-labelledby="how" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 24px', alignItems: 'center' }}>
            <h2 id="how" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Remind me by</h2>
            {['Text message', 'Email'].map((how) => (
              <label key={how} style={{ display: 'flex', gap: 10, alignItems: 'center', minHeight: 44, fontSize: 16 }}>
                <input type="checkbox" defaultChecked style={{ width: 20, height: 20, accentColor: 'var(--green)' }} /> {how}
              </label>
            ))}
          </section>
        </div>
      </main>
    </Shell>
  )
}
