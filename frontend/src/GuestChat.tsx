import { useEffect, useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'
import { navigate } from './main'
import { api } from './api'
import { goSignIn } from './auth'
import { GuideStart } from './applicant/Guide'
import { t, type Lang } from './applicant/i18n'

type Msg = { who: 'you' | 'ellis'; text: string }
// Module state: survives navigation, not a reload, and never touches storage or the server.
let guest: { msgs: Msg[]; answers: Record<string, unknown> } = { msgs: [], answers: {} }
let guestLang: Lang = 'en'
export const guestSnapshot = () => ({ answers: guest.answers, transcript: guest.msgs })

const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

// The logged-out home. Talking and uploads need an account.
export default function GuestChat() {
  const [msgs, setMsgs] = useState(guest.msgs)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [lang, setLang] = useState(guestLang)
  useEffect(() => { if (msgs.length) scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }) }, [msgs.length])
  const send = async (raw?: string) => {
    const text = (raw ?? typed).trim()
    if (!text || busy) return
    const sent: Msg[] = [...msgs, { who: 'you', text }]
    setMsgs(sent)
    setTyped('')
    setBusy(true)
    try {
      const r = await api<{ reply: string; answers: Record<string, unknown> }>('/api/guest/chat', {
        body: { messages: sent, answers: guest.answers, language: guestLang },
      })
      guest = { msgs: [...sent, { who: 'ellis', text: r.reply }], answers: r.answers }
    } catch {
      guest = { ...guest, msgs: [...sent, { who: 'ellis', text: 'Connection lost. Please try again.' }] }
    }
    setMsgs(guest.msgs)
    setBusy(false)
  }
  const pick = (code: string) => { guestLang = code.startsWith('es') ? 'es' : 'en'; setLang(guestLang) }
  return (
    <Shell active="chat" guest>
      <main className="main chat">
        <header className="bar">
          <h1 className="h1">{t(lang, 'chatWithEllis')}</h1>
          <div className="btns">
            <button type="button" className="btn" onClick={() => goSignIn('/')}>{t(lang, 'logIn')}</button>
            <button type="button" className="btn primary" onClick={() => navigate('/signup')}>{t(lang, 'signUp')}</button>
          </div>
        </header>
        <div className="chat-body">
          <section aria-label="Conversation" className="convo">
            <div className="thread" aria-live="polite">
              <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>{greeting()}. I help people get ready to apply for U.S. citizenship.</p>
              {msgs.length === 0 && <GuideStart lang={lang} onLocale={pick} onTalk={() => goSignIn('/')} onType={() => document.getElementById('msg')?.focus()} onChip={send} />}
              {msgs.map((m, i) => m.who === 'you' ? (
                <div key={i} className="you"><div className="label">{t(lang, 'you')}</div><div className="bubble">{m.text}</div></div>
              ) : (
                <div key={i} className="msg">
                  <div className="label green">{t(lang, 'ellis')}</div>
                  <p className="lead">{m.text}</p>
                  <p className="small">{t(lang, 'saveAccount')} <a href="/signup" data-nav className="link-btn">{t(lang, 'signUp')}</a></p>
                </div>
              ))}
            </div>
            <div className="composer">
              <div>
                <form className="ask" onSubmit={(e) => { e.preventDefault(); send() }}>
                  <span className="tools">
                    <button type="button" aria-label={t(lang, 'uploadDoc')} className="icon-btn" onClick={() => goSignIn('/')}><Icon name="clip" size={20} /></button>
                    <button type="button" className="btn" onClick={() => goSignIn('/')}>{t(lang, 'signInToTalk')}</button>
                  </span>
                  <label htmlFor="msg" className="sr-only">Message Ellis</label>
                  <input id="msg" type="text" autoComplete="off" placeholder="Ask anything, in any language" value={typed} onChange={(e) => setTyped(e.target.value)} />
                  <button type="submit" aria-label="Send" className="icon-btn" style={{ background: 'var(--ink)', color: 'var(--white)' }}><Icon name="send" size={20} /></button>
                </form>
              </div>
            </div>
          </section>
        </div>
      </main>
    </Shell>
  )
}
