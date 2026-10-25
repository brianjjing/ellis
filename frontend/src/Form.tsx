import { useState } from 'react'
import Shell from './Shell'
import { Icon } from './icons'
import { useCase } from './applicant/ApplicantApp'

// Section states from the Case API → the design's status words and colors.
const statusMeta: Record<string, { label: string; cls: string }> = {
  done: { label: 'Done', cls: 'green' },
  partial: { label: 'In progress', cls: '' },
  blocked: { label: 'With your professional', cls: 'rust' },
  not_started: { label: 'Not started', cls: 'soft' },
}
const segment: Record<string, string> = { done: 'green', partial: 'gold', blocked: 'gold', not_started: 'segment-idle' }
const chipColor: Record<string, string> = { confirmed: 'green', review: 'blue', deferred: 'rust' }

export default function Form() {
  const { data, upload } = useCase()
  const parts = data.progress
  const [i, setI] = useState(Math.max(0, parts.findIndex((p: any) => p.state !== 'done')))
  const [view, setView] = useState<'question' | 'parts'>('question')
  const question = view === 'question'
  const part = parts[i]
  const items = data.facts.find((g: any) => g.section === part?.section)?.items ?? []
  const done = parts.filter((p: any) => p.state === 'done').length
  const open = (n: number) => { setI(n); setView('question'); scrollTo(0, 0) }

  return (
    <Shell active="form">
      <main className="main">
        <header className="bar">
          <div className="stack" style={{ gap: 4 }}>
            <h1 className="h1">{done} of {parts.length} parts done</h1>
          </div>
          <div className="btns">
            <button type="button" className="btn" onClick={() => setView(question ? 'parts' : 'question')}>{question ? 'See all parts' : 'Back to my question'}</button>
            <button type="button" className="btn primary" onClick={() => upload()}><Icon name="upload" />Fill from a document</button>
          </div>
        </header>
        <div aria-hidden="true" className="progress" style={{ gridTemplateColumns: `repeat(${parts.length}, minmax(0, 1fr))` }}>
          {parts.map((p: any) => <div key={p.section} style={{ background: `var(--${segment[p.state]})` }} />)}
        </div>

        {question && part ? (
          <div key={i} className="content enter" style={{ padding: '48px 24px', gap: 28 }}>
            <div className="label">Part {i + 1} · {part.label} · {part.done} of {part.total} confirmed</div>
            <h2 className="display" style={{ marginTop: -14 }}>{part.label}</h2>

            {items.length === 0 ? (
              <div className="panel" style={{ flexDirection: 'column', gap: 12 }}>
                <p className="lead soft" style={{ margin: 0 }}>Nothing here yet. Ellis asks these questions in the chat, one at a time.</p>
                <a href="/" data-nav className="btn md primary" style={{ alignSelf: 'flex-start' }}><Icon name="mic" />Answer with Ellis</a>
              </div>
            ) : (
              <section aria-labelledby="answers" className="stack enter">
                <h3 id="answers" className="rule" style={{ fontSize: 17, lineHeight: '24px', fontWeight: 700 }}>
                  <span className="green" style={{ fontWeight: 700 }}>Ellis</span> · I have {items.length} answer{items.length > 1 ? 's' : ''} for this part
                </h3>
                {items.map((t: any) => (
                  <div key={t.field} className="row" style={{ padding: '16px 0' }}>
                    <span style={{ flex: '1 1 220px', fontSize: 17, fontWeight: 700 }}>{t.label}</span>
                    <span className="mono" style={{ flex: '1 1 220px', fontSize: 15 }}>
                      {t.corrected_from && <><s>{t.corrected_from}</s> → </>}{t.value}{t.days !== undefined && ` · ${t.days} days`}
                    </span>
                    <span className={`status ${chipColor[t.chip.key] ?? ''}`}>{t.chip.label}</span>
                  </div>
                ))}
              </section>
            )}

            <div className="btns" style={{ alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <a href="/" data-nav className="talk"><Icon name="mic" />{items.length ? 'Continue with Ellis' : 'Answer with Ellis'}</a>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn lg" disabled={i === 0} onClick={() => open(i - 1)}>Back</button>
                <button type="button" className="btn lg primary" style={{ padding: '0 32px' }} onClick={() => (i + 1 < parts.length ? open(i + 1) : setView('parts'))}>{i + 1 < parts.length ? `Next: ${parts[i + 1].label}` : 'Done'}</button>
              </div>
            </div>
          </div>
        ) : (
          <div className="content enter" style={{ padding: '40px 24px 48px', gap: 0 }}>
            {parts.map((p: any, n: number) => {
              const meta = statusMeta[p.state] ?? statusMeta.not_started
              return (
                <div key={p.section} className="form-section-row" role="button" tabIndex={0} onClick={() => open(n)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && open(n)}>
                  <span className="mono" style={{ flex: '0 0 28px', fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)' }}>{String(n + 1).padStart(2, '0')}</span>
                  <span style={{ flex: '1 1 200px', fontSize: 17, fontWeight: 700 }}>{p.label}</span>
                  <span className="soft small">{p.done} of {p.total}</span>
                  <span className={`status ${meta.cls}`}>{meta.label}</span>
                  <div className="btns" style={{ gap: 6, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
                    <a href="/" data-nav className="btn sm"><Icon name="mic" size={14} />Answer</a>
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
          </div>
        )}
      </main>
    </Shell>
  )
}
