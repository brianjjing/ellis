import { useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'
import { navigate } from './main'
import { api } from './api'
import { goSignIn } from './auth'

type Msg = { who: 'you' | 'ellis'; text: string }
// Module state: survives navigation, not a reload, and never touches storage or the server.
let guest: { msgs: Msg[]; answers: Record<string, unknown> } = { msgs: [], answers: {} }
export const guestSnapshot = () => ({ answers: guest.answers, transcript: guest.msgs })

const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

// The logged-out home: Chat's markup with Log in and Sign up in the bar.
export default function GuestChat() {
  const [msgs, setMsgs] = useState(guest.msgs)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async () => {
    const text = typed.trim()
    if (!text || busy) return
    const sent: Msg[] = [...msgs, { who: 'you', text }]
    setMsgs(sent)
    setTyped('')
    setBusy(true)
    try {
      const r = await api<{ reply: string; answers: Record<string, unknown> }>('/api/guest/chat', { body: { messages: sent, answers: guest.answers } })
      guest = { msgs: [...sent, { who: 'ellis', text: r.reply }], answers: r.answers }
    } catch {
      guest = { ...guest, msgs: [...sent, { who: 'ellis', text: 'Connection lost. Please try again.' }] }
    }
    setMsgs(guest.msgs)
    setBusy(false)
  }
  return (
    <Shell active="chat" guest>
      <main className="main chat">
        <header className="bar">
          <h1 className="h1">Chat with Ellis</h1>
          <div className="btns">
            <button type="button" className="btn" onClick={() => goSignIn('/')}>Log in</button>
            <button type="button" className="btn primary" onClick={() => navigate('/signup')}>Sign up</button>
          </div>
        </header>
        <div className="chat-body">
          <section aria-label="Conversation" className="convo">
            <div className="thread" aria-live="polite">
              <div className="msg" style={{ gap: 14 }}>
                <div className="label green">ELLIS</div>
                <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>{greeting()}. I help people get ready to apply for U.S. citizenship.</p>
                <p className="lead soft">Ask me anything about the process, or tell me a little about yourself and I'll check where you stand.</p>
              </div>
              {msgs.map((m, i) => m.who === 'you' ? (
                <div key={i} className="you"><div className="label">YOU</div><div className="bubble">{m.text}</div></div>
              ) : (
                <div key={i} className="msg">
                  <div className="label green">ELLIS</div>
                  <p className="lead">{m.text}</p>
                  <p className="small">Create a free account to save this conversation and start your N-400. <a href="/signup" data-nav className="link-btn" style={{ textDecoration: 'underline' }}>Sign up</a></p>
                </div>
              ))}
            </div>
            <div className="composer">
              <div>
                <form className="ask enter" onSubmit={(e) => { e.preventDefault(); send() }}>
                  <button type="button" aria-label="Log in to upload a document" className="icon-btn" onClick={() => goSignIn('/')}><Icon name="clip" size={20} /></button>
                  <label htmlFor="msg" className="sr-only">Message Ellis</label>
                  <input id="msg" type="text" autoComplete="off" placeholder="Ask anything, in any language" value={typed} onChange={(e) => setTyped(e.target.value)} />
                  <button type="button" aria-label="Log in to talk with Ellis" title="Log in to talk with Ellis" className="icon-btn" style={{ background: 'var(--green)', color: 'var(--white)' }} onClick={() => goSignIn('/')}>
                    <Icon name="mic" size={20} />
                  </button>
                </form>
              </div>
            </div>
          </section>
        </div>
      </main>
    </Shell>
  )
}
