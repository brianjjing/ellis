// A3 Session: talk, see captions, facts ("Lo que tenemos"), team activity and uploads.
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { Roadmap, type CaseView } from './ApplicantApp'
import { Lang, t } from './i18n'
import { VoiceClient, type Caption, type VoiceState } from './voice'

const CHIP_ICON: Record<string, string> = { document: '▢', spoken: '◔', confirmed: '✓', review: '!', corrected: '↺', deferred: '■' }

export default function Session({ data, reload, highlight, docStatus, onUpload, onEnd, wantVoice, lang, locale }: {
  data: CaseView; reload: () => void; highlight: Record<string, number>; docStatus: Record<string, string>
  onUpload: () => void; onEnd: () => void; wantVoice: boolean; lang: Lang; locale: string
}) {
  const [state, setState] = useState<VoiceState>('connecting')
  const [captions, setCaptions] = useState<Caption[]>([])
  const [partial, setPartial] = useState('')
  const [mode, setMode] = useState<'voice' | 'text' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [section, setSection] = useState<string | null>(null)
  const [official, setOfficial] = useState<{ es: string; en?: string } | null>(null)
  const [typed, setTyped] = useState('')
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [teamOpen, setTeamOpen] = useState(matchMedia('(min-width: 900px)').matches)
  const vc = useRef<VoiceClient | null>(null)

  useEffect(() => {
    const c = new VoiceClient({
      onState: setState,
      onCaption: (cap) => setCaptions((cs) => [...cs.slice(-2), cap]),
      onPartial: setPartial,
      onReady: (info) => {
        setMode(info.mode)
        if (info.voice_unavailable) setNotice(lang === 'en'
          ? "Ellis's voice isn't available right now. You can type your answers, or talk if your browser allows it."
          : 'La voz de Ellis no está disponible en este momento. Puede escribir sus respuestas, o hablar si su navegador lo permite.')
      },
      onLine: (l) => {
        if (l.kind === 'official_question') setOfficial({ es: l.text, en: l.meta?.text_en })
        else if (l.kind === 'question' || l.kind === 'readback') setOfficial(null)
        const f = l.meta?.field || l.field
        if (f) setSection(f)
        reload()
      },
      onEnd: () => { reload(); onEnd() },
      onError: (m) => {
        if (m === 'offline') setNotice(lang === 'en' ? 'Connection lost. What you said is saved.' : 'Se perdió la conexión. Lo que dijo está guardado.')
        else if (m === 'mic_denied') setNotice(lang === 'en' ? 'No microphone: you can type your answers.' : 'Sin micrófono: puede escribir sus respuestas.')
      },
    })
    vc.current = c
    c.start(wantVoice, lang, locale)
    return () => c.stop(false)
  }, [])

  const send = () => {
    const t = typed.trim()
    if (!t) return
    vc.current?.sendText(t)
    setTyped('')
  }

  const sectionLabel = section ? (data.facts.find((g: any) => g.items.some((i: any) => i.field === section))?.label ?? sectionName(section, lang)) : (lang === 'en' ? 'Conversation' : 'Conversación')
  const ring = { speaking: 'blue', listening: 'green', thinking: 'grey', connecting: 'grey', idle: 'grey', ended: 'grey' }[state]
  const otherLang: Lang = lang === 'en' ? 'es' : 'en'

  return (
    <div className="session">
      <div className="s-bar">
        <span className="s-section">{sectionLabel}</span>
        {!confirmEnd
          ? <button className="btn md" onClick={() => setConfirmEnd(true)}>{t(lang, 'endForToday')}</button>
          : <span className="btns"><span className="small">{t(lang, 'endConfirm')}</span>
            <button className="btn md primary" onClick={() => vc.current?.endCall()}>{t(lang, 'endYes')}</button>
            <button className="btn md" onClick={() => setConfirmEnd(false)}>{t(lang, 'endNo')}</button></span>}
      </div>
      {notice && <div className="panel warn" role="status">{notice}</div>}
      <div className="s-grid">
        <section className="s-talk" aria-label={lang === 'en' ? 'Conversation' : 'Conversación'}>
          <div className={`ring ${ring}`} aria-label={stateLabel(state, lang)} role="img">
            <Icon name={state === 'speaking' ? 'speaker' : 'mic'} size={40} />
          </div>
          <div className="s-state">{stateLabel(state, lang)}{mode === 'text' ? (lang === 'en' ? ' · text mode' : ' · modo texto') : ''}</div>
          {official && (
            <div className="official">
              <div className="label">{lang === 'en' ? 'OFFICIAL QUESTION' : 'PREGUNTA OFICIAL'}</div>
              <p className="lead">{official.es}</p>
              {official.en && <p className="small" lang={otherLang}>{official.en}</p>}
            </div>
          )}
          <div className="captions" aria-live="polite">
            {captions.map((c, i) => (
              <div key={i} className={`cap ${c.who}`}>
                <span className="label">{c.who === 'ellis' ? 'ELLIS' : (lang === 'en' ? 'YOU' : 'USTED')}</span>
                <p>{c.locked && <span title={lang === 'en' ? 'Please listen until it finishes' : 'Por favor escuche hasta el final'}><Icon name="lock" /> </span>}{c.text}</p>
                {c.locked && i === captions.length - 1 && state === 'speaking' && <span className="small">{lang === 'en' ? 'Please listen until it finishes' : 'Por favor escuche hasta el final'}</span>}
              </div>
            ))}
            {partial && <div className="cap usted partial"><span className="label">{lang === 'en' ? 'YOU' : 'USTED'}</span><p>{partial}…</p></div>}
          </div>
          <form className="ask" onSubmit={(e) => { e.preventDefault(); send() }}>
            <label htmlFor="typed" className="sr-only">{t(lang, 'typeInstead')}</label>
            <input id="typed" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t(lang, 'typeInstead')} autoComplete="off" />
            <button type="submit" className="icon-btn" aria-label={lang === 'en' ? 'Send' : 'Enviar'} style={{ background: 'var(--ink)', color: 'var(--white)' }}><Icon name="send" size={20} /></button>
          </form>
          <button className="btn lg strong" onClick={onUpload}><Icon name="upload" />{t(lang, 'uploadDoc')}</button>
          {Object.keys(docStatus).length > 0 && (
            <div className="docs-status">
              {Object.entries(docStatus).map(([id, st]) => (
                <span key={id} className={`doc-chip ${st}`}>{docStatusLabel(st, lang)}</span>
              ))}
            </div>
          )}
        </section>

        <aside className="s-side">
          <FactsPanel data={data} highlight={highlight} lang={lang} />
          <section className="team" aria-label={lang === 'en' ? 'Your team is working' : 'Su equipo está trabajando'}>
            <button className="team-head" onClick={() => setTeamOpen(!teamOpen)} aria-expanded={teamOpen}>
              <span className="h3">{lang === 'en' ? 'Your team is working' : 'Su equipo está trabajando'}</span><span className="soft">{teamOpen ? '−' : '+'}</span>
            </button>
            {teamOpen && (data.team.length === 0 ? <p className="small">{lang === 'en' ? 'Nothing yet.' : 'Todavía nada.'}</p> : data.team.map((t: any) => (
              <div key={t.id} className="team-card enter"><span className="label green">{t.label}</span><span>{t.text}</span></div>
            )))}
          </section>
        </aside>
      </div>
      <Roadmap data={data} />
    </div>
  )
}

function docStatusLabel(st: string, lang: Lang) {
  if (lang === 'en') {
    return st === 'extracting' ? 'Reviewing…' : st === 'ok' ? 'Ready ✓' : st === 'low' ? "The photo isn't clear. Can you take another?" : "We couldn't read it"
  }
  return st === 'extracting' ? 'Revisando…' : st === 'ok' ? 'Listo ✓' : st === 'low' ? 'La foto no se ve bien. ¿Puede tomar otra?' : 'No pudimos leerlo'
}

export function FactsPanel({ data, highlight, lang = 'es' }: { data: CaseView; highlight: Record<string, number>; lang?: Lang }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t) }, [])
  return (
    <section className="facts" aria-label={lang === 'en' ? 'What we have' : 'Lo que tenemos'}>
      <h2 className="h3">{t(lang, 'whatWeHave')}</h2>
      {data.facts.length === 0 && <p className="small">{lang === 'en' ? 'Your answers will appear here.' : 'Aquí aparecerán sus respuestas.'}</p>}
      {data.facts.map((g: any) => (
        <div key={g.section} className="f-group">
          <div className="label">{g.label.toUpperCase()}</div>
          {g.items.map((it: any) => {
            const fresh = highlight[it.field] && Date.now() - highlight[it.field] < 10000
            const chip = fresh ? { key: 'corrected', label: lang === 'en' ? 'Corrected' : 'Corregido' } : it.chip
            return (
              <div key={it.field} className={`f-card ${fresh ? 'flash' : ''}`}>
                <span className="f-label">{it.label}</span>
                <span className="f-value">
                  {fresh && it.corrected_from ? <><s>{it.corrected_from}</s> → </> : null}{it.value}
                  {it.days !== undefined && <span className="f-days"> · {fresh && it.days_from !== undefined ? <><s>{it.days_from}</s> → </> : null}{it.days} {lang === 'en' ? 'days' : 'días'}</span>}
                </span>
                <span className={`chip ${chip.key}`}><span aria-hidden="true">{CHIP_ICON[chip.key]} </span>{chip.label}{it.simulated ? (lang === 'en' ? ' · simulated' : ' · simulado') : ''}</span>
              </div>
            )
          })}
        </div>
      ))}
    </section>
  )
}

function stateLabel(s: VoiceState, lang: Lang) {
  if (lang === 'en') {
    return { speaking: 'Ellis is speaking', listening: "I'm listening", thinking: 'One moment…', connecting: 'Connecting…', idle: '', ended: 'Call ended' }[s]
  }
  return { speaking: 'Ellis está hablando', listening: 'Le escucho', thinking: 'Un momento…', connecting: 'Conectando…', idle: '', ended: 'Llamada terminada' }[s]
}

function sectionName(field: string, lang: Lang) {
  if (lang === 'en') {
    if (field.startsWith('trips')) return 'Time outside the US'
    if (field.startsWith('addresses')) return 'Addresses'
    if (field.startsWith('employment')) return 'Employment and school'
    if (field.startsWith('background')) return 'Background questions'
    if (field.startsWith('oath')) return 'Oath questions'
    if (field.startsWith('children')) return 'Children'
    if (field.startsWith('spouse') || field.startsWith('marital')) return 'Marital history'
    return 'Conversation'
  }
  if (field.startsWith('trips')) return 'Viajes fuera del país'
  if (field.startsWith('addresses')) return 'Domicilios'
  if (field.startsWith('employment')) return 'Trabajo y estudios'
  if (field.startsWith('background')) return 'Preguntas de antecedentes'
  if (field.startsWith('oath')) return 'Preguntas del juramento'
  if (field.startsWith('children')) return 'Hijos'
  if (field.startsWith('spouse') || field.startsWith('marital')) return 'Estado civil'
  return 'Conversación'
}
