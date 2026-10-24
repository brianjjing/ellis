// A4 upload sheet, A5 secure entry, biographic pickers, A6 referral cards.
import { useState } from 'react'
import { api, ApiError } from '../api'
import { Icon } from '../icons'
import type { Lang } from './i18n'

function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <dialog ref={(d) => { if (d && !d.open) d.showModal() }} onClose={onClose} className="dialog sheet enter" aria-label={title}>
      <div className="sheet-head"><h2 className="h1">{title}</h2><button className="btn" onClick={onClose}>Close</button></div>
      {children}
    </dialog>
  )
}

const DOCS_ES: [string, string][] = [
  ['green_card', 'Tarjeta de residente'], ['passport', 'Pasaporte'], ['marriage_certificate', 'Acta de matrimonio'],
  ['lease', 'Contrato de renta'], ['court_record', 'Recibo o documento de la corte'], ['tax_transcript', 'Comprobante de impuestos'],
  ['benefit_letter', 'Carta de beneficios'], ['other', 'Otro'],
]
const DOCS_EN: [string, string][] = [
  ['green_card', 'Green card'], ['passport', 'Passport'], ['marriage_certificate', 'Marriage certificate'],
  ['lease', 'Lease'], ['court_record', 'Court record or receipt'], ['tax_transcript', 'Tax transcript'],
  ['benefit_letter', 'Benefit letter'], ['other', 'Other'],
]

export function UploadSheet({ initial, lang = 'es', onClose, onUploaded }: { initial?: string; lang?: Lang; onClose: () => void; onUploaded: (id: string) => void }) {
  const en = lang === 'en'
  const DOCS = en ? DOCS_EN : DOCS_ES
  const [type, setType] = useState<string | null>(initial ?? null)
  const [status, setStatus] = useState<string | null>(null)
  const upload = async (f: File) => {
    if (f.size > 10 * 1024 * 1024) { setStatus(en ? 'The file is too large (10 MB max).' : 'El archivo es muy grande (máximo 10 MB).'); return }
    setStatus(en ? 'Uploading…' : 'Subiendo…')
    const fd = new FormData()
    fd.append('document_type', type!)
    fd.append('file', f)
    try {
      const r = await api('/api/a/documents', { form: fd })
      onUploaded(r.document_id)
      setStatus(en ? 'Reviewing… You can keep talking.' : 'Revisando… Puede seguir hablando.')
      setTimeout(onClose, 1200)
    } catch (e) {
      setStatus(e instanceof ApiError ? e.message : (en ? "Couldn't upload it." : 'No se pudo subir.'))
    }
  }
  return (
    <Sheet title={en ? 'Which document are you uploading?' : '¿Qué documento va a subir?'} onClose={onClose}>
      {!type ? (
        <div className="tiles">{DOCS.map(([k, l]) => <button key={k} className="tile" onClick={() => setType(k)}>{l}</button>)}</div>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <p className="lead">{en ? 'Put the document on a table, in good light, with no glare.' : 'Ponga el documento sobre una mesa, con buena luz, sin reflejos.'}{type === 'green_card' ? (en ? ' Take a photo of both sides.' : ' Tome una foto de los dos lados.') : ''}</p>
          <label className="btn lg primary a-big">
            <Icon name="camera" size={20} />{en ? 'Take photo or choose file' : 'Tomar foto o elegir archivo'}
            <input type="file" accept="image/jpeg,image/png,image/heic,application/pdf" capture="environment" hidden
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
          <p className="small">{en ? 'JPG, PNG, HEIC or PDF; up to 10 MB and 5 pages.' : 'JPG, PNG, HEIC o PDF; hasta 10 MB y 5 páginas.'}</p>
          {status && <p className="lead" role="status">{status}</p>}
          <button className="link-btn" onClick={() => setType(null)}>{en ? 'Choose a different type' : 'Elegir otro tipo'}</button>
        </div>
      )}
    </Sheet>
  )
}

const MASKS_ES: Record<string, { label: string; placeholder: string }> = {
  a_number: { label: 'Número A', placeholder: 'A123456789' },
  ssn: { label: 'Número de Seguro Social', placeholder: '###-##-####' },
  uscis_account_number: { label: 'Número de cuenta de USCIS (12 dígitos)', placeholder: '000000000000' },
  passport_number: { label: 'Número de pasaporte', placeholder: '' },
  'contact.phone': { label: 'Teléfono', placeholder: '(831) 555-0100' },
  'contact.email': { label: 'Correo electrónico', placeholder: 'nombre@correo.com' },
  'fee.household_size': { label: 'Personas en su hogar', placeholder: '1' },
  'fee.income': { label: 'Ingreso anual del hogar (dólares)', placeholder: '15000' },
}
const MASKS_EN: Record<string, { label: string; placeholder: string }> = {
  a_number: { label: 'A-number', placeholder: 'A123456789' },
  ssn: { label: 'Social Security number', placeholder: '###-##-####' },
  uscis_account_number: { label: 'USCIS online account number (12 digits)', placeholder: '000000000000' },
  passport_number: { label: 'Passport number', placeholder: '' },
  'contact.phone': { label: 'Phone', placeholder: '(831) 555-0100' },
  'contact.email': { label: 'Email', placeholder: 'name@email.com' },
  'fee.household_size': { label: 'People in your household', placeholder: '1' },
  'fee.income': { label: 'Annual household income (dollars)', placeholder: '15000' },
}

export function SecureEntrySheet({ field, label, lang = 'es', onClose }: { field: string; label: string; lang?: Lang; onClose: () => void }) {
  const en = lang === 'en'
  const MASKS = en ? MASKS_EN : MASKS_ES
  const [value, setValue] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const m = MASKS[field] ?? { label, placeholder: '' }
  const save = async () => {
    try {
      await api('/api/a/secure', { body: { field, value } })
      setDone(true)
      setTimeout(onClose, 900)
    } catch (e) {
      setErr(e instanceof ApiError ? (en ? 'Please check the number.' : 'Revise el número, por favor.') : (en ? "Couldn't save it." : 'No se pudo guardar.'))
    }
  }
  return (
    <Sheet title={en ? "Type it here, don't say it out loud" : 'Escriba aquí, no lo diga en voz alta'} onClose={onClose}>
      <p className="small"><Icon name="lock" /> {en ? "This number isn't spoken aloud or seen by the AI." : 'Este número no se lee en voz alta ni lo ve la inteligencia artificial.'}</p>
      <label htmlFor="sec" className="field">{m.label}</label>
      <input id="sec" className="input code" inputMode={field.includes('email') ? 'email' : 'text'} autoComplete="off"
        placeholder={m.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
      {err && <p className="rust">{err}</p>}
      {done ? <p className="lead green">{en ? 'Saved ✓' : 'Guardado ✓'}</p> : <button className="btn lg primary" onClick={save} disabled={!value}>{en ? 'Save' : 'Guardar'}</button>}
    </Sheet>
  )
}

const PICKS_ES: Record<string, [string, string][]> = {
  sex: [['female', 'Femenino'], ['male', 'Masculino']],
  eye_color: [['brown', 'Café'], ['black', 'Negro'], ['hazel', 'Avellana'], ['green', 'Verde'], ['blue', 'Azul'], ['gray', 'Gris'], ['unknown', 'Otro']],
  hair_color: [['black', 'Negro'], ['brown', 'Café'], ['gray', 'Canoso'], ['blond', 'Rubio'], ['red', 'Rojo'], ['white', 'Blanco'], ['bald', 'Calvo'], ['unknown', 'Otro']],
  ethnicity: [['hispanic_or_latino', 'Hispano o latino'], ['not_hispanic_or_latino', 'No hispano']],
  race: [['white', 'Blanca'], ['black', 'Negra'], ['asian', 'Asiática'], ['american_indian_alaska_native', 'Indígena americana'], ['native_hawaiian_pacific_islander', 'Isleña del Pacífico']],
}
const PICK_LABEL_ES: Record<string, string> = { sex: 'Sexo', eye_color: 'Color de ojos', hair_color: 'Color de pelo', ethnicity: 'Origen étnico', race: 'Raza' }
const PICKS_EN: Record<string, [string, string][]> = {
  sex: [['female', 'Female'], ['male', 'Male']],
  eye_color: [['brown', 'Brown'], ['black', 'Black'], ['hazel', 'Hazel'], ['green', 'Green'], ['blue', 'Blue'], ['gray', 'Gray'], ['unknown', 'Other']],
  hair_color: [['black', 'Black'], ['brown', 'Brown'], ['gray', 'Gray'], ['blond', 'Blond'], ['red', 'Red'], ['white', 'White'], ['bald', 'Bald'], ['unknown', 'Other']],
  ethnicity: [['hispanic_or_latino', 'Hispanic or Latino'], ['not_hispanic_or_latino', 'Not Hispanic or Latino']],
  race: [['white', 'White'], ['black', 'Black'], ['asian', 'Asian'], ['american_indian_alaska_native', 'American Indian or Alaska Native'], ['native_hawaiian_pacific_islander', 'Native Hawaiian or Pacific Islander']],
}
const PICK_LABEL_EN: Record<string, string> = { sex: 'Sex', eye_color: 'Eye color', hair_color: 'Hair color', ethnicity: 'Ethnicity', race: 'Race' }

export function BiographicsSheet({ lang = 'es', onClose }: { lang?: Lang; onClose: () => void }) {
  const en = lang === 'en'
  const PICKS = en ? PICKS_EN : PICKS_ES
  const PICK_LABEL = en ? PICK_LABEL_EN : PICK_LABEL_ES
  const [v, setV] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    try { await api('/api/a/biographics', { body: { values: v } }); onClose() } catch { setErr(en ? 'Please check your answers.' : 'Revise sus respuestas.') }
  }
  return (
    <Sheet title={en ? 'Your physical description' : 'Su descripción física'} onClose={onClose}>
      {Object.entries(PICKS).map(([k, opts]) => (
        <fieldset key={k} className="pick">
          <legend className="field">{PICK_LABEL[k]}</legend>
          <div className="btns">{opts.map(([val, l]) => (
            <button key={val} type="button" className={`btn md ${v[k] === val ? 'primary' : ''}`} aria-pressed={v[k] === val} onClick={() => setV({ ...v, [k]: val })}>{l}</button>
          ))}</div>
        </fieldset>
      ))}
      <label className="field" htmlFor="h">{en ? 'Height' : 'Estatura'}</label>
      <input id="h" className="input" placeholder={en ? '5 ft 3 in' : '5 pies 3 pulgadas'} value={v.height ?? ''} onChange={(e) => setV({ ...v, height: e.target.value })} />
      <label className="field" htmlFor="w">{en ? 'Weight (pounds)' : 'Peso (libras)'}</label>
      <input id="w" className="input" inputMode="numeric" placeholder="140" value={v.weight ?? ''} onChange={(e) => setV({ ...v, weight: e.target.value })} />
      {err && <p className="rust">{err}</p>}
      <button className="btn lg primary" onClick={save}>{en ? 'Save' : 'Guardar'}</button>
    </Sheet>
  )
}

export function ReferralCard({ card, lang = 'es', onOk, onNotMe }: { card: any; lang?: Lang; onOk: () => void; onNotMe: () => void }) {
  const stop = card.variant === 'stop_now'
  const en = lang === 'en'
  return (
    <section className={`referral ${stop ? 'stop' : ''} enter`} role="alert">
      <div className="label">{stop ? (en ? 'YOUR CLINIC WILL CONTACT YOU' : 'SU CLÍNICA LE VA A CONTACTAR') : (en ? 'FOR REVIEW' : 'PARA REVISIÓN')}</div>
      <h2 className="h3">{card.title}</h2>
      {stop ? <p>{card.body}</p> : <>
        {card.item && <p className="lead">{card.item}</p>}
        {card.prepare?.length > 0 && <><div className="field">{en ? 'What you can prepare:' : 'Qué puede preparar:'}</div><ul>{card.prepare.map((p: string) => <li key={p}>{p}</li>)}</ul></>}
        <p className="small">{en ? "Ellis can't advise you on this." : 'Ellis no puede aconsejarle sobre esto.'}</p>
      </>}
      {(card.who || card.phone) && <p className="small">{en ? 'Who can help: ' : 'Quién le ayuda: '}{card.who ?? (en ? 'your clinic' : 'su clínica')}{card.phone ? ` · ${card.phone}` : ''}</p>}
      {card.show_emergency && <p className="rust"><strong>{en ? 'If someone is in danger right now: call 911 or 988.' : 'Si alguien corre peligro ahora: llame al 911 o al 988.'}</strong></p>}
      <div className="btns">
        <button className="btn md primary" onClick={onOk}>{en ? 'Understood' : 'Entendido'}</button>
        {stop && <button className="btn md" onClick={onNotMe}>{en ? "This wasn't about me" : 'Esto no era sobre mí'}</button>}
      </div>
    </section>
  )
}
