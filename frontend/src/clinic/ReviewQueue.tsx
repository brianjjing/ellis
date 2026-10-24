// C3 Review queue: one row per open review item; stop-now pinned on top. Keyboard: J/K move, C clear, N note.
import { useEffect, useRef, useState } from 'react'
import { api, ApiError, fmtTime } from '../api'
import type { Me } from './ClinicApp'

const DECISIONS: [string, string, string][] = [
  ['clear', 'Clear', 'Item closed; no longer blocks'],
  ['clear_with_referral', 'Clear with referral', 'Closed; the note is shown to the applicant'],
  ['needs_more_info', 'Needs more info', 'Stays open; the note becomes a question for the liaison'],
  ['resolved_by_professional', 'Resolved by professional', 'Stop-now only: handled outside Ellis'],
  ['block_case', 'Block case', 'Case cannot reach ready'],
  ['not_about_applicant', 'Not about applicant', 'Only after the applicant tapped "Esto no era sobre mí"'],
]

export default function ReviewQueue({ me, tick }: { me: Me; tick: number }) {
  const [data, setData] = useState<{ items: any[]; cases: Record<string, any> }>({ items: [], cases: {} })
  const [sel, setSel] = useState(0)
  const [all, setAll] = useState(false)
  const noteRef = useRef<HTMLTextAreaElement | null>(null)
  const load = () => api(`/api/clinic/review?all_cases=${all}`).then(setData)
  useEffect(() => { load() }, [tick, all])
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'TEXTAREA' || (e.target as HTMLElement).tagName === 'INPUT') return
      if (e.key === 'j') setSel((s) => Math.min(s + 1, data.items.length - 1))
      if (e.key === 'k') setSel((s) => Math.max(s - 1, 0))
      if (e.key === 'n') { e.preventDefault(); noteRef.current?.focus() }
      if (e.key === 'c') document.getElementById('decide-clear')?.click()
    }
    addEventListener('keydown', on)
    return () => removeEventListener('keydown', on)
  }, [data.items.length])
  const item = data.items[sel]
  return (
    <>
      <header className="bar">
        <h1 className="h1">Review queue</h1>
        <div className="btns">
          {me.clinic.is_demo && <span className="demo-tag">Simulated clinic reviewer (demo)</span>}
          <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> All cases</label>
        </div>
      </header>
      <div className="queue">
        <ul className="q-list" role="listbox" aria-label="Review items">
          {data.items.length === 0 && <li className="soft" style={{ padding: 16 }}>Nothing to review.</li>}
          {data.items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === sel} className={`q-row ${i === sel ? 'sel' : ''} ${it.speed === 'stop_now' ? 'stop' : ''}`} onClick={() => setSel(i)}>
              <span className="label">{it.speed === 'stop_now' ? 'STOP-NOW' : it.category.replace(/_/g, ' ').toUpperCase()}</span>
              <span>{it.applicant}{it.self_report ? ' · applicant: "not about me"' : ''}</span>
              <span className="small">{fmtTime(it.ts)}{it.status === 'case_blocked' ? ' · case blocked' : ''}</span>
            </li>
          ))}
        </ul>
        {item && <ItemDetail key={item.id} item={item} gate={data.cases[item.case_id]} noteRef={noteRef} onDone={load} />}
      </div>
    </>
  )
}

function ItemDetail({ item, gate, noteRef, onDone }: { item: any; gate: any; noteRef: React.RefObject<HTMLTextAreaElement | null>; onDone: () => void }) {
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const stop = item.speed === 'stop_now'
  const decide = async (d: string) => {
    setErr(null)
    try { await api(`/api/clinic/review/${item.id}/decision`, { body: { decision: d, note } }); setNote(''); onDone() } catch (e) { setErr(e instanceof ApiError ? e.message : 'failed') }
  }
  const ready = async () => {
    try { await api(`/api/clinic/cases/${item.case_id}/ready`, { body: {} }); onDone() } catch (e) { setErr(e instanceof ApiError ? `${e.message}: ${(e.details ?? []).map((f: any) => f.message).join('; ')}` : 'failed') }
  }
  return (
    <section className="q-detail">
      <div className="label">{stop ? 'STOP-NOW' : `${item.category.replace(/_/g, ' ')} · ${item.speed.replace('_', ' ')}`}</div>
      <h2 className="h1"><a href={`/clinic/cases/${item.case_id}`} data-nav>{item.applicant}</a></h2>
      {stop ? (
        <div className="panel warn"><strong>{item.banner}</strong><span className="small">Category: {item.category} · {fmtTime(item.ts)} · {item.trigger}</span></div>
      ) : (
        <dl className="kv">
          <dt>What triggered it</dt><dd>{item.trigger}{item.rule_id ? ` · ${item.rule_id}` : ''}</dd>
          <dt>Facts involved</dt><dd>{item.facts ?? '—'}</dd>
          <dt>Evidence attached</dt><dd>{item.evidence?.length ? item.evidence.map((d: any) => <a key={d.id} href={`/api/clinic/documents/${d.id}/file`} target="_blank" rel="noreferrer" className="pill">{d.document_type.replace('_', ' ')}</a>) : '—'}</dd>
          <dt>Agent notes</dt><dd>{item.agent_notes?.length ? item.agent_notes.map((n: any, i: number) => <p key={i} className="small">{n.note} <span className="soft">— {n.by.split('@')[0].replace('_', ' ')}</span></p>) : '—'}</dd>
        </dl>
      )}
      <label htmlFor="note" className="field">Note (required)</label>
      <textarea id="note" ref={noteRef} className="input area" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="btns">
        {DECISIONS.filter(([k]) => stop ? ['resolved_by_professional', 'block_case', 'not_about_applicant', 'needs_more_info'].includes(k) : !['resolved_by_professional', 'not_about_applicant'].includes(k)).map(([k, l, d]) => (
          <button key={k} id={k === 'clear' ? 'decide-clear' : undefined} className={`btn md ${k.startsWith('clear') || k === 'resolved_by_professional' ? 'primary' : ''}`} title={d} disabled={!note.trim()} onClick={() => decide(k)}>{l}</button>
        ))}
      </div>
      {err && <p className="rust">{err}</p>}
      {gate && (
        <div className="panel">
          <span className="grow">Gate for {gate.applicant}: {gate.gate.passes ? 'passes' : gate.gate.failing.map((f: any) => f.message).join('; ')}</span>
          <button className="btn md primary" disabled={!gate.gate.passes} onClick={ready}>Mark ready for applicant sign-off</button>
        </div>
      )}
    </section>
  )
}
