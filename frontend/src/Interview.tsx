import { useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'

const tabs = [
  { id: 'interview', label: 'Interview' },
  { id: 'civics', label: 'Civics test' },
  { id: 'english', label: 'English test' },
]

const answers = [
  { id: 'a', text: 'The Constitution', right: true },
  { id: 'b', text: 'The Declaration of Independence' },
  { id: 'c', text: 'The Bill of Rights' },
  { id: 'd', text: 'Laws passed by Congress' },
]

export default function Interview() {
  const [tab, setTab] = useState('interview')
  const [pick, setPick] = useState<string | null>(null)

  return (
    <Shell active="interview">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Interview prep</h1>
          <div role="tablist" aria-label="What to practice" className="tabs">
            {tabs.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={t.id === tab} className="tab" onClick={() => setTab(t.id)}>{t.label}</button>
            ))}
          </div>
        </header>

        <div key={tab} className="content enter" style={{ padding: '48px 24px', gap: 24 }}>
          {tab === 'interview' && <>
            <div className="label">PRACTICE INTERVIEW · FROM YOUR OWN N-400 · QUESTION 6 OF 18</div>
            <section aria-label="Officer" className="card" style={{ padding: 32, gap: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <span className="label">THE OFFICER ASKS</span>
                <button type="button" className="btn" style={{ gap: 6 }}><Icon name="speaker" />Hear it again</button>
              </div>
              <p className="display">Have you traveled outside the United States since you became a resident?</p>
            </section>
            <section aria-label="Your answer" className="stack" style={{ padding: '24px 32px', background: 'var(--sand)', borderRadius: 6, gap: 10 }}>
              <span className="label">YOU SAID</span>
              <p className="lead" style={{ fontSize: 18, lineHeight: '30px' }}>"Yes. I went to Mexico in 2023 for about seven months, to take care of my mother. I also took short trips to Toronto and Cancún."</p>
            </section>
            <section aria-label="Feedback" className="stack" style={{ gap: 8 }}>
              <span className="label green">ELLIS</span>
              <p className="lead"><strong>Good answer.</strong> It matches your form. Next time, add the months you left and came back. Bring your records for the Mexico trip.</p>
            </section>
            <div className="btns">
              <button type="button" className="btn lg primary">Next question</button>
              <button type="button" className="btn lg strong"><Icon name="mic" color="#1e6b5b" />Answer again out loud</button>
            </div>
          </>}

          {tab === 'civics' && <>
            <div className="label" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8 }}>
              <span>CIVICS TEST · QUESTION 7 OF 20</span>
              <span className="soft">YOUR BEST: 14 · NEED 12 TO PASS</span>
            </div>
            <h2 className="display">What is the supreme law of the land?</h2>
            <div role="radiogroup" aria-label="Answers" className="stack" style={{ gap: 10 }}>
              {answers.map((a) => {
                const verdict = pick && a.right ? 'right' : pick === a.id ? 'wrong' : ''
                return (
                  <button key={a.id} type="button" role="radio" aria-checked={pick === a.id} className={`ans ${verdict}`} onClick={() => setPick(a.id)}>
                    <span style={{ flex: 1, textAlign: 'left' }}>{a.text}</span>
                    <span className="status">{verdict === 'right' ? 'Correct' : verdict && 'Not this one'}</span>
                  </button>
                )
              })}
            </div>
            {pick && (
              <p className="lead enter"><span className="label green">ELLIS</span> · The Constitution. It sets up the government, and every other law has to follow it. At the real test there are no choices: you say the answer out loud.</p>
            )}
            <div className="btns">
              <button type="button" className="btn lg primary" style={{ padding: '0 28px' }}>Next question</button>
              <button type="button" className="btn lg strong"><Icon name="mic" color="#1e6b5b" />Answer out loud</button>
            </div>
          </>}

          {tab === 'english' && <>
            <div className="label">ENGLISH TEST · READING</div>
            <p className="lead soft">The officer will ask you to read one sentence out loud. Read this one when you're ready.</p>
            <div className="card" style={{ display: 'block', padding: '48px 32px', fontFamily: 'var(--serif)', fontSize: 44, lineHeight: '54px', textAlign: 'center' }}>Citizens have the right to vote.</div>
            <div className="btns">
              <button type="button" className="btn lg primary"><Icon name="mic" />Read it out loud</button>
              <button type="button" className="btn lg strong">Practice writing instead</button>
            </div>
          </>}
        </div>
      </main>
    </Shell>
  )
}
