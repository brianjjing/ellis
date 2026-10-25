// Applicant client root: loads the signed-in applicant's case (cookie from /a/:token), keeps it live over
// /api/a/stream, and hosts what the liaison opens (secure entry, upload, biographics, referral cards) on
// whichever page the applicant is on. Pages read the case with useCase().
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, debounce, stream } from '../api'
import { navigate } from '../main'
import { langOf } from './i18n'
import { BiographicsSheet, ReferralCard, SecureEntrySheet, UploadSheet } from './Sheets'

export type CaseView = any

type Overlay =
  | { kind: 'secure'; field: string; label: string }
  | { kind: 'upload'; documentType?: string }
  | { kind: 'biographics' }
  | null

type Ctx = { data: CaseView; reload: () => Promise<CaseView>; upload: (documentType?: string) => void }
const CaseCtx = createContext<Ctx>(null!)
export const useCase = () => useContext(CaseCtx)

// Current value of a case fact, e.g. fact(data, 'name.family').
export const fact = (data: CaseView, field: string): string | undefined =>
  data.facts.flatMap((g: any) => g.items).find((i: any) => i.field === field)?.value

// Days until the applicant can file; 0 once the window is open or before the rules engine has a date.
export function daysToFile(data: CaseView) {
  const f = data.filing_window
  if (!f || f.window_open) return 0
  return Math.max(1, Math.ceil((Date.parse(f.earliest_filing) - Date.now()) / 864e5))
}

export default function ApplicantApp({ children }: { children: ReactNode }) {
  const [data, setData] = useState<CaseView | null>(null)
  const [failed, setFailed] = useState(false)
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [cards, setCards] = useState<any[]>([])

  const reload = useCallback(() => api('/api/a/case').then((d) => { setData(d); return d }), [])

  useEffect(() => {
    reload().catch((e) => (e instanceof ApiError && e.status === 401 ? navigate('/signin?next=' + encodeURIComponent(location.pathname), true) : setFailed(true)))
  }, [reload])

  useEffect(() => {
    if (!data) return
    const refresh = debounce(() => reload().catch(() => undefined), 250)
    return stream('/api/a/stream', (m) => {
      if (m.type === 'ping') return
      const p = m.payload || {}
      if (m.type === 'open_secure_entry') setOverlay({ kind: 'secure', field: p.field, label: p.label })
      else if (m.type === 'open_upload') setOverlay({ kind: 'upload', documentType: p.document_type })
      else if (m.type === 'open_biographics') setOverlay({ kind: 'biographics' })
      else if (m.type === 'referral_card' && p.variant === 'stop_now') setCards((c) => [...c.filter((x) => x.flag_id !== p.flag_id), p]) // other flags: a note beside the chat reply
      refresh()
    })
  }, [!!data, reload])

  if (failed) {
    return (
      <div className="page col">
        <main className="signin"><div>
          <h1 className="display">We couldn't open your case</h1>
          <p className="lead soft pull">The connection was lost. What you said is saved.</p>
          <button type="button" className="btn lg primary" onClick={() => location.reload()}>Try again</button>
        </div></main>
      </div>
    )
  }
  if (!data) return <div className="page" />

  const lang = langOf(data)
  const close = () => { setOverlay(null); reload() }
  const dismiss = (id: string) => setCards((c) => c.filter((x) => x.flag_id !== id))
  const notAboutMe = async (id: string) => {
    await api(`/api/a/flags/${id}/not_about_me`, { body: {} })
    dismiss(id)
  }

  return (
    <CaseCtx.Provider value={{ data, reload, upload: (documentType) => setOverlay({ kind: 'upload', documentType }) }}>
      {children}
      {cards.length > 0 && (
        <div className="card-stack">
          {cards.slice(-1).map((c) => <ReferralCard key={c.flag_id} card={c} lang={lang} onOk={() => dismiss(c.flag_id)} onNotMe={() => notAboutMe(c.flag_id)} />)}
        </div>
      )}
      {overlay?.kind === 'secure' && <SecureEntrySheet field={overlay.field} label={overlay.label} lang={lang} onClose={close} />}
      {overlay?.kind === 'upload' && <UploadSheet initial={overlay.documentType} lang={lang} onClose={close} onUploaded={() => reload()} />}
      {overlay?.kind === 'biographics' && <BiographicsSheet lang={lang} onClose={close} />}
    </CaseCtx.Provider>
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
