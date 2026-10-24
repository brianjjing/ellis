// Applicant web client (/a/:token): phone-first, 48 px targets. Voice is the primary input; the screen
// shows what was heard, what was saved and what is still needed. Language (and dialect) is chosen on the
// first screen, before the applicant starts talking; it drives both the spoken conversation (backend) and
// this app's own chrome text (i18n.ts).
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, debounce, stream } from '../api'
import { Icon } from '../icons'
import { LANGUAGES, Lang, langOf, t } from './i18n'
import Session from './Session'
import { BiographicsSheet, ReferralCard, SecureEntrySheet, UploadSheet } from './Sheets'
import { PacketReady, ReviewSignoff } from './Review'

export type CaseView = any

export type Overlay =
  | { kind: 'secure'; field: string; label: string; type?: string }
  | { kind: 'upload'; documentType?: string }
  | { kind: 'biographics' }
  | null

export default function ApplicantApp({ token }: { token: string }) {
  const [data, setData] = useState<CaseView | null>(null)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)
  const [screen, setScreen] = useState<'language' | 'welcome' | 'explain' | 'mic' | 'session' | 'progress' | 'review' | 'packet'>('language')
  const [lang, setLang] = useState<Lang>('es')
  const [locale, setLocale] = useState('es-MX')
  const [wantVoice, setWantVoice] = useState(true)
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [cards, setCards] = useState<any[]>([])
  const [docStatus, setDocStatus] = useState<Record<string, string>>({})
  const [highlight, setHighlight] = useState<Record<string, number>>({})
  const prevFacts = useRef<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const d = await api('/api/a/case')
      // highlight corrections (purple chip, 10 s, old → new)
      const now = Date.now()
      const hl: Record<string, number> = {}
      for (const g of d.facts) for (const it of g.items) {
        const prev = prevFacts.current[it.field]
        if (prev !== undefined && prev !== it.value && it.corrected_from) hl[it.field] = now
        prevFacts.current[it.field] = it.value
      }
      if (Object.keys(hl).length) setHighlight((h) => ({ ...h, ...hl }))
      setData(d)
      return d
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return exchange()
      throw e
    }
  }, [])

  const exchange = useCallback(async () => {
    try {
      const d = await api('/api/a/session', { body: { token } })
      for (const g of d.facts) for (const it of g.items) prevFacts.current[it.field] = it.value
      setData(d)
      setError(null)
      return d
    } catch (e) {
      if (e instanceof ApiError) setError({ code: e.code, message: e.message })
      else setError({ code: 'offline', message: 'Se perdió la conexión. Lo que dijo está guardado.' })
    }
  }, [token])

  useEffect(() => {
    exchange().then((d) => {
      if (!d) return
      // Resume in whatever language the applicant already chose (persisted on the case), so a returning
      // session doesn't silently fall back to Spanish. The 'language' screen only shows on a brand-new case.
      if (d.language) {
        setLocale(d.language)
        setLang(d.language.startsWith('en') ? 'en' : 'es')
      }
      if (d.state === 'signed') setScreen('packet')
      else if (d.state === 'ready') setScreen('review')
      else if (d.state !== 'consent_pending') setScreen('progress')
    })
  }, [exchange])

  useEffect(() => {
    if (!data) return
    const refresh = debounce(() => load().catch(() => undefined), 250)
    return stream('/api/a/stream', (m) => {
      if (m.type === 'ping') return
      const p = m.payload || {}
      if (m.type === 'open_secure_entry') setOverlay({ kind: 'secure', field: p.field, label: p.label, type: p.type })
      else if (m.type === 'open_upload') setOverlay({ kind: 'upload', documentType: p.document_type })
      else if (m.type === 'open_biographics') setOverlay({ kind: 'biographics' })
      else if (m.type === 'referral_card') setCards((c) => [...c.filter((x) => x.flag_id !== p.flag_id), p])
      else if (m.type === 'document.status') setDocStatus((s) => ({ ...s, [p.document_id]: p.status === 'extracted' ? (p.quality === 'low' ? 'low' : 'ok') : p.status }))
      if (m.type === 'case.state_changed' && p.to === 'ready') setScreen((sc) => (sc === 'session' ? sc : 'review'))
      refresh()
    })
  }, [!!data, load])

  if (error) return <ErrorScreen error={error} retry={exchange} />
  if (!data) return <Loading />

  const dismissCard = (id: string) => setCards((c) => c.filter((x) => x.flag_id !== id))
  const notAboutMe = async (id: string) => {
    await api(`/api/a/flags/${id}/not_about_me`, { body: {} })
    dismissCard(id)
  }

  return (
    <div className="page col applicant" lang={lang}>
      <header className="a-head">
        <div className="stack">
          <span className="a-clinic">{t(lang, 'preparedFor')} {data.clinic.name}</span>
          {data.clinic.is_demo && <span className="demo-tag">{t(lang, 'demoData')}</span>}
        </div>
        <span className="wordmark">Ellis</span>
      </header>

      {screen === 'language' && <LanguageSelect onChoose={(l, lc) => {
        setLang(l); setLocale(lc); setScreen('welcome')
        api('/api/a/language', { body: { locale: lc } }).catch(() => undefined)
      }} />}
      {screen === 'welcome' && <Welcome data={data} lang={lang} onStart={() => setScreen('mic')} onExplain={() => setScreen('explain')} />}
      {screen === 'explain' && <Explainer lang={lang} onBack={() => setScreen('welcome')} />}
      {screen === 'mic' && <MicPrompt lang={lang} onGo={(voice) => { setWantVoice(voice); setScreen('session') }} />}
      {screen === 'session' && (
        <Session data={data} reload={load} highlight={highlight} docStatus={docStatus} wantVoice={wantVoice}
          lang={lang} locale={locale}
          onUpload={() => setOverlay({ kind: 'upload' })}
          onEnd={() => { load(); setScreen(data.state === 'ready' ? 'review' : 'progress') }} />
      )}
      {screen === 'progress' && <Progress data={data} onTalk={() => setScreen('mic')} onUpload={() => setOverlay({ kind: 'upload' })} reload={load}
        onReview={() => setScreen('review')} />}
      {screen === 'review' && <ReviewSignoff data={data} reload={load} onSigned={() => { load(); setScreen('packet') }} onBack={() => setScreen('progress')} />}
      {screen === 'packet' && <PacketReady data={data} />}

      {cards.length > 0 && (
        <div className="card-stack">
          {cards.slice(-1).map((c) => <ReferralCard key={c.flag_id} card={c} lang={lang} onOk={() => dismissCard(c.flag_id)} onNotMe={() => notAboutMe(c.flag_id)} />)}
        </div>
      )}
      {overlay?.kind === 'secure' && <SecureEntrySheet field={overlay.field} label={overlay.label} lang={lang} onClose={() => { setOverlay(null); load() }} />}
      {overlay?.kind === 'upload' && <UploadSheet initial={overlay.documentType} lang={lang} onClose={() => { setOverlay(null); load() }} onUploaded={(id) => setDocStatus((s) => ({ ...s, [id]: 'extracting' }))} />}
      {overlay?.kind === 'biographics' && <BiographicsSheet lang={lang} onClose={() => { setOverlay(null); load() }} />}
    </div>
  )
}

function ProfessionalOptions({ reload, lang }: { reload: () => void; lang: Lang }) {
  const [url, setUrl] = useState<string | null>(null)
  return (
    <section className="panel" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
      <strong>{lang === 'en' ? 'Part of your application is completed by a licensed professional.' : 'Una parte de su solicitud la completa un profesional con licencia.'}</strong>
      <span className="small">{lang === 'en' ? 'Once you have talked to your professional:' : 'Cuando ya haya hablado con su profesional:'}</span>
      <div className="btns">
        <button className="btn md" onClick={async () => setUrl((await api('/api/a/professional_draft', { body: {} })).url)}>{lang === 'en' ? 'Download a draft for my professional' : 'Descargar un borrador para mi profesional'}</button>
        <button className="btn md" onClick={async () => { await api('/api/a/representation', { body: { professional_files: true } }); reload() }}>{lang === 'en' ? 'My professional will file for me' : 'Mi profesional presentará por mí'}</button>
      </div>
      {url && <a className="btn md strong" href={url} target="_blank" rel="noreferrer">{lang === 'en' ? 'Open the draft' : 'Abrir el borrador'}</a>}
      <span className="small">{lang === 'en' ? "Ellis doesn't send anything to anyone." : 'Ellis no envía nada a nadie.'}</span>
    </section>
  )
}

function Loading() {
  return <div className="page col applicant"><main className="a-main"><p className="lead">Cargando… / Loading…</p></main></div>
}

function ErrorScreen({ error, retry }: { error: { code: string; message: string }; retry: () => void }) {
  return (
    <div className="page col applicant" lang="es">
      <main className="a-main">
        <h1 className="display">{error.code === 'link_expired' ? 'Este enlace ya venció' : 'No pudimos abrir su caso'}</h1>
        <p className="lead">{error.message}</p>
        {error.code === 'offline' && <button className="btn lg primary" onClick={retry}>Intentar otra vez</button>}
      </main>
    </div>
  )
}

function LanguageSelect({ onChoose }: { onChoose: (lang: Lang, locale: string) => void }) {
  const [picked, setPicked] = useState<Lang | null>(null)
  const group = LANGUAGES.find((l) => l.code === picked)
  return (
    <main className="a-main">
      <h1 className="display">Elija su idioma / Choose your language</h1>
      <p className="lead">Puede cambiarlo después. / You can change it later.</p>
      {!picked ? (
        <div className="btns" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 12 }}>
          {LANGUAGES.map((l) => (
            <button key={l.code} className="btn lg primary a-big" onClick={() => setPicked(l.code)}>{l.label}</button>
          ))}
        </div>
      ) : (
        <div className="btns" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 12 }}>
          <p className="small">{t(picked, 'chooseDialect')}</p>
          {group!.dialects.map((d) => (
            <button key={d.code} className="btn lg a-big" onClick={() => onChoose(picked, d.code)}>{d.label}</button>
          ))}
          <button className="link-btn" onClick={() => setPicked(null)}>{picked === 'es' ? 'Atrás' : 'Back'}</button>
        </div>
      )}
    </main>
  )
}

function Welcome({ data, lang, onStart, onExplain }: { data: CaseView; lang: Lang; onStart: () => void; onExplain: () => void }) {
  return (
    <main className="a-main">
      <h1 className="display">{t(lang, 'welcomeTitle')}</h1>
      <ul className="a-lines">
        <li>{t(lang, 'welcomeLine1')}</li>
        <li>{t(lang, 'welcomeLine2')}</li>
        <li>{t(lang, 'welcomeLine3')}</li>
      </ul>
      <button className="btn lg primary a-big" onClick={onStart}><Icon name="mic" size={20} />{t(lang, 'startTalking')}</button>
      <button className="link-btn" onClick={onExplain}>{t(lang, 'howItWorks')}</button>
      <Roadmap data={data} />
    </main>
  )
}

function Explainer({ lang, onBack }: { lang: Lang; onBack: () => void }) {
  const steps = lang === 'en' ? [
    ['1', 'We talk', 'I ask you the N-400 form questions, one at a time. You answer with your voice.'],
    ['2', 'Upload photos', 'You can take photos of your documents while we talk.'],
    ['3', 'Your clinic reviews', 'Someone at your clinic reviews what needs reviewing.'],
    ['4', 'You sign', 'You review every answer and sign. You or your clinic file the application.'],
  ] : [
    ['1', 'Hablamos', 'Le hago preguntas del formulario N-400, una a la vez. Usted contesta con su voz.'],
    ['2', 'Sube fotos', 'Puede tomar fotos de sus documentos mientras hablamos.'],
    ['3', 'Su clínica revisa', 'Una persona de su clínica revisa lo que hay que revisar.'],
    ['4', 'Usted firma', 'Revisa cada respuesta y firma. Usted o su clínica presentan la solicitud.'],
  ]
  return (
    <main className="a-main">
      <h1 className="display">{t(lang, 'howItWorks')}</h1>
      {steps.map(([n, title, desc]) => (
        <div key={n} className="row a-step"><span className="a-num">{n}</span><span className="stack"><strong>{title}</strong><span className="soft">{desc}</span></span></div>
      ))}
      <button className="btn lg" onClick={onBack}>{lang === 'en' ? 'Back' : 'Volver'}</button>
    </main>
  )
}

function MicPrompt({ lang, onGo }: { lang: Lang; onGo: (voice: boolean) => void }) {
  const [denied, setDenied] = useState(false)
  const ask = async () => {
    // ponytail: getUserMedia can hang forever (e.g. OS never shows the permission prompt) instead of
    // rejecting; without a timeout the applicant would be stuck on this screen with no way out.
    const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('mic_timeout')), 8000))
    try {
      const s = await Promise.race([navigator.mediaDevices.getUserMedia({ audio: true }), timeout])
      s.getTracks().forEach((t) => t.stop())
      onGo(true)
    } catch {
      setDenied(true)
    }
  }
  return (
    <main className="a-main">
      {!denied ? <>
        <h1 className="display">{t(lang, 'micTitle')}</h1>
        <p className="lead">{t(lang, 'micSub')}</p>
        <button className="btn lg primary a-big" onClick={ask}><Icon name="mic" size={20} />{t(lang, 'micContinue')}</button>
      </> : <>
        <h1 className="display">{t(lang, 'micDeniedTitle')}</h1>
        <p className="lead">{t(lang, 'micDeniedSub')}</p>
        <button className="btn lg primary a-big" onClick={ask}>{t(lang, 'micRetry')}</button>
        <button className="link-btn" onClick={() => onGo(false)}>{t(lang, 'micSkip')}</button>
      </>}
    </main>
  )
}

export function Roadmap({ data }: { data: CaseView }) {
  const lang = langOf(data)
  const [open, setOpen] = useState(false)
  const cur = data.roadmap.current
  return (
    <section className="roadmap" aria-label={lang === 'en' ? 'Stages' : 'Etapas'}>
      <button className="roadmap-dots" onClick={() => setOpen(!open)} aria-expanded={open}>
        {data.roadmap.stages.map((s: any, i: number) => (
          <span key={s.key} className={`rm-dot ${i < cur ? 'done' : i === cur ? 'cur' : ''}`}>
            <span aria-hidden="true" className="rm-mark">{i < cur ? '✓' : ''}</span>
            <span className="rm-label">{s.label}</span>
          </span>
        ))}
      </button>
      {open && (
        <ul className="rm-future">
          {data.roadmap.future.map((f: string) => <li key={f}>{f} · <span className="soft">{lang === 'en' ? 'Coming soon' : 'Próximamente'}</span></li>)}
        </ul>
      )}
    </section>
  )
}

function Progress({ data, onTalk, onUpload, onReview, reload }: { data: CaseView; onTalk: () => void; onUpload: () => void; onReview: () => void; reload: () => void }) {
  const lang = langOf(data)
  const icon: Record<string, string> = { done: '✓', partial: '◐', blocked: '■', not_started: '○' }
  const label = lang === 'en'
    ? { done: 'Done', partial: 'Partial', blocked: "With your professional", not_started: 'Missing' }
    : { done: 'Listo', partial: 'A medias', blocked: 'Con su profesional', not_started: 'Falta' }
  const decline = async (id: string) => { await api(`/api/a/gaps/${id}/decline`, { body: {} }); reload() }
  return (
    <main className="a-main">
      <h1 className="display">{lang === 'en' ? `Hi, ${data.first_name}.` : `Hola, ${data.first_name}.`}</h1>
      {data.case_blocked && <div className="panel warn">{lang === 'en' ? 'Your clinic will contact you.' : 'Su clínica le contactará.'}</div>}
      {data.state === 'ready' && (
        <div className="panel ok">
          <strong>{lang === 'en' ? 'Your clinic reviewed your case.' : 'Su clínica revisó su caso.'}</strong> {lang === 'en' ? 'Now review each answer yourself.' : 'Ahora revise usted cada respuesta.'}
          <button className="btn md primary" onClick={onReview}>{lang === 'en' ? 'Review and sign' : 'Revisar y firmar'}</button>
        </div>
      )}
      {data.reviewer_notes?.length > 0 && (
        <section className="panel">
          <div className="label">{lang === 'en' ? 'NOTES FROM YOUR CLINIC' : 'NOTAS DE SU CLÍNICA'}</div>
          {data.reviewer_notes.map((n: any) => <p key={n.id} className="lead">{n.label ? <strong>{n.label}: </strong> : null}{n.note}</p>)}
        </section>
      )}
      <button className="btn lg primary a-big" onClick={onTalk}><Icon name="mic" size={20} />{lang === 'en' ? 'Keep talking' : 'Seguir hablando'}</button>
      {data.referrals?.some((r: any) => r.variant === 'stop_now') && <ProfessionalOptions reload={reload} lang={lang} />}
      <section>
        <h2 className="h3 rule">{lang === 'en' ? 'Form sections' : 'Secciones del formulario'}</h2>
        {data.progress.map((p: any) => (
          <div key={p.section} className={`row prog ${p.state}`}>
            <span aria-hidden="true" className="prog-icon">{icon[p.state]}</span>
            <span className="grow">{p.label}</span>
            <span className="soft">{label[p.state as keyof typeof label]}</span>
          </div>
        ))}
      </section>
      <section>
        <h2 className="h3 rule">{lang === 'en' ? "What's missing" : 'Lo que falta'}</h2>
        {data.gaps.length === 0 ? <p className="soft">{lang === 'en' ? 'Nothing for now.' : 'Nada por ahora.'}</p> : data.gaps.map((g: any) => (
          <div key={g.id} className="row gap-row">
            <span className="grow">{g.label}</span>
            <button className="btn" onClick={onUpload}><Icon name="camera" />{lang === 'en' ? 'Upload' : 'Subir'}</button>
            <button className="btn" onClick={() => decline(g.id)}>{lang === 'en' ? "I don't have it" : 'No lo tengo'}</button>
          </div>
        ))}
      </section>
      <section className="panel">
        <span className="grow">{lang === 'en' ? "For your clinic's review" : 'Para revisión de su clínica'}</span>
        <strong className="count">{data.open_review_items}</strong>
      </section>
      <Roadmap data={data} />
    </main>
  )
}
