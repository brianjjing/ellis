import { type FormEvent, useEffect, useState } from 'react'
import Shell from './Shell'
import { api, ApiError } from './api'
import { Icon } from './icons'
import { useCase } from './applicant/ApplicantApp'
import { Sheet } from './applicant/Sheets'

// Section states from the Case API → the design's status words and colors.
const statusMeta: Record<string, { label: string; cls: string }> = {
  done: { label: 'Done', cls: 'green' },
  partial: { label: 'In progress', cls: '' },
  blocked: { label: 'With your professional', cls: 'rust' },
  not_started: { label: 'Not started', cls: 'soft' },
}
const segment: Record<string, string> = { done: 'green', partial: 'gold', blocked: 'gold', not_started: 'segment-idle' }
const chipColor: Record<string, string> = { confirmed: 'green', review: 'blue', deferred: 'rust' }
const saveErrors: Record<string, string> = {
  invalid_value: 'Check this answer and try again.',
  consent_required: 'Agree to the notice in the chat with Ellis first, then answer here.',
  deferred_to_professional: 'Your professional will go over this part with you.',
}
const tag = (required: boolean) => (
  <span className="small" style={{ marginLeft: 8, fontWeight: 700, color: required ? 'var(--rust)' : undefined }}>{required ? 'Required' : 'Optional'}</span>
)

// A question not answered yet, filled in right on the form. It goes through the same checks as a spoken answer.
function Blank({ q, onSaved }: { q: any; onSaved: () => void }) {
  const [v, setV] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const id = `q-${q.field}`
  const save = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/api/a/answer', { body: { field: q.field, value: q.options ? q.options[+v].value : v.trim() } })
      onSaved()
    } catch (err) {
      setError((err instanceof ApiError && saveErrors[err.code]) || "This answer couldn't be saved. Try again.")
      setBusy(false)
    }
  }
  const box = { flex: '1 1 220px', height: 44, fontSize: 15 }
  return (
    <form className="row" style={{ padding: '16px 0' }} onSubmit={save}>
      <label htmlFor={id} style={{ flex: '1 1 220px', fontSize: 17, fontWeight: 700 }}>{q.label}{tag(q.required)}</label>
      {q.options ? (
        <select id={id} className="input sm" style={box} value={v} onChange={(e) => setV(e.target.value)}>
          <option value="" disabled>Choose…</option>
          {q.options.map((o: any, n: number) => <option key={n} value={n}>{o.label}</option>)}
        </select>
      ) : (
        <input id={id} className="input sm mono" style={box} autoComplete="off" value={v} onChange={(e) => setV(e.target.value)}
          type={q.type === 'date' ? 'date' : 'text'} inputMode={q.type === 'int' || q.type === 'ssn' ? 'numeric' : undefined}
          placeholder={q.type === 'string_list' || q.type === 'optional_name' ? 'Type "none" if none' : undefined} />
      )}
      <button type="submit" className="btn" disabled={busy || !v.trim()}>{busy ? 'Saving…' : 'Save'}</button>
      {error && <p className="small" role="alert" style={{ flexBasis: '100%', color: 'var(--rust)' }}>{error}</p>}
    </form>
  )
}

export default function Form() {
  const { data, reload, upload, filling } = useCase()
  const parts = data.progress
  const [i, setI] = useState(Math.max(0, parts.findIndex((p: any) => p.state !== 'done')))
  const [view, setView] = useState<'question' | 'parts'>('question')
  const question = view === 'question'
  const part = parts[i]
  const items = data.facts.find((g: any) => g.section === part?.section)?.items ?? []
  const missing: any[] = part?.missing ?? []
  const required = missing.filter((q) => q.required).length
  const done = parts.filter((p: any) => p.state === 'done').length
  const open = (n: number) => { setI(n); setView('question'); scrollTo(0, 0) }
  useEffect(() => { if (filling) setView('parts') }, [filling]) // an N-400 upload fills the parts view live
  const n400 = data.documents.filter((d: any) => d.document_type === 'n400').at(-1)
  const [clearing, setClearing] = useState<'confirm' | 'busy' | 'failed' | null>(null)
  const clearAll = async () => {
    setClearing('busy')
    try { await api('/api/a/clear', { body: {} }) } catch { return setClearing('failed') }
    setClearing(null) // saved: close now; the counts follow when the page refresh lands
    reload().catch(() => undefined)
  }
  const nav = (
    <div style={{ display: 'flex', gap: 8 }}>
      <button type="button" className="btn lg" disabled={i === 0} onClick={() => open(i - 1)}>Back</button>
      <button type="button" className="btn lg primary" style={{ padding: '0 32px' }} onClick={() => (i + 1 < parts.length ? open(i + 1) : setView('parts'))}>{i + 1 < parts.length ? `Next: ${parts[i + 1].label}` : 'Done'}</button>
    </div>
  )

  return (
    <Shell active="form">
      <main className="main">
        <header className="bar">
          <div className="stack" style={{ gap: 4 }}>
            <h1 className="h1">{done} of {parts.length} parts done</h1>
          </div>
          <div className="btns">
            <button type="button" className="btn" onClick={() => setView(question ? 'parts' : 'question')}>{question ? 'See all parts' : 'Back to my question'}</button>
            <button type="button" className="btn primary" onClick={() => upload('n400')}><Icon name="upload" />Fill from a document</button>
          </div>
        </header>
        <nav aria-label="Form parts" className="progress" style={{ gridTemplateColumns: `repeat(${parts.length}, minmax(0, 1fr))` }}>
          {parts.map((p: any, n: number) => (
            <button key={p.section} type="button" title={p.label} aria-label={`Part ${n + 1} of ${parts.length}: ${p.label}`}
              aria-current={question && n === i ? 'step' : undefined} style={{ backgroundColor: `var(--${segment[p.state]})` }} onClick={() => open(n)} />
          ))}
        </nav>

        {question && part ? (
          <div key={i} className="content enter" style={{ padding: '48px 24px', gap: 28 }}>
            <div className="label">Part {i + 1} · {part.label} · {part.total ? `${part.done} of ${part.total} required confirmed` : 'Nothing required'}</div>
            <h2 className="display" style={{ marginTop: -14 }}>{part.label}</h2>

            {items.length === 0 && missing.length === 0 ? (
              // empty part: the note and every action sit in the one white box
              <div className="panel" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 32 }}>
                <p className="lead soft" style={{ margin: 0 }}>Nothing here yet. Ellis asks these questions in the chat, one at a time.</p>
                <div className="btns" style={{ alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                  <a href="/" data-nav className="btn lg primary">Answer with Ellis<Icon name="mic" /></a>
                  {nav}
                </div>
              </div>
            ) : <>
              {missing.length > 0 && (
                <section aria-labelledby="unanswered" className="stack enter">
                  <h3 id="unanswered" className="rule" style={{ fontSize: 17, lineHeight: '24px', fontWeight: 700 }}>
                    <span className="rust" style={{ fontWeight: 700 }}>Still to answer</span> · {[required && `${required} required`, missing.length - required && `${missing.length - required} optional`].filter(Boolean).join(', ')}
                  </h3>
                  {missing.map((q) => <Blank key={q.field} q={q} onSaved={() => reload().catch(() => undefined)} />)}
                </section>
              )}
              {items.length > 0 && <section aria-labelledby="answers" className="stack enter">
                <h3 id="answers" className="rule" style={{ fontSize: 17, lineHeight: '24px', fontWeight: 700 }}>
                  <span className="green" style={{ fontWeight: 700 }}>Ellis</span> · I have {items.length} answer{items.length > 1 ? 's' : ''} for this part
                </h3>
                {items.map((t: any) => (
                  <div key={t.field} className="row" style={{ padding: '16px 0' }}>
                    <span style={{ flex: '1 1 220px', fontSize: 17, fontWeight: 700 }}>{t.label}{part.optional?.includes(t.field) && tag(false)}</span>
                    <span className="mono" style={{ flex: '1 1 220px', fontSize: 15 }}>
                      {t.corrected_from && <><s>{t.corrected_from}</s> → </>}{t.value}{t.days !== undefined && ` · ${t.days} days`}
                    </span>
                    <span className={`status ${chipColor[t.chip.key] ?? ''}`}>{t.chip.label}</span>
                  </div>
                ))}
              </section>}
              <div className="btns" style={{ alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <a href="/" data-nav className="talk">Continue with Ellis<Icon name="mic" /></a>
                {nav}
              </div>
            </>}
          </div>
        ) : (
          <div className="content enter" style={{ padding: '40px 24px 48px', gap: 0 }}>
            {n400?.status === 'failed' && !filling && <p className="rust" role="alert" style={{ margin: '0 0 16px' }}>We couldn't read your N-400. Upload the fillable PDF of the form.</p>}
            {filling && <span className="sr-only" role="status">Filling your form from your N-400</span>}
            {parts.map((p: any, n: number) => {
              const meta = statusMeta[p.state] ?? statusMeta.not_started
              return (
                <div key={p.section} className="form-section-row" role="button" tabIndex={0} onClick={() => open(n)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && open(n)}>
                  <span className="mono" style={{ flex: '0 0 28px', fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)' }}>{String(n + 1).padStart(2, '0')}</span>
                  <span style={{ flex: '1 1 200px', fontSize: 17, fontWeight: 700 }}>{p.label}</span>
                  {filling && p.done < p.total && <span className="dots" aria-hidden="true" />}
                  <span className="soft small">{p.total ? `${p.done} of ${p.total}` : 'Optional'}</span>
                  <span className={`status ${meta.cls}`}>{meta.label}</span>
                  <div className="btns" style={{ gap: 6, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
                    <a href="/" data-nav className="btn sm">Answer<Icon name="mic" size={14} /></a>
                    <button type="button" className="btn sm" onClick={() => open(n)}>Edit</button>
                  </div>
                </div>
              )
            })}
            {parts.length === 0 && (
              <div className="panel" style={{ margin: '20px 0' }}>
                <p className="lead soft" style={{ margin: 0 }}>No sections yet. Your form will appear here after your first session with Ellis.</p>
              </div>
            )}
            {(data.state === 'ready' || data.state === 'signed') && (
              <a href="/review" data-nav className="btn lg primary" style={{ marginTop: 28, alignSelf: 'flex-start' }}>{data.state === 'ready' ? 'Review and sign' : 'Open my packet'}</a>
            )}
            {parts.length > 0 && <button type="button" className="btn lg danger clear-all" style={{ marginTop: 28, alignSelf: 'flex-end' }} disabled={!!filling} onClick={() => setClearing('confirm')}>Clear all</button>}
            {clearing && (
              <Sheet title="Clear all answers?" onClose={() => setClearing(null)}>
                <p className="lead">Every answer in all parts of your form will be cleared. You can't undo this.</p>
                {clearing === 'failed' && <p className="rust" role="alert">Your form couldn't be cleared. Try again.</p>}
                <div className="btns">
                  <button type="button" className="btn lg danger clear-all" disabled={clearing === 'busy'} onClick={clearAll}>{clearing === 'busy' ? 'Clearing…' : 'Clear all'}</button>
                  <button type="button" className="btn lg" onClick={() => setClearing(null)}>Cancel</button>
                </div>
              </Sheet>
            )}
          </div>
        )}
      </main>
    </Shell>
  )
}
