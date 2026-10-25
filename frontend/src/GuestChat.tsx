import { useEffect, useState } from 'react'
import Shell from './Shell'
import { Dots, Icon } from './icons'
import { navigate } from './main'
import { api } from './api'
import { goSignIn } from './auth'
import { GuideFoot, GuideStart } from './applicant/Guide'
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
  const [voice, setVoice] = useState(false) // talking needs an account, so the guest box starts in text mode
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
  const empty = msgs.length === 0
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
          {/* Empty: CSS centers the greeting and box, like other chat home pages. Same DOM either way, so the input keeps focus on first send. */}
          <section aria-label="Conversation" className={empty ? 'convo empty' : 'convo'}>
            <div className="thread" aria-live="polite">
              <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>{greeting()}. I help people get ready to apply for U.S. citizenship.</p>
              {msgs.map((m, i) => m.who === 'you' ? (
                <div key={i} className="you"><div className="label">{t(lang, 'you')}</div><div className="bubble">{m.text}</div></div>
              ) : (
                <div key={i} className="msg">
                  <div className="label green">{t(lang, 'ellis')}</div>
                  <p className="lead">{m.text}</p>
                  {msgs.findIndex(x => x.who === 'ellis') === i && (
                    <p className="small">{t(lang, 'saveAccount')} <a href="/signup" data-nav className="link-btn">{t(lang, 'signUp')}</a></p>
                  )}
                </div>
              ))}
              {busy && <div className="msg" aria-hidden="true"><div className="label green">{t(lang, 'ellis')}</div><Dots /></div>}
            </div>
            <div className="composer">
              <div>
                <form className="ask" onSubmit={(e) => { e.preventDefault(); send() }}>
                  <span className="tools">
                    <button type="button" aria-label={t(lang, 'uploadDoc')} className="icon-btn" onClick={() => goSignIn('/')}><Icon name="clip" size={20} /></button>
                    <button type="button" aria-label={voice ? t(lang, 'typeWord') : t(lang, 'talk')} title={voice ? t(lang, 'typeWord') : t(lang, 'talk')} className="icon-btn" onClick={() => setVoice(!voice)}><Icon name={voice ? 'keyboard' : 'talk'} size={20} /></button>
                  </span>
                  <label htmlFor="msg" className="sr-only">Message Ellis</label>
                  <input id="msg" type="text" autoComplete="off" readOnly={voice} placeholder={voice ? t(lang, 'micHint') : 'Ask anything, in any language'} value={voice ? '' : typed} onChange={(e) => setTyped(e.target.value)} />
                  {voice ? (
                    <button type="button" aria-label={t(lang, 'signInToTalk')} title={t(lang, 'signInToTalk')} className="icon-btn mic" onClick={() => goSignIn('/')}><Icon name="mic" size={22} /></button>
                  ) : (
                    <button type="submit" aria-label="Send" className="icon-btn" style={{ background: 'var(--ink)', color: 'var(--white)' }}><Icon name="send" size={20} /></button>
                  )}
                </form>
                {empty && <GuideStart lang={lang} onChip={send} />}
              </div>
            </div>
            {empty && <GuideFoot lang={lang} onLocale={pick} />}
          </section>
        </div>
      </main>
    </Shell>
  )
}
