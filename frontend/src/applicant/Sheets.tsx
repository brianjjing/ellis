// A4 upload sheet, A5 secure entry, biographic pickers, A6 referral cards.
import { useState } from 'react'
import { api, ApiError } from '../api'
import { Icon } from '../icons'

function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <dialog ref={(d) => { if (d && !d.open) d.showModal() }} onClose={onClose} className="dialog sheet enter" aria-label={title}>
      <div className="sheet-head"><h2 className="h1">{title}</h2><button className="btn" onClick={onClose}>Cerrar</button></div>
      {children}
    </dialog>
  )
}

const DOCS: [string, string][] = [
  ['green_card', 'Tarjeta de residente'], ['passport', 'Pasaporte'], ['marriage_certificate', 'Acta de matrimonio'],
  ['lease', 'Contrato de renta'], ['court_record', 'Recibo o documento de la corte'], ['tax_transcript', 'Comprobante de impuestos'],
  ['benefit_letter', 'Carta de beneficios'], ['other', 'Otro'],
]

export function UploadSheet({ initial, onClose, onUploaded }: { initial?: string; onClose: () => void; onUploaded: (id: string) => void }) {
  const [type, setType] = useState<string | null>(initial ?? null)
  const [status, setStatus] = useState<string | null>(null)
  const upload = async (f: File) => {
    if (f.size > 10 * 1024 * 1024) { setStatus('El archivo es muy grande (máximo 10 MB).'); return }
    setStatus('Subiendo…')
    const fd = new FormData()
    fd.append('document_type', type!)
    fd.append('file', f)
    try {
      const r = await api('/api/a/documents', { form: fd })
      onUploaded(r.document_id)
      setStatus('Revisando… Puede seguir hablando.')
      setTimeout(onClose, 1200)
    } catch (e) {
      setStatus(e instanceof ApiError ? e.message : 'No se pudo subir.')
    }
  }
  return (
    <Sheet title="¿Qué documento va a subir?" onClose={onClose}>
      {!type ? (
        <div className="tiles">{DOCS.map(([k, l]) => <button key={k} className="tile" onClick={() => setType(k)}>{l}</button>)}</div>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <p className="lead">Ponga el documento sobre una mesa, con buena luz, sin reflejos.{type === 'green_card' ? ' Tome una foto de los dos lados.' : ''}</p>
          <label className="btn lg primary a-big">
            <Icon name="camera" size={20} />Tomar foto o elegir archivo
            <input type="file" accept="image/jpeg,image/png,image/heic,application/pdf" capture="environment" hidden
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
          <p className="small">JPG, PNG, HEIC o PDF; hasta 10 MB y 5 páginas.</p>
          {status && <p className="lead" role="status">{status}</p>}
          <button className="link-btn" onClick={() => setType(null)}>Elegir otro tipo</button>
        </div>
      )}
    </Sheet>
  )
}

const MASKS: Record<string, { label: string; placeholder: string; pattern?: string }> = {
  a_number: { label: 'Número A', placeholder: 'A123456789' },
  ssn: { label: 'Número de Seguro Social', placeholder: '###-##-####' },
  uscis_account_number: { label: 'Número de cuenta de USCIS (12 dígitos)', placeholder: '000000000000' },
  passport_number: { label: 'Número de pasaporte', placeholder: '' },
  'contact.phone': { label: 'Teléfono', placeholder: '(831) 555-0100' },
  'contact.email': { label: 'Correo electrónico', placeholder: 'nombre@correo.com' },
  'fee.household_size': { label: 'Personas en su hogar', placeholder: '1' },
  'fee.income': { label: 'Ingreso anual del hogar (dólares)', placeholder: '15000' },
}

export function SecureEntrySheet({ field, label, onClose }: { field: string; label: string; onClose: () => void }) {
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
      setErr(e instanceof ApiError ? 'Revise el número, por favor.' : 'No se pudo guardar.')
    }
  }
  return (
    <Sheet title="Escriba aquí, no lo diga en voz alta" onClose={onClose}>
      <p className="small"><Icon name="lock" /> Este número no se lee en voz alta ni lo ve la inteligencia artificial.</p>
      <label htmlFor="sec" className="field">{m.label}</label>
      <input id="sec" className="input code" inputMode={field.includes('email') ? 'email' : 'text'} autoComplete="off"
        placeholder={m.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
      {err && <p className="rust">{err}</p>}
      {done ? <p className="lead green">Guardado ✓</p> : <button className="btn lg primary" onClick={save} disabled={!value}>Guardar</button>}
    </Sheet>
  )
}

const PICKS: Record<string, [string, string][]> = {
  sex: [['female', 'Femenino'], ['male', 'Masculino']],
  eye_color: [['brown', 'Café'], ['black', 'Negro'], ['hazel', 'Avellana'], ['green', 'Verde'], ['blue', 'Azul'], ['gray', 'Gris'], ['unknown', 'Otro']],
  hair_color: [['black', 'Negro'], ['brown', 'Café'], ['gray', 'Canoso'], ['blond', 'Rubio'], ['red', 'Rojo'], ['white', 'Blanco'], ['bald', 'Calvo'], ['unknown', 'Otro']],
  ethnicity: [['hispanic_or_latino', 'Hispano o latino'], ['not_hispanic_or_latino', 'No hispano']],
  race: [['white', 'Blanca'], ['black', 'Negra'], ['asian', 'Asiática'], ['american_indian_alaska_native', 'Indígena americana'], ['native_hawaiian_pacific_islander', 'Isleña del Pacífico']],
}
const PICK_LABEL: Record<string, string> = { sex: 'Sexo', eye_color: 'Color de ojos', hair_color: 'Color de pelo', ethnicity: 'Origen étnico', race: 'Raza' }

export function BiographicsSheet({ onClose }: { onClose: () => void }) {
  const [v, setV] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const save = async () => {
    try { await api('/api/a/biographics', { body: { values: v } }); onClose() } catch { setErr('Revise sus respuestas.') }
  }
  return (
    <Sheet title="Su descripción física" onClose={onClose}>
      {Object.entries(PICKS).map(([k, opts]) => (
        <fieldset key={k} className="pick">
          <legend className="field">{PICK_LABEL[k]}</legend>
          <div className="btns">{opts.map(([val, l]) => (
            <button key={val} type="button" className={`btn md ${v[k] === val ? 'primary' : ''}`} aria-pressed={v[k] === val} onClick={() => setV({ ...v, [k]: val })}>{l}</button>
          ))}</div>
        </fieldset>
      ))}
      <label className="field" htmlFor="h">Estatura</label>
      <input id="h" className="input" placeholder="5 pies 3 pulgadas" value={v.height ?? ''} onChange={(e) => setV({ ...v, height: e.target.value })} />
      <label className="field" htmlFor="w">Peso (libras)</label>
      <input id="w" className="input" inputMode="numeric" placeholder="140" value={v.weight ?? ''} onChange={(e) => setV({ ...v, weight: e.target.value })} />
      {err && <p className="rust">{err}</p>}
      <button className="btn lg primary" onClick={save}>Guardar</button>
    </Sheet>
  )
}

export function ReferralCard({ card, onOk, onNotMe }: { card: any; onOk: () => void; onNotMe: () => void }) {
  const stop = card.variant === 'stop_now'
  return (
    <section className={`referral ${stop ? 'stop' : ''} enter`} role="alert">
      <div className="label">{stop ? 'SU CLÍNICA LE VA A CONTACTAR' : 'PARA REVISIÓN'}</div>
      <h2 className="h3">{card.title}</h2>
      {stop ? <p>{card.body}</p> : <>
        {card.item && <p className="lead">{card.item}</p>}
        {card.prepare?.length > 0 && <><div className="field">Qué puede preparar:</div><ul>{card.prepare.map((p: string) => <li key={p}>{p}</li>)}</ul></>}
        <p className="small">Ellis no puede aconsejarle sobre esto.</p>
      </>}
      {(card.who || card.phone) && <p className="small">Quién le ayuda: {card.who ?? 'su clínica'}{card.phone ? ` · ${card.phone}` : ''}</p>}
      {card.show_emergency && <p className="rust"><strong>Si alguien corre peligro ahora: llame al 911 o al 988.</strong></p>}
      <div className="btns">
        <button className="btn md primary" onClick={onOk}>Entendido</button>
        {stop && <button className="btn md" onClick={onNotMe}>Esto no era sobre mí</button>}
      </div>
    </section>
  )
}
