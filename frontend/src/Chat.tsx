import { useState } from 'react'
import Shell from './Shell'
import { Flag, Icon } from './icons'

const chats = [
  { title: 'Do short trips count?', meta: 'TODAY · CHAT' },
  { title: 'Which tax years do I need?', meta: 'OCT 21 · VOICE' },
  { title: 'A traffic ticket from 2019', meta: 'OCT 18 · CHAT' },
  { title: '¿Puedo hacer la entrevista en español?', meta: 'SEP 30 · VOICE' },
  { title: 'Reading my green card', meta: 'SEP 12 · CHAT' },
]

export default function Chat() {
  const [history, setHistory] = useState(false)
  const [voice, setVoice] = useState(false)
  const [approved, setApproved] = useState(false)
  const toggleHistory = () => setHistory(!history)

  return (
    <Shell active="chat">
      <main className="main chat">
        <header className="bar">
          <h1 className="h1">Do short trips count?</h1>
          <div className="btns">
            <button type="button" className="btn" aria-pressed={history} onClick={toggleHistory}>Past chats</button>
            <button type="button" className="btn">New chat</button>
          </div>
        </header>

        <div className="chat-body">
          <section aria-label="Conversation" className="convo">
            <div className="thread">
              <div className="msg" style={{ gap: 14 }}>
                <div className="label green">ELLIS</div>
                <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>Good morning, Maria. You can file in 11 days.</p>
                <div className="card" style={{ padding: 24, gap: 12 }}>
                  <div className="label rust" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span aria-hidden="true" className="diamond" />
                    YOUR NEXT STEP · ABOUT 10 MINUTES
                  </div>
                  <div style={{ fontSize: 20, lineHeight: '28px', fontWeight: 700 }}>Confirm your trips outside the U.S.</div>
                  <p className="lead soft">I found 4 trips in your passport. We can do it right here, or in the form.</p>
                  <div className="btns">
                    <button type="button" className="btn lg primary">Do it here</button>
                    <a href="#/form" className="btn lg strong">Open the form</a>
                  </div>
                </div>
              </div>

              <div className="you">
                <div className="label">YOU</div>
                <div className="bubble">I drove to Toronto for a long weekend in March. Do I have to list that?</div>
              </div>

              <div className="msg">
                <div className="label green">ELLIS</div>
                <p className="lead"><strong>Yes. List every trip longer than 24 hours.</strong> Short trips won't hurt you. They just need to be listed. I drafted it from your passport:</p>
                <div className="draft">
                  <div className="mono" style={{ fontSize: 12, fontWeight: 700 }}>ADD TO N-400 · PART 9 · TRIP 3</div>
                  <div style={{ fontSize: 20, lineHeight: '28px' }}><strong>Toronto, Canada</strong> · <span className="mono" style={{ fontSize: 16 }}>Mar 7 – Mar 10, 2025 · 3 days</span></div>
                  <div className="btns">
                    {approved ? (
                      <span className="enter green" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 44, fontSize: 15, fontWeight: 700 }}>
                        <Icon name="check" weight={2} />
                        Added to your form
                      </span>
                    ) : <>
                      <button type="button" className="btn md primary" style={{ padding: '0 20px' }} onClick={() => setApproved(true)}>Approve</button>
                      <button type="button" className="btn md">Change it</button>
                    </>}
                  </div>
                </div>
                <div className="small">Source: USCIS Form N-400 instructions, Part 9</div>
              </div>

              <div className="you">
                <div className="label">YOU · SPOKEN</div>
                <div className="bubble">And the long trip to Mexico when my mom was sick?</div>
              </div>

              <div className="msg">
                <div className="label green">ELLIS</div>
                <p className="lead">That trip was 217 days. A trip over 6 months can raise a question. Whether your proof is enough is a legal judgment I shouldn't make for you, so I've asked an attorney to look.</p>
                <a href="#/advanced" className="flag-link">
                  <Flag size={15} pole="#0e192b" />
                  <span className="mono">F-01</span> With an attorney
                </a>
              </div>
            </div>

            <div className="composer">
              <div>
                {voice ? (
                  <div className="voice enter">
                    <button type="button" aria-label="Stop listening" className="icon-btn" style={{ flex: '0 0 80px', height: 80, background: 'var(--green)', color: 'var(--white)' }} onClick={() => setVoice(false)}>
                      <Icon name="mic" size={34} />
                    </button>
                    <div className="stack" style={{ flex: '1 1 260px', gap: 6 }}>
                      <span className="label rust" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 9999, background: 'var(--rust)' }} />
                        LISTENING · ANY LANGUAGE
                      </span>
                      <span className="lead">Speak whenever you're ready. Tap the mic to stop.</span>
                    </div>
                    <button type="button" className="btn md" onClick={() => setVoice(false)}>Type instead</button>
                  </div>
                ) : <>
                  <div className="btns enter">
                    <button type="button" className="btn">What's my next step?</button>
                    <button type="button" className="btn">Practice my interview</button>
                    <button type="button" className="btn">Read a document for me</button>
                  </div>
                  <div className="ask enter">
                    <button type="button" aria-label="Upload a document" className="icon-btn"><Icon name="clip" size={20} /></button>
                    <label htmlFor="msg" className="sr-only">Message Ellis</label>
                    <input id="msg" type="text" placeholder="Ask anything, in any language" />
                    <button type="button" aria-label="Talk instead" className="icon-btn" style={{ background: 'var(--green)', color: 'var(--white)' }} onClick={() => setVoice(true)}>
                      <Icon name="mic" size={20} />
                    </button>
                    <button type="button" aria-label="Send" className="icon-btn" style={{ background: 'var(--ink)', color: 'var(--white)' }}>
                      <Icon name="send" size={20} />
                    </button>
                  </div>
                </>}
              </div>
            </div>
          </section>

          {history && (
            <aside aria-label="Past chats" className="history enter">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <h2 className="h3">Past chats</h2>
                <button type="button" className="btn" style={{ height: 36, padding: '0 12px' }} onClick={toggleHistory}>Close</button>
              </div>
              <label htmlFor="search" className="sr-only">Search past chats</label>
              <input id="search" type="search" placeholder="Search" className="input" style={{ height: 44, padding: '0 12px', fontSize: 15 }} />
              <div className="stack">
                {chats.map((c) => (
                  <a key={c.title} href="#/chat" className="past">
                    <span style={{ fontSize: 15, fontWeight: 700 }}>{c.title}</span>
                    <span className="mono soft" style={{ fontSize: 12 }}>{c.meta}</span>
                  </a>
                ))}
              </div>
            </aside>
          )}
        </div>
      </main>
    </Shell>
  )
}
