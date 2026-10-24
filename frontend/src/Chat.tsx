import { useEffect, useRef, useState } from 'react'
import Shell from './Shell'
import { Flag, Icon } from './icons'
import { daysToFile, useCase, type CaseView } from './applicant/ApplicantApp'
import { langOf } from './applicant/i18n'
import { VoiceClient, type VoiceState } from './applicant/voice'

type Msg = { who: 'ellis' | 'you'; text: string; kind?: string; field?: string | null; locked?: boolean; en?: string; spoken?: boolean; approved?: boolean }
type Thread = { msgs: Msg[]; when: Date; voice: boolean }

// ponytail: chats live in memory only (they survive page changes, not a reload). Transcripts are never put in
// browser storage: a stop-now disclosure's words must not be written anywhere.
let live: Msg[] = []
const past: Thread[] = []

const titleOf = (t: Thread) => t.msgs.find((m) => m.who === 'you')?.text ?? 'Chat with Ellis'
const sectionOf = (data: CaseView, field?: string | null) =>
  field ? data.facts.find((g: any) => g.items.some((i: any) => i.field === field))?.label : undefined

const voiceLabel: Record<VoiceState, string> = {
  listening: 'LISTENING · ANY LANGUAGE', idle: 'LISTENING · ANY LANGUAGE', speaking: 'ELLIS IS SPEAKING',
  thinking: 'ONE MOMENT', connecting: 'CONNECTING', ended: 'CONVERSATION ENDED',
}

// The one thing to do next, from the case: sign, upload what's missing, or keep answering.
function nextStep(data: CaseView) {
  if (data.case_blocked) return { title: 'Your clinic will contact you', note: 'A person at your clinic needs to look at your case first.' }
  if (data.state === 'signed' || data.state === 'referred_out') return { title: 'Your packet is ready', note: 'Download it, then you or your clinic file the application.', go: '/review', label: 'Open my packet' }
  if (data.state === 'ready') return { title: 'Review and sign your answers', note: 'Your clinic reviewed your case. Now check each answer yourself.', go: '/review', label: 'Review and sign' }
  if (data.gaps.length) return { title: `Upload: ${data.gaps[0].label}`, note: 'Take a photo of it. You can keep talking while I read it.', upload: data.gaps[0].document_type }
  const sec = data.progress.find((p: any) => p.state !== 'done')
  if (!sec) return { title: 'Your clinic is reviewing your answers', note: "You've answered everything. When it's your turn to sign, this card changes." }
  // ponytail: ~30 s per unanswered field is a guess; replace with measured pace if anyone needs it exact.
  return { title: `Answer the questions about ${sec.label.toLowerCase()}`, note: `${sec.done} of ${sec.total} confirmed so far. We can do it right here, or in the form.`, minutes: Math.max(1, Math.ceil((sec.total - sec.done) / 2)) }
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function Chat() {
  const { data, upload } = useCase()
  const lang = langOf(data)
  const [msgs, setMsgs] = useState(live)
  const [partial, setPartial] = useState('')
  const [voice, setVoice] = useState(true)
  const [state, setState] = useState<VoiceState>('connecting')
  const [notice, setNotice] = useState<string | null>(null)
  const [session, setSession] = useState(0)
  const [history, setHistory] = useState(false)
  const [search, setSearch] = useState('')
  const [viewing, setViewing] = useState<Thread | null>(null)
  const [typed, setTyped] = useState('')
  const vc = useRef<VoiceClient | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const add = (m: Msg) => setMsgs((ms) => (live = [...ms, m]))
  const toggleHistory = () => setHistory(!history)

  // One liaison session per mount; switching voice on/off or "New chat" starts a fresh one.
  useEffect(() => {
    setNotice(null)
    const c: VoiceClient = new VoiceClient({
      // A stopped client still reports 'ended' when its socket finally closes; only the current one counts.
      onState: (s) => { if (vc.current === c) setState(s) },
      onCaption: (cap) => { if (cap.who === 'usted') add({ who: 'you', text: cap.text, spoken: voice }) },
      onPartial: setPartial,
      onReady: (info) => {
        if (info.voice_unavailable) setNotice("Ellis's voice isn't available right now. You can type, or talk if your browser allows it.")
      },
      onLine: (l) => add({ who: 'ellis', text: l.text, kind: l.kind, field: l.meta?.field ?? l.field, locked: l.locked, en: l.meta?.text_en }),
      onEnd: () => undefined,
      onError: (m) => setNotice(m === 'offline' ? 'Connection lost. What you said is saved.' : m === 'mic_denied' ? 'No microphone: you can type your answers.' : m),
    })
    vc.current = c
    c.start(voice, lang, data.language ?? 'en-US')
    return () => c.stop(false)
  }, [voice, session])

  useEffect(() => { if (msgs.length) end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }) }, [msgs.length, partial])

  const send = (text = typed.trim()) => {
    if (!text) return
    setViewing(null)
    if (state === 'ended') return setSession((s) => s + 1) // reconnect first; the typed text stays to send again
    vc.current?.sendText(text)
    setTyped('')
  }
  const answer = (i: number, yes: boolean) => {
    if (yes) setMsgs((ms) => (live = ms.map((m, j) => (j === i ? { ...m, approved: true } : m))))
    send(yes ? (lang === 'en' ? 'Yes' : 'Sí') : 'No')
  }
  const newChat = () => {
    if (live.length) past.unshift({ msgs: live, when: new Date(), voice })
    live = []
    setMsgs([])
    setViewing(null)
    setSession((s) => s + 1)
  }

  const shown = viewing?.msgs ?? msgs
  const step = nextStep(data)
  const days = daysToFile(data)
  const canFile = data.filing_window ? (days ? ` You can file in ${days} days.` : ' You can file now.') : ''
  const title = viewing ? titleOf(viewing) : sectionOf(data, [...msgs].reverse().find((m) => m.field)?.field) ?? 'Chat with Ellis'
  const flags = data.referrals.length

  return (
    <Shell active="chat">
      <main className="main chat">
        <header className="bar">
          <h1 className="h1">{title}</h1>
          <div className="btns">
            <button type="button" className="btn" aria-pressed={history} onClick={toggleHistory}>Past chats</button>
            <button type="button" className="btn" onClick={newChat}>New chat</button>
          </div>
        </header>

        <div className="chat-body">
          <section aria-label="Conversation" className="convo">
            <div className="thread" aria-live="polite">
              {!viewing && (
                <div className="msg" style={{ gap: 14 }}>
                  <div className="label green">ELLIS</div>
                  <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>{greeting()}, {data.first_name}.{canFile}</p>
                  {step && (
                    <div id="next" className="card" style={{ padding: 24, gap: 12 }}>
                      <div className="label rust" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span aria-hidden="true" className="diamond" />
                        YOUR NEXT STEP{step.minutes ? ` · ABOUT ${step.minutes} MINUTE${step.minutes > 1 ? 'S' : ''}` : ''}
                      </div>
                      <div style={{ fontSize: 20, lineHeight: '28px', fontWeight: 700 }}>{step.title}</div>
                      <p className="lead soft">{step.note}</p>
                      {step.go ? (
                        <div className="btns"><a href={step.go} data-nav className="btn lg primary">{step.label}</a></div>
                      ) : step.upload ? (
                        <div className="btns">
                          <button type="button" className="btn lg primary" onClick={() => upload(step.upload)}><Icon name="camera" />Upload it</button>
                          <a href="/form" data-nav className="btn lg strong">Open the form</a>
                        </div>
                      ) : step.minutes ? (
                        <div className="btns">
                          <button type="button" className="btn lg primary" onClick={() => document.getElementById('msg')?.focus()}>Do it here</button>
                          <a href="/form" data-nav className="btn lg strong">Open the form</a>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              )}

              {shown.map((m, i) => m.who === 'you' ? (
                <div key={i} className="you">
                  <div className="label">{m.spoken ? 'YOU · SPOKEN' : 'YOU'}</div>
                  <div className="bubble">{m.text}</div>
                </div>
              ) : m.kind?.startsWith('readback') ? (
                <div key={i} className="msg">
                  <div className="label green">ELLIS</div>
                  <div className="draft">
                    <div className="mono" style={{ fontSize: 12, fontWeight: 700 }}>ADD TO N-400{sectionOf(data, m.field) ? ` · ${sectionOf(data, m.field).toUpperCase()}` : ''}</div>
                    <div style={{ fontSize: 20, lineHeight: '28px' }}>{m.text}</div>
                    <div className="btns">
                      {m.approved ? (
                        <span className="enter green" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 44, fontSize: 15, fontWeight: 700 }}>
                          <Icon name="check" weight={2} />
                          Added to your form
                        </span>
                      ) : !viewing && i === shown.length - 1 && <>
                        <button type="button" className="btn md primary" style={{ padding: '0 20px' }} onClick={() => answer(i, true)}>Approve</button>
                        <button type="button" className="btn md" onClick={() => answer(i, false)}>Change it</button>
                      </>}
                    </div>
                  </div>
                </div>
              ) : (
                <div key={i} className="msg">
                  <div className="label green">{m.kind === 'official_question' ? 'ELLIS · OFFICIAL N-400 QUESTION' : 'ELLIS'}</div>
                  <p className="lead">{m.locked && <Icon name="lock" />} {m.text}</p>
                  {m.en && <div className="small" lang={lang === 'en' ? 'es' : 'en'}>{m.en}</div>}
                  {m.kind?.startsWith('flag') && flags > 0 && (
                    <a href="/profile?tab=flags" data-nav className="flag-link">
                      <Flag size={15} pole="#0e192b" />
                      <span className="mono">F-{String(flags).padStart(2, '0')}</span> With your clinic
                    </a>
                  )}
                </div>
              ))}
              {partial && !viewing && (
                <div className="you" style={{ opacity: 0.7 }}>
                  <div className="label">YOU · SPOKEN</div>
                  <div className="bubble">{partial}…</div>
                </div>
              )}
              <div ref={end} />
            </div>

            <div className="composer">
              <div>
                {notice && <p className="small rust" role="status">{notice}</p>}
                {voice ? (
                  <div className="voice enter">
                    <button type="button" aria-label="Stop listening" className="icon-btn" style={{ flex: '0 0 80px', height: 80, background: 'var(--green)', color: 'var(--white)' }} onClick={() => setVoice(false)}>
                      <Icon name="mic" size={34} />
                    </button>
                    <div className="stack" style={{ flex: '1 1 260px', gap: 6 }}>
                      <span className="label rust" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 9999, background: 'var(--rust)' }} />
                        {voiceLabel[state]}
                      </span>
                      <span className="lead">Speak whenever you're ready. Tap the mic to stop.</span>
                    </div>
                    <button type="button" className="btn md" onClick={() => setVoice(false)}>Type instead</button>
                  </div>
                ) : <>
                  <div className="btns enter">
                    <button type="button" className="btn" onClick={() => { setViewing(null); setTimeout(() => document.getElementById('next')?.scrollIntoView({ behavior: 'smooth', block: 'center' })) }}>What's my next step?</button>
                    <a href="/interview" data-nav className="btn">Practice my interview</a>
                    <button type="button" className="btn" onClick={() => upload()}>Read a document for me</button>
                  </div>
                  <form className="ask enter" onSubmit={(e) => { e.preventDefault(); send() }}>
                    <button type="button" aria-label="Upload a document" className="icon-btn" onClick={() => upload()}><Icon name="clip" size={20} /></button>
                    <label htmlFor="msg" className="sr-only">Message Ellis</label>
                    <input id="msg" type="text" autoComplete="off" placeholder="Ask anything, in any language" value={typed} onChange={(e) => setTyped(e.target.value)} />
                    <button type="button" aria-label="Talk instead" className="icon-btn" style={{ background: 'var(--green)', color: 'var(--white)' }} onClick={() => setVoice(true)}>
                      <Icon name="mic" size={20} />
                    </button>
                    <button type="submit" aria-label="Send" className="icon-btn" style={{ background: 'var(--ink)', color: 'var(--white)' }}>
                      <Icon name="send" size={20} />
                    </button>
                  </form>
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
              <input id="search" type="search" placeholder="Search" className="input" style={{ height: 44, padding: '0 12px', fontSize: 15 }} value={search} onChange={(e) => setSearch(e.target.value)} />
              <div className="stack">
                {past.length === 0 && <p className="small">Chats you finish with "New chat" show up here until you close this tab.</p>}
                {past.filter((t) => titleOf(t).toLowerCase().includes(search.toLowerCase())).map((t) => (
                  <button key={t.when.getTime()} type="button" className="past" style={{ border: 0, borderBottom: '1px solid var(--line)', background: 'none', textAlign: 'left', cursor: 'pointer' }} onClick={() => setViewing(t)}>
                    <span style={{ fontSize: 15, fontWeight: 700 }}>{titleOf(t)}</span>
                    <span className="mono soft" style={{ fontSize: 12 }}>
                      {t.when.toDateString() === new Date().toDateString() ? 'TODAY' : t.when.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toUpperCase()} · {t.voice ? 'VOICE' : 'CHAT'}
                    </span>
                  </button>
                ))}
              </div>
            </aside>
          )}
        </div>
      </main>
    </Shell>
  )
}
