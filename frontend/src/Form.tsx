import { useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'

const options = [
  { id: 'yes', label: 'Yes' },
  { id: 'no', label: 'No' },
  { id: 'unsure', label: "I'm not sure" },
]

const trips = [
  { place: 'Bogotá, Colombia', dates: 'Dec 18, 2022 – Jan 2, 2023', status: 'Done', color: 'green' },
  { place: 'Mexico City, Mexico', dates: 'Jun 1, 2023 – Jan 4, 2024', status: 'With attorney · F-01', color: 'blue' },
  { place: 'Toronto, Canada', dates: 'Mar 7 – Mar 10, 2025', status: 'Done', color: 'green' },
  { place: 'Cancún, Mexico', dates: 'Aug 9, 2025 – ?', status: 'Add return date', color: 'rust' },
]

const status = { d: ['Done', 'green'], c: ['Confirm answers', 'rust'], p: ['In progress', ''], t: ['Not started', 'soft'] }
const parts = [
  ['01', 'Eligibility', 'd'], ['02', 'About you', 'd'], ['03', 'What you look like', 'd'],
  ['04', 'Where you lived', 'c'], ['05', 'Your parents', 'd'], ['06', 'Marriage', 'd'],
  ['07', 'Children', 'd'], ['08', 'Work and school', 'p'], ['09', 'Time outside the U.S.', 'p'],
  ['10', 'More about you', 't'],
] as const

// Progress bar, one segment per part: done, needs attention, not started.
const segments = ['green', 'green', 'green', 'gold', 'green', 'green', 'green', 'gold', 'gold', 'segment-idle']

export default function Form() {
  const [pick, setPick] = useState('yes')
  const [view, setView] = useState<'question' | 'parts'>('question')
  const question = view === 'question'

  return (
    <Shell active="form">
      <main className="main">
        <header className="bar">
          <div className="stack" style={{ gap: 4 }}>
            <div className="mono" style={{ fontSize: 12, lineHeight: '16px' }}>N-400 · APPLICATION FOR CITIZENSHIP</div>
            <h1 className="h1">6 of 10 parts done</h1>
          </div>
          <div className="btns">
            <button type="button" className="btn" onClick={() => setView(question ? 'parts' : 'question')}>{question ? 'See all parts' : 'Back to my question'}</button>
            <button type="button" className="btn"><Icon name="upload" />Fill from a document</button>
          </div>
        </header>
        <div aria-hidden="true" className="progress">
          {segments.map((c, i) => <div key={i} style={{ background: `var(--${c})` }} />)}
        </div>

        {question ? (
          <div className="content enter" style={{ padding: '48px 24px', gap: 28 }}>
            <div className="label">PART 9 · TIME OUTSIDE THE U.S. · QUESTION 2 OF 4</div>
            <h2 className="display" style={{ marginTop: -14 }}>In the last 5 years, did you take any trips outside the U.S. longer than 24 hours?</h2>
            <p className="lead soft pull">Count every trip, even a weekend in Canada or Mexico. A rough guess is fine.</p>

            <fieldset className="stack" style={{ margin: 0, padding: 0, border: 0, gap: 10 }}>
              <legend className="sr-only">Your answer</legend>
              {options.map((o) => (
                <button key={o.id} type="button" role="radio" aria-checked={pick === o.id} className={`opt ${o.id}`} onClick={() => setPick(o.id)}>
                  <span aria-hidden="true" className="dot" />
                  <span style={{ fontSize: 18, lineHeight: '24px', fontWeight: 700, textAlign: 'left' }}>{o.label}</span>
                </button>
              ))}
            </fieldset>

            {pick === 'yes' && (
              <section aria-labelledby="trips" className="stack enter">
                <h3 id="trips" className="rule" style={{ fontSize: 17, lineHeight: '24px', fontWeight: 700 }}>
                  <span className="mono green">ELLIS</span> · I found these 4 trips in your passport
                </h3>
                {trips.map((t) => (
                  <div key={t.place} className="row" style={{ padding: '16px 0' }}>
                    <span style={{ flex: '1 1 220px', fontSize: 17, fontWeight: 700 }}>{t.place}</span>
                    <span className="mono" style={{ flex: '1 1 220px', fontSize: 15 }}>{t.dates}</span>
                    <span className={`status ${t.color}`}>{t.status}</span>
                  </div>
                ))}
              </section>
            )}

            <div className="btns" style={{ alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <a href="#/chat" className="talk"><Icon name="mic" />Answer by talking to Ellis</a>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn lg">Back</button>
                <button type="button" className="btn lg primary" style={{ padding: '0 32px' }}>Continue</button>
              </div>
            </div>
          </div>
        ) : (
          <div className="content enter" style={{ padding: '40px 24px 48px' }}>
            {parts.map(([n, name, k]) => (
              <button key={n} type="button" className="part" onClick={() => setView('question')}>
                <span className="mono" style={{ flex: '0 0 32px', fontSize: 14, fontWeight: 700 }}>{n}</span>
                <span style={{ flex: '1 1 240px', fontSize: 17, fontWeight: 700 }}>{name}</span>
                <span className={`status ${status[k][1]}`}>{status[k][0]}</span>
              </button>
            ))}
          </div>
        )}
      </main>
    </Shell>
  )
}
