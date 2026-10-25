import { useEffect, useRef, useState } from 'react'
import Shell from './Shell'
import { Dots, Flag, Icon } from './icons'
import { daysToFile, useCase, type CaseView } from './applicant/ApplicantApp'
import { GuideFoot, GuideStart } from './applicant/Guide'
import { langOf, t } from './applicant/i18n'
import { VoiceClient, type VoiceState } from './applicant/voice'
import { api } from './api'

// A permission card: Ellis asked to do something only the applicant can approve (a setting, a question to the clinic).
type Perm = { id: string; kind: 'setting' | 'ask_clinic'; title: string; detail?: string | null; allowed?: boolean }
type Msg = { who: 'ellis' | 'you'; text: string; kind?: string; field?: string | null; en?: string; mt?: boolean; spoken?: boolean; approved?: boolean; perms?: Perm[]; flags?: { id: string; label: string }[] }
type Thread = { msgs: Msg[]; when: Date; voice: boolean }
// What Ellis says the applicant is doing now; the next-step bar shows it. Set by the agent, never computed here.
type Focus = { task: string; next_step?: string; link?: string; upload?: string }

// ponytail: chats live in memory only (they survive page changes, not a reload). Transcripts are never put in
// browser storage: a stop-now disclosure's words must not be written anywhere.
let live: Msg[] = []
let liveFocus: Focus | null = null
let soundOn = true // Ellis's voice on/off; survives page changes, starts on
const past: Thread[] = []

const titleOf = (t: Thread) => t.msgs.find((m) => m.who === 'you')?.text ?? 'Chat with Ellis'
const sectionOf = (data: CaseView, field?: string | null) =>
  field ? data.facts.find((g: any) => g.items.some((i: any) => i.field === field))?.label : undefined

const pageLabel: Record<string, string> = {
  '/form': 'Open the form', '/interview': 'Interview prep', '/reminders': 'Reminders', '/profile': 'My profile', '/review': 'Review and sign',
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

const VOICE_KEY = { connecting: 'connecting', listening: 'listening', thinking: 'thinking', speaking: 'ellisSpeaking', idle: 'paused', ended: 'voiceEnded' } as const

export default function Chat() {
  const { data, upload, reload } = useCase()
  const lang = langOf(data)
  const [msgs, setMsgs] = useState(live)
  const [focus, setFocus] = useState(liveFocus)
  const [since, setSince] = useState(0) // permission cards before this index belong to an ended session
  const [partial, setPartial] = useState('')
  const [voice, setVoice] = useState(true)
  const [state, setState] = useState<VoiceState>('connecting')
  const [notice, setNotice] = useState<string | null>(null)
  const [session, setSession] = useState(0)
  const [history, setHistory] = useState(false)
  const [search, setSearch] = useState('')
  const [viewing, setViewing] = useState<Thread | null>(null)
  const [typed, setTyped] = useState('')
  const [holding, setHolding] = useState(false) // the applicant's mic is open (not muted)
  const [consentLater, setConsentLater] = useState(false)
  const [started, setStarted] = useState(live.length > 0)
  const [sound, setSound] = useState(soundOn)
  const shownState = state === 'listening' && !holding ? 'idle' : state // "Listening" only while the mic is open
  const vc = useRef<VoiceClient | null>(null)
  const voiceRef = useRef(true)
  const queued = useRef<string | null>(null)
  const add = (m: Msg) => setMsgs((ms) => (live = [...ms, m]))
  const toggleHistory = () => setHistory(!history)

  const showConsent = !viewing && !data.consent_given
  const showGuide = !viewing && !!data.consent_given && !started && msgs.length === 0
  // The liaison waits until they leave the consent screen and the start screen. A chip can be typed before the socket opens.
  const composerOn = !showConsent && !showGuide

  // One liaison session per chat; only "New chat" starts a fresh one. Typing vs. talking shares it.
  useEffect(() => {
    if (!composerOn) return
    setNotice(null)
    setSince(live.length)
    const c: VoiceClient = new VoiceClient({
      // A stopped client still reports 'ended' when its socket finally closes; only the current one counts.
      onState: (s) => { if (vc.current === c) { setState(s); if (s !== 'listening') setHolding(false) } },
      onCaption: (cap) => { if (cap.who === 'usted') add({ who: 'you', text: cap.text, spoken: cap.spoken }) },
      onPartial: setPartial,
      onReady: (info) => {
        if (info.talk_unavailable) setMode(false)
        if (info.voice_unavailable) setNotice("Ellis's voice isn't available right now; replies show here as text.")
        else if (info.talk_unavailable) setNotice("Talking isn't available right now. You can type.")
        const q = queued.current
        if (q) { queued.current = null; c.sendText(q) }
      },
      onLine: (l) => {
        if (l.meta?.focus) setFocus((liveFocus = l.meta.focus))
        add({ who: 'ellis', text: l.text, kind: l.kind, field: l.meta?.field ?? l.field, en: l.meta?.text_en, mt: l.meta?.machine_translation, perms: l.meta?.permissions, flags: l.meta?.flags })
      },
      onEnd: () => undefined,
      onError: (m) => {
        if (m === 'mic_denied') setMode(false)
        setNotice(m === 'offline' ? 'Connection lost. What you said is saved.' : m === 'mic_denied' ? 'No microphone: you can type your answers.' : m)
      },
    })
    vc.current = c
    c.soundOn = soundOn
    c.voice = voiceRef.current
    // the disclosure is only said again on a fresh chat ("New chat" or a reload); the server knows if they agreed
    c.start(lang, data.language ?? 'en-US', live.some((m) => m.kind === 'disclosure'))
    return () => c.stop(false)
  }, [session, composerOn])

  // Newest message in view, like a coding agent's transcript. The page scrolls (the composer is sticky over
  // its bottom), so go to the page's end: scrolling an element at the thread's end into view tucks it behind
  // the composer, which read as jumping up.
  useEffect(() => { if (msgs.length) scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }) }, [msgs.length])

  const setMode = (v: boolean) => {
    voiceRef.current = v
    setVoice(v)
    setHolding(false)
    vc.current?.setVoice(v)
  }
  const tap = () => {
    const r = vc.current?.toggle()
    if (r === 'unavailable') setNotice(t(lang, 'micDeniedTitle'))
    setHolding(r === 'on')
  }
  const agree = async () => {
    await api('/api/a/consent', { body: { agree: true } })
    await reload()
  }
  const toggleSound = () => { setSound((soundOn = !sound)); vc.current?.setSound(soundOn) }

  const send = (text = typed.trim()) => {
    if (!text) return
    if (showGuide) { setMode(false); queued.current = text; setTyped(''); return setStarted(true) } // leaves the start screen; sent once the socket opens
    setViewing(null)
    if (state === 'ended') return setSession((s) => s + 1) // reconnect first; the typed text stays to send again
    if (vc.current?.ws?.readyState === WebSocket.OPEN) vc.current.sendText(text)
    else queued.current = text
    setTyped('')
  }
  const answer = (i: number, yes: boolean) => {
    if (yes) setMsgs((ms) => (live = ms.map((m, j) => (j === i ? { ...m, approved: true } : m))))
    send(yes ? (lang === 'en' ? 'Yes' : 'Sí') : 'No')
  }
  const decide = (i: number, id: string, allowed: boolean) => {
    setMsgs((ms) => (live = ms.map((m, j) => (j === i ? { ...m, perms: m.perms?.map((p) => (p.id === id ? { ...p, allowed } : p)) } : m))))
    vc.current?.permission(id, allowed)
  }
  const newChat = () => {
    if (live.length) past.unshift({ msgs: live, when: new Date(), voice })
    live = []
    liveFocus = null
    setFocus(null)
    setMsgs([])
    setViewing(null)
    queued.current = null
    setStarted(false)
    setMode(true)
    setSession((s) => s + 1)
  }

  const shown = viewing?.msgs ?? msgs
  // Same speaker twice in a row: one label over the run.
  const cont = (i: number) => i > 0 && shown[i - 1].who === shown[i].who
  const days = daysToFile(data)
  const canFile = data.filing_window ? (days ? ` Earliest filing: ${days} days away — your clinic will confirm.` : ' Your clinic will confirm when you are ready to file.') : ''
  const title = viewing ? titleOf(viewing) : sectionOf(data, [...msgs].reverse().find((m) => m.field)?.field) ?? 'Chat with Ellis'

  return (
    <Shell active="chat">
      <main className="main chat">
        <header className="bar">
          <h1 className="h1">{title}</h1>
          <div className="btns">
            <button type="button" className="btn round" aria-pressed={!sound} aria-label={sound ? "Mute Ellis's voice" : "Turn Ellis's voice on"} title={sound ? "Mute Ellis's voice" : "Turn Ellis's voice on"} onClick={toggleSound}>
              <Icon name={sound ? 'speaker' : 'speakerOff'} size={18} />
            </button>
            <button type="button" className="btn" aria-pressed={history} onClick={toggleHistory}>Past chats</button>
            <button type="button" className="btn" onClick={newChat}>New chat</button>
          </div>
        </header>

        <div className="chat-body">
          <section aria-label="Conversation" className={showGuide ? 'convo empty' : 'convo'}>
            <div className="thread" aria-live="polite">
              {/* the page's greeting, not something Ellis said */}
              {!viewing && <p className="lead" style={{ fontFamily: 'var(--serif)', fontSize: 32, lineHeight: '40px' }}>{greeting()}, {data.first_name}.{canFile}</p>}
              {showConsent && (
                <section className="panel" aria-label={t(lang, 'iAgree')}>
                  <p className="lead">{data.disclosure}</p>
                  {consentLater ? <p>{t(lang, 'consentLater')}</p> : (
                    <div className="btns">
                      <button type="button" className="btn lg primary" onClick={agree}>{t(lang, 'iAgree')}</button>
                      <button type="button" className="btn" onClick={() => setConsentLater(true)}>{t(lang, 'notNow')}</button>
                    </div>
                  )}
                </section>
              )}

              {shown.map((m, i) => m.who === 'you' ? (
                <div key={i} className={`you${cont(i) ? ' cont' : ''}`}>
                  {!cont(i) && <div className="label">{m.spoken ? `${t(lang, 'you')} · spoken` : t(lang, 'you')}</div>}
                  <div className="bubble" dir="auto">{m.text}</div>
                </div>
              ) : m.kind?.startsWith('readback') ? (
                <div key={i} className={`msg${cont(i) ? ' cont' : ''}`}>
                  {!cont(i) && <div className="label green">{t(lang, 'ellis')}</div>}
                  <div className="draft">
                    <div className="label" style={{ fontSize: 12 }}>Add to N-400{sectionOf(data, m.field) ? ` · ${sectionOf(data, m.field)}` : ''}</div>
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
                <div key={i} className={`msg${cont(i) && m.kind !== 'official_question' ? ' cont' : ''}`}>
                  {(!cont(i) || m.kind === 'official_question') && <div className="label green">{m.kind === 'official_question' ? `${t(lang, 'ellis')} · Official N-400 question` : t(lang, 'ellis')}</div>}
                  <p className="lead" dir="auto">{m.text}</p>
                  {m.en && <div className="small" lang={m.mt ? 'en' : lang === 'en' ? 'es' : 'en'}>{m.mt && <span className="soft">{lang === 'es' ? 'Traducción automática, todavía sin revisar. En inglés: ' : 'Machine translation, not yet reviewed. In English: '}</span>}{m.en}</div>}
                  {m.perms?.map((p) => (
                    <div key={p.id} className="perm" role="group" aria-label="Ellis needs your OK">
                      <div className="perm-head label">
                        <Icon name={p.kind === 'ask_clinic' ? 'send' : 'lock'} />
                        {p.kind === 'ask_clinic' ? 'Send to your clinic' : 'Change a setting'} · needs your OK
                      </div>
                      <div className="perm-body">
                        <div style={{ fontWeight: 700 }}>{p.title}</div>
                        {p.detail && <blockquote className="perm-quote">{p.detail}</blockquote>}
                        {p.kind === 'ask_clinic' && <span className="small">A person at {data.clinic.name} answers it. Ellis can't give legal advice.</span>}
                      </div>
                      <div className="perm-foot">
                        {p.allowed !== undefined ? (
                          <span className={`status ${p.allowed ? 'green' : 'soft'}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                            {p.allowed && <Icon name="check" weight={2} />}{p.allowed ? (p.kind === 'ask_clinic' ? 'Sent' : 'Allowed') : 'Not allowed'}
                          </span>
                        ) : viewing || i < since ? (
                          <span className="small">This request ended with the chat. Ask Ellis again.</span>
                        ) : <>
                          <button type="button" className="btn md" onClick={() => decide(i, p.id, false)}>Don't allow</button>
                          <button type="button" className="btn md primary" onClick={() => decide(i, p.id, true)}>{p.kind === 'ask_clinic' ? 'Send it' : 'Allow'}</button>
                        </>}
                      </div>
                    </div>
                  ))}
                  {/* in the margin beside this reply: what it sent to the clinic (inline when there's no margin) */}
                  {m.flags?.length ? (
                    <div className="margin-notes">
                      {m.flags.map((f) => (
                        <a key={f.id} href="/profile?tab=flags" data-nav className="margin-note">
                          <span className="label" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Flag size={13} pole="#0e192b" />Clinic will check</span>
                          <strong>{f.label}</strong>
                          <span className="soft">Nothing is decided yet.</span>
                        </a>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
              {/* Ellis's pending turn. No dots while speaking: the line's text is already shown. Screen readers get the state from the status line below. */}
              {!viewing && composerOn && (state === 'connecting' || state === 'thinking' || (voice && shownState === 'listening')) && (
                <div className={`msg${shown.at(-1)?.who === 'ellis' ? ' cont' : ''}`} aria-hidden="true">
                  {shown.at(-1)?.who !== 'ellis' && <div className="label green">{t(lang, 'ellis')}</div>}
                  {shownState === 'listening' ? <p className="lead soft">{t(lang, 'listening').replace(/…$/, '')}<Dots sm /></p> : <Dots />}
                </div>
              )}
            </div>

            {!showConsent && <div className="composer">
              <div>
                {notice && <p className="small rust" role="status">{notice}</p>}
                {focus?.next_step && !viewing && (
                  <div id="next" className="next-bar enter">
                    <span className="label rust" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <span aria-hidden="true" className="diamond" />NEXT STEP
                    </span>
                    <span className="next-title">{focus.next_step}</span>
                    {(focus.upload || focus.link) && (
                      <div className="btns">
                        {focus.upload && <button type="button" className="btn primary" onClick={() => upload(focus.upload)}><Icon name="camera" />Upload it</button>}
                        {focus.link && <a href={focus.link} data-nav className="btn strong">{pageLabel[focus.link] ?? 'Open'}</a>}
                      </div>
                    )}
                  </div>
                )}
                {/* the box shows the state; this keeps it announced to screen readers */}
                {!showGuide && <p className="sr-only" aria-live="polite">{voice ? t(lang, VOICE_KEY[shownState]) : t(lang, 'paused')}</p>}
                <form className="ask" onSubmit={(e) => { e.preventDefault(); send() }}>
                  <span className="tools">
                    <button type="button" aria-label={t(lang, 'uploadDoc')} className="icon-btn" onClick={() => upload()}><Icon name="clip" size={20} /></button>
                    <button type="button" aria-label={voice ? t(lang, 'typeWord') : t(lang, 'talk')} title={voice ? t(lang, 'typeWord') : t(lang, 'talk')} className="icon-btn" onClick={() => setMode(!voice)}><Icon name={voice ? 'keyboard' : 'talk'} size={20} /></button>
                  </span>
                  <label htmlFor="msg" className="sr-only">{voice ? t(lang, 'listening') : 'Message Ellis'}</label>
                  <input id="msg" type="text" autoComplete="off" readOnly={voice} value={voice ? partial : typed} onChange={(e) => setTyped(e.target.value)}
                    placeholder={!voice ? 'Ask anything, in any language' : showGuide || shownState === 'idle' ? t(lang, 'micHint') : t(lang, VOICE_KEY[shownState])} />
                  {voice ? (
                    // On the start screen the first tap starts the voice session, like "Start talking" did; after that it toggles the mic.
                    <button type="button" aria-label={holding || state === 'speaking' ? t(lang, 'stop') : t(lang, 'talk')} aria-pressed={holding}
                      className={`icon-btn mic${holding || state === 'speaking' ? ' pulse' : ''}`}
                      onClick={showGuide ? () => setStarted(true) : tap}>
                      <Icon name={holding ? 'mic' : 'micOff'} size={22} />
                    </button>
                  ) : (
                    <button type="submit" aria-label="Send" className="icon-btn" style={{ background: 'var(--ink)', color: 'var(--white)' }}><Icon name="send" size={20} /></button>
                  )}
                </form>
                {showGuide ? <GuideStart lang={lang} onChip={send} /> : (
                  <div className="btns suggest">
                    <button type="button" className="btn" onClick={() => send("What's my next step?")}>What's my next step?</button>
                    <button type="button" className="btn" onClick={() => send('I want to practice my interview')}>Practice my interview</button>
                    <button type="button" className="btn" onClick={() => upload()}>Read a document for me</button>
                  </div>
                )}
              </div>
            </div>}
            {showGuide && <GuideFoot lang={lang} locale={data.language} onLocale={async (code) => { await api('/api/a/language', { body: { locale: code } }); await reload() }} />}
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
