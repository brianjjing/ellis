// A8 review and sign-off; A9 packet ready. Professional-draft path for stop-now cases (F2.08–F2.09).
import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Roadmap, type CaseView } from './ApplicantApp'

export function ReviewSignoff({ data, reload, onSigned, onBack }: { data: CaseView; reload: () => void; onSigned: () => void; onBack: () => void }) {
  const [view, setView] = useState<any>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [checked, setChecked] = useState(false)
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/a/review').then(setView).catch((e) => setErr(e.message)) }, [data.state])

  if (err && !view) return <main className="a-main"><p className="lead">{err}</p><button className="btn lg" onClick={onBack}>Volver</button></main>
  if (!view) return <main className="a-main"><p className="lead">Cargando…</p></main>

  const listen = (sec: any) => {
    const synth = window.speechSynthesis
    if (!synth) return
    synth.cancel()
    const u = new SpeechSynthesisUtterance(`${sec.label}. ` + sec.items.map((i: any) => `${i.label}: ${i.value}`).join('. '))
    u.lang = 'es-MX'
    synth.speak(u)
  }
  const wrong = async (sec: string) => {
    await api('/api/a/review/reopen', { body: { section: sec } })
    reload()
    onBack()
  }
  const sign = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api('/api/a/signoff', { body: { typed_name: name, attestation_version: view.attestation_version } })
      onSigned()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'No se pudo firmar.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="a-main">
      <div className="panel ok">Su clínica revisó su caso. Ahora revise usted cada respuesta.</div>
      {view.sections.map((sec: any) => (
        <section key={sec.key} className="acc">
          <button className="acc-head" aria-expanded={open === sec.key} onClick={() => setOpen(open === sec.key ? null : sec.key)}>
            <span className="h3">{sec.label}</span><span className="soft">{sec.items.length} respuestas</span>
          </button>
          {open === sec.key && (
            <div className="acc-body">
              {sec.items.map((i: any) => (
                <div key={i.field} className="row rv-row">
                  <span className="soft grow">{i.label}</span>
                  <strong className={i.deferred ? 'soft' : ''}>{i.value}</strong>
                </div>
              ))}
              <div className="btns">
                <button className="btn md" onClick={() => listen(sec)}>Escuchar esta sección</button>
                <button className="btn md danger" onClick={() => wrong(sec.key)}>Algo está mal aquí</button>
              </div>
            </div>
          )}
        </section>
      ))}
      <label className="attest">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <span>{view.attestation_text}</span>
      </label>
      <label htmlFor="nm" className="field">Escriba su nombre completo, como aparece en sus documentos</label>
      <input id="nm" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
      {err && <p className="rust">{err}</p>}
      <button className="btn lg primary a-big" disabled={!checked || !name.trim() || busy} onClick={sign}>{busy ? 'Preparando su paquete…' : 'Firmar'}</button>
      <p className="small">Ellis no envía nada. Usted presenta la solicitud en su cuenta de USCIS, o su clínica la presenta por usted.</p>
    </main>
  )
}

const KIND_ES: Record<string, string> = {
  n400_pdf: 'Borrador del formulario N-400', online_copy_sheet: 'Hoja para copiar en línea', evidence_index: 'Índice de pruebas',
  fee_sheet: 'Hoja de la tarifa', filing_checklist: 'Lista para presentar', i912_pdf: 'Borrador del formulario I-912',
  professional_draft: 'Borrador para su profesional',
}

export function PacketReady({ data }: { data: CaseView }) {
  const [files, setFiles] = useState<any[]>([])
  const [draft, setDraft] = useState<any>(null)
  useEffect(() => { api('/api/a/packet').then((r) => setFiles(r.files)).catch(() => undefined) }, [data.state])
  const referred = data.state === 'referred_out'
  const proDraft = async () => setDraft(await api('/api/a/professional_draft', { body: {} }))
  const proFiles = async () => { await api('/api/a/representation', { body: { professional_files: true } }); location.reload() }
  return (
    <main className="a-main">
      <h1 className="display">{referred ? 'Su profesional le ayuda con el resto.' : 'Su paquete está listo.'}</h1>
      {files.length > 0 && <p className="lead">Su clínica también tiene una copia.</p>}
      <div className="stack" style={{ gap: 10 }}>
        {files.map((f) => <a key={f.id} className="btn lg strong" href={f.url} target="_blank" rel="noreferrer">{KIND_ES[f.kind] ?? f.filename}</a>)}
        {draft && <a className="btn lg strong" href={draft.url} target="_blank" rel="noreferrer">{KIND_ES.professional_draft}</a>}
      </div>
      {!files.length && !referred && (
        <section className="panel">
          <p className="lead">¿Ya habló con un profesional con licencia?</p>
          <div className="btns">
            <button className="btn md" onClick={proDraft}>Descargar un borrador para mi profesional</button>
            <button className="btn md" onClick={proFiles}>Mi profesional presentará por mí</button>
          </div>
        </section>
      )}
      <h2 className="h3 rule">¿Qué sigue?</h2>
      <p className="lead">La solicitud la presenta usted o su clínica. Ellis nunca la envía.</p>
      <Roadmap data={data} />
    </main>
  )
}
