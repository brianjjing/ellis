import { useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'

// ponytail: study and mock interview are Phase 2 with no Case API behind them yet, so this page practices
// generic questions with the browser's own speech (speechSynthesis / SpeechRecognition) and saves nothing.

const tabs = [
  { id: 'interview', label: 'Interview' },
  { id: 'civics', label: 'Civics test' },
  { id: 'english', label: 'English test' },
]

const officer = [
  'Have you traveled outside the United States since you became a permanent resident?',
  'What is your current home address?',
  'Where do you work, and how long have you worked there?',
  'Are you married? How long have you been married?',
  'Have you ever been arrested, cited or detained by a law enforcement officer?',
]

const civics = [
  { q: 'What is the supreme law of the land?', answers: ['The Constitution', 'The Declaration of Independence', 'The Bill of Rights', 'Laws passed by Congress'], why: 'The Constitution. It sets up the government, and every other law has to follow it.' },
  { q: 'What do we call the first ten amendments to the Constitution?', answers: ['The Bill of Rights', 'The Preamble', 'The Articles of Confederation', 'The Federalist Papers'], why: 'The Bill of Rights. It protects rights like free speech and religion.' },
  { q: 'How many U.S. senators are there?', answers: ['One hundred (100)', 'Fifty (50)', 'Four hundred thirty-five (435)', 'Two hundred (200)'], why: 'One hundred. Each state has two senators.' },
  { q: 'Who is in charge of the executive branch?', answers: ['The President', 'The Chief Justice', 'The Speaker of the House', 'The Senate'], why: 'The President. The President also commands the military.' },
]

const sentence = 'Citizens have the right to vote.'

const say = (text: string) => {
  speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'en-US'
  speechSynthesis.speak(u)
}

// One spoken answer from the browser's recognizer; '' where the browser has none or nothing was heard.
function listen(): Promise<string> {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) return Promise.resolve('')
  return new Promise((done) => {
    const r = new SR()
    r.lang = 'en-US'
    r.onresult = (e: any) => done(e.results[0][0].transcript)
    r.onerror = r.onend = () => done('')
    r.start()
  })
}

const same = (a: string, b: string) => a.toLowerCase().replace(/[^a-z ]/g, '').trim() === b.toLowerCase().replace(/[^a-z ]/g, '').trim()

// Highlight words in `heard` that differ from the corresponding word in `target` (word-level diff).
function HighlightDiff({ heard, target }: { heard: string; target: string }) {
  const heardWords = heard.split(/\s+/)
  const targetWords = target.replace(/[.!?,]/g, '').toLowerCase().split(/\s+/)
  return (
    <span>
      {heardWords.map((w, i) => {
        const clean = w.replace(/[^a-z]/gi, '').toLowerCase()
        const ok = clean === (targetWords[i] ?? '')
        return <span key={i} style={ok ? undefined : { color: 'var(--rust)', textDecoration: 'underline', textDecorationStyle: 'wavy' }}>{w}{i < heardWords.length - 1 ? ' ' : ''}</span>
      })}
    </span>
  )
}

export default function Interview() {
  const [tab, setTab] = useState('interview')
  const [n, setN] = useState(0)
  const [pick, setPick] = useState<number | null>(null)
  const [heard, setHeard] = useState<string | null>(null)
  const [writing, setWriting] = useState('')
  const [writeMode, setWriteMode] = useState(false)
  const [score, setScore] = useState({ right: 0, asked: 0 })
  const [mic, setMic] = useState(false)
  const [showChoices, setShowChoices] = useState(false)
  const next = () => { setN(n + 1); setPick(null); setHeard(null); setShowChoices(false) }
  const answerOutLoud = async () => { setMic(true); setHeard(await listen() || "I didn't hear anything. Your browser may not support listening."); setMic(false) }
  const q = officer[n % officer.length]
  const c = civics[n % civics.length]

  return (
    <Shell active="interview">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Interview prep</h1>
          <div role="tablist" aria-label="What to practice" className="tabs">
            {tabs.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={t.id === tab} className="tab" onClick={() => { setTab(t.id); setN(0); setPick(null); setHeard(null) }}>{t.label}</button>
            ))}
          </div>
        </header>

        <div key={tab} className="content enter" style={{ padding: '48px 24px', gap: 24 }}>
          {tab === 'interview' && <>
            <div className="label">Practice interview · question {(n % officer.length) + 1} of {officer.length}</div>
            <section aria-label="Officer" className="card" style={{ padding: '9px 32px 41px', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <span className="label">The officer asks</span>
                <button type="button" className="btn" style={{ gap: 6, minHeight: 0, height: 32 }} onClick={() => say(q)}><Icon name="speaker" />Hear it again</button>
              </div>
              <p className="display">{q}</p>
            </section>
            {heard && (
              <section aria-label="Your answer" className="stack enter" style={{ padding: '24px 32px', background: 'var(--sand)', borderRadius: 6, gap: 10 }}>
                <span className="label">You said</span>
                <p className="lead" style={{ fontSize: 18, lineHeight: '30px' }}>"{heard}"</p>
              </section>
            )}
            <section aria-label="Tip" className="stack" style={{ gap: 8 }}>
              <span className="label green">Ellis</span>
              <p className="lead">Answer the way you answered on your form, in a full sentence. If you don't understand a question, ask the officer to repeat it.</p>
            </section>
            <div className="btns">
              <button type="button" className="btn lg primary strong" disabled={mic} onClick={answerOutLoud}><Icon name="mic" color="#1e6b5b" />{mic ? 'Listening…' : heard ? 'Answer again out loud' : 'Answer out loud'}</button>
              <button type="button" className="btn lg" onClick={next}>Next question</button>
            </div>
          </>}

          {tab === 'civics' && <>
            <div className="label" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8 }}>
              {/* [VERIFY] "12 of 20" passing threshold and "20 questions" total against current USCIS civics test rules */}
              <span>Civics test · question {(n % civics.length) + 1} of {civics.length}</span>
              {score.asked > 0 && <span className="soft">This practice: {score.right} of {score.asked} · need 12 of 20 to pass</span>}
            </div>
            <h2 className="display">{c.q}</h2>
            <div className="btns">
              <button type="button" className="btn lg primary strong" disabled={mic} onClick={answerOutLoud}><Icon name="mic" color="#1e6b5b" />{mic ? 'Listening…' : 'Answer out loud'}</button>
              <button type="button" className="btn lg" onClick={() => setShowChoices(!showChoices)}>{showChoices ? 'Hide choices' : 'Show choices'}</button>
            </div>
            {showChoices && (
              <div role="radiogroup" aria-label="Answers" className="stack enter" style={{ gap: 10 }}>
                {c.answers.map((a, i) => {
                  const verdict = pick !== null && i === 0 ? 'right' : pick === i ? 'wrong' : ''
                  return (
                    <button key={a} type="button" role="radio" aria-checked={pick === i} className={`ans ${verdict}`} onClick={() => {
                      if (pick === null) setScore({ right: score.right + (i === 0 ? 1 : 0), asked: score.asked + 1 })
                      setPick(i)
                    }}>
                      <span style={{ flex: 1, textAlign: 'left' }}>{a}</span>
                      <span className="status">{verdict === 'right' ? 'Correct' : verdict && 'Not this one'}</span>
                    </button>
                  )
                })}
              </div>
            )}
            {pick !== null && (
              <p className="lead enter"><span className="label green">Ellis</span> · {c.why} At the real test there are no choices: you say the answer out loud.</p>
            )}
            {heard && <p className="lead enter"><span className="label">You said</span> · "{heard}"</p>}
            <div className="btns">
              <button type="button" className="btn lg primary" style={{ padding: '0 28px' }} onClick={next}>Next question</button>
            </div>
          </>}

          {tab === 'english' && <>
            <div className="label">English test · {writeMode ? 'writing' : 'reading'}</div>
            <p className="lead soft">{writeMode ? 'The officer will read one sentence out loud. Write it down.' : "The officer will ask you to read one sentence out loud. Read this one when you're ready."}</p>
            <div className="card" style={{ display: 'block', padding: '48px 32px', fontFamily: 'var(--serif)', fontSize: 44, lineHeight: '54px', textAlign: 'center' }}>
              {writeMode ? (
                <input aria-label="Write what you hear" className="input" autoComplete="off" placeholder="Write what you hear" value={writing} onChange={(e) => setWriting(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', height: 64, fontFamily: 'var(--serif)', fontSize: 28, textAlign: 'center' }} />
              ) : sentence}
            </div>
            {writeMode && writing && <strong className={same(writing, sentence) ? 'green' : 'soft'}>{same(writing, sentence) ? 'Correct' : 'Keep going'}</strong>}
            {!writeMode && heard && (
              <p className="lead enter">
                <span className="label">You said</span> · "<HighlightDiff heard={heard} target={sentence} />"
                {' '}<strong className={same(heard, sentence) ? 'green' : 'rust'}>{same(heard, sentence) ? 'Correct' : 'Try again'}</strong>
              </p>
            )}
            <div className="btns">
              <button type="button" className="btn lg primary" disabled={mic} onClick={() => { setWriteMode(false); answerOutLoud() }}><Icon name="mic" />{mic ? 'Listening…' : 'Read it out loud'}</button>
              <button type="button" className="btn lg strong" onClick={() => { setWriteMode(true); say(sentence) }}>{writeMode ? 'Hear it again' : 'Practice writing instead'}</button>
            </div>
          </>}
        </div>
      </main>
    </Shell>
  )
}
