import { useEffect, useState, type ReactNode } from 'react'
import Shell from './Shell'
import { Flag, Icon } from './icons'
import { api } from './api'
import { signOut, useAuth } from './auth'
import { fact, useCase } from './applicant/ApplicantApp'
import { LANGUAGES, langOf, type Lang } from './applicant/i18n'
import { DOCS_EN } from './applicant/Sheets'

const tabs = [
  { id: 'docs', label: 'Documents' },
  { id: 'case', label: 'Case details' },
  { id: 'flags', label: 'Attorney' },
]

const docName = Object.fromEntries(DOCS_EN)
const dialects = LANGUAGES.flatMap((l) => l.dialects.map((d) => ({ ...d, label: `${l.label} (${d.label})` })))

function docNote(d: any): [string, boolean] {
  if (d.status === 'extracting' || d.status === 'uploaded') return ['Reading it…', false]
  if (d.status === 'extracted') return d.quality === 'low' ? ["The photo isn't clear. Can you take another?", true] : ['Read · used for your form', false]
  return ["We couldn't read it. Try another photo.", true]
}

function Setting({ name, note, children }: { name: ReactNode; note: string; children?: ReactNode }) {
  return (
    <div className="row" style={{ minHeight: 64, padding: '10px 0' }}>
      <span className="stack" style={{ flex: '1 1 260px' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 17, fontWeight: 700 }}>{name}</span>
        <span className="soft" style={{ fontSize: 15 }}>{note}</span>
      </span>
      {children}
    </div>
  )
}

// F2.08–F2.09: for a stop-now item the applicant can take a draft to their own professional. Ellis sends nothing.
function ProfessionalOptions({ reload, lang }: { reload: () => void; lang: Lang }) {
  const [url, setUrl] = useState<string | null>(null)
  return (
    <div className="btns" style={{ flexBasis: '100%' }}>
      <button type="button" className="btn md" onClick={async () => setUrl((await api('/api/a/professional_draft', { body: {} })).url)}>{lang === 'en' ? 'Download a draft for my professional' : 'Descargar un borrador para mi profesional'}</button>
      <button type="button" className="btn md" onClick={async () => { await api('/api/a/representation', { body: { professional_files: true } }); reload() }}>{lang === 'en' ? 'My professional will file for me' : 'Mi profesional presentará por mí'}</button>
      {url && <a className="btn md strong" href={url} target="_blank" rel="noreferrer">{lang === 'en' ? 'Open the draft' : 'Abrir el borrador'}</a>}
    </div>
  )
}

// The profile at the foot of the sidebar: account and language, with the case's advanced views below.
export default function Profile() {
  const { data, reload, upload } = useCase()
  const [tab, setTab] = useState(new URLSearchParams(location.search).get('tab') ?? 'docs')
  const [picking, setPicking] = useState(false)
  const lang = langOf(data)
  const facts = data.facts.flatMap((g: any) => g.items)
  const name = [fact(data, 'name.given') ?? data.first_name, fact(data, 'name.family')].filter(Boolean).join(' ')
  const contact = [fact(data, 'contact.email'), fact(data, 'contact.phone')].filter(Boolean).join(' · ')
  const flags = data.referrals.length + data.reviewer_notes.length + (data.case_blocked ? 1 : 0)

  const decline = async (id: string) => { await api(`/api/a/gaps/${id}/decline`, { body: {} }); reload() }
  const setLanguage = async (locale: string) => { await api('/api/a/language', { body: { locale } }); setPicking(false); reload() }
  const setConsent = async (agree: boolean) => { await api('/api/a/consent', { body: { agree } }); reload() }
  const { refresh } = useAuth()
  const logOut = () => signOut(refresh)
  // Deep links like /profile?tab=flags land on the Advanced section.
  useEffect(() => { if (location.search.includes('tab=')) document.getElementById('advanced')?.scrollIntoView() }, [])

  return (
    <Shell active="profile">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Profile</h1>
        </header>

        <div className="content" style={{ padding: '40px 24px 48px', gap: 20 }}>
          <section aria-labelledby="profile" className="panel" style={{ gap: 16 }}>
            <span aria-hidden="true" className="avatar" style={{ flex: '0 0 56px', height: 56, borderRadius: 6, fontSize: 26, lineHeight: '56px' }}>{name[0]}</span>
            <div className="stack" style={{ flex: '1 1 240px', gap: 2 }}>
              <h2 id="profile" style={{ margin: 0, fontSize: 19, lineHeight: '24px', fontWeight: 700 }}>{name}</h2>
              <span className="soft" style={{ fontSize: 15 }}>{contact || `Prepared with ${data.clinic.name}`}</span>
            </div>
            <a href="/" data-nav className="btn">Edit</a>
          </section>
          <h3 className="h3 rule" style={{ marginTop: 12 }}>How you sign in</h3>
          <div className="stack" style={{ marginTop: -20 }}>
            <Setting name={`Private link from ${data.clinic.name}`} note="Works for 30 days after you last use it. Your clinic can send a new one.">
              <span className="status green">This device</span>
            </Setting>
          </div>
          <h3 className="h3 rule" style={{ marginTop: 12 }}>Privacy</h3>
          <div className="stack" style={{ marginTop: -20 }}>
            <Setting name="Consent to talk with Ellis" note={data.consent_given
              ? 'You agreed. Ellis is an AI, not a lawyer. It saves the text of your chats, not the audio.'
              : "Not given. Ellis is an AI, not a lawyer, and saves the text of your chats, not the audio. It can't save your answers until you agree."}>
              <button type="button" className={`btn${data.consent_given ? '' : ' primary'}`} onClick={() => setConsent(!data.consent_given)}>{data.consent_given ? 'Withdraw' : 'I agree'}</button>
            </Setting>
            <Setting name="Sensitive numbers" note="You type them; they are never spoken. The AI only sees a placeholder." />
            <Setting name={<><Icon name="globe" />Language</>} note={`${dialects.find((d) => d.code === data.language)?.label ?? data.language}. Ellis talks with you in this language.`}>
              <button type="button" className="btn" aria-expanded={picking} onClick={() => setPicking(!picking)}>Change</button>
            </Setting>
            {picking && (
              <div className="btns enter" style={{ paddingTop: 12 }}>
                {dialects.map((d) => (
                  <button key={d.code} type="button" className={`btn md ${d.code === data.language ? 'primary' : ''}`} aria-pressed={d.code === data.language} onClick={() => setLanguage(d.code)}>{d.label}</button>
                ))}
              </div>
            )}
            <Setting name="Ellis's replies" note={`${{ short: 'Short', normal: 'Normal', detailed: 'Detailed' }[data.settings.reply_length as string] ?? data.settings.reply_length}. To change it, ask Ellis in the chat.`} />
            <Setting name="Ellis's voice speed" note={`${data.settings.voice_speed === 'slow' ? 'Slower' : 'Normal'}. To change it, ask Ellis in the chat.`} />
            <div className="btns" style={{ paddingTop: 20 }}>
              {data.packet_ready && <a href="/review" data-nav className="btn md">Download my packet</a>}
              <button type="button" className="btn md strong" onClick={logOut}>Sign out</button>
            </div>
          </div>
          <h2 id="advanced" className="h3 rule" style={{ marginTop: 28 }}>Advanced</h2>
          <div role="tablist" aria-label="Advanced" className="tabs" style={{ alignSelf: 'flex-start' }}>
            {tabs.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={t.id === tab} className="tab" onClick={() => setTab(t.id)}>{t.label}</button>
            ))}
          </div>
          <div key={tab} className="stack enter" style={{ gap: 20 }}>
            {tab === 'docs' && <>
              <div className="btns" style={{ gap: 12, alignItems: 'center', justifyContent: 'space-between' }}>
                <p className="soft" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 }}>
                  <Icon name="lock" />
                  {data.documents.length} document{data.documents.length === 1 ? '' : 's'} · only your clinic can open them
                </p>
                <button type="button" className="btn md primary" onClick={() => upload()}><Icon name="upload" />Upload</button>
              </div>
              <div className="stack">
                {data.gaps.map((g: any) => (
                  <div key={g.id} className="row" style={{ minHeight: 64, padding: '10px 0' }}>
                    <span className="stack" style={{ flex: '1 1 260px', gap: 2 }}>
                      <span style={{ fontSize: 17, fontWeight: 700 }}>{g.label}</span>
                      <span className="rust" style={{ fontSize: 15, fontWeight: 700 }}>Still needed</span>
                    </span>
                    <div className="btns">
                      <button type="button" className="btn ink" style={{ padding: '0 16px' }} onClick={() => upload(g.document_type)}>Upload</button>
                      <button type="button" className="btn" style={{ padding: '0 16px' }} onClick={() => decline(g.id)}>I don't have it</button>
                    </div>
                  </div>
                ))}
                {data.documents.map((d: any) => {
                  const [note, warn] = docNote(d)
                  return (
                    <div key={d.id} className="row" style={{ minHeight: 64, padding: '10px 0' }}>
                      <span className="stack" style={{ flex: '1 1 260px', gap: 2 }}>
                        <span style={{ fontSize: 17, fontWeight: 700 }}>{docName[d.document_type] ?? d.filename}</span>
                        <span className={warn ? 'rust' : 'soft'} style={{ fontSize: 15, fontWeight: warn ? 700 : undefined }}>{note}</span>
                      </span>
                      {warn && <button type="button" className="btn" style={{ padding: '0 16px' }} onClick={() => upload(d.document_type)}>Upload again</button>}
                    </div>
                  )
                })}
                {!data.documents.length && !data.gaps.length && <p className="soft" style={{ margin: 0, fontSize: 15 }}>No documents yet. Ellis will ask for them in the chat.</p>}
              </div>
            </>}

            {tab === 'case' && <>
              <dl className="stack" style={{ margin: 0 }}>
                {facts.map((f: any) => (
                  <div key={f.field} className="row" style={{ gap: '4px 16px', alignItems: 'baseline', padding: '18px 0' }}>
                    <dt className="soft" style={{ flex: '0 0 220px', fontSize: 15 }}>{f.label}</dt>
                    <dd style={{ margin: 0, flex: '1 1 260px', fontSize: 17, fontWeight: 700 }}>{f.corrected_from && <><s style={{ fontWeight: 400 }}>{f.corrected_from}</s> → </>}{f.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="soft" style={{ margin: 0, fontSize: 15, lineHeight: '22px' }}>{facts.length ? 'To change anything here, just tell Ellis in the chat.' : 'Your answers show up here as you give them in the chat.'}</p>
            </>}

            {tab === 'flags' && <>
              <p className="lead soft">Ellis isn't a lawyer. These are questions a person should decide.</p>
              {data.case_blocked && (
                <section className="panel">
                  <div className="stack" style={{ flex: '1 1 280px', gap: 4 }}>
                    <span className="label rust">Needs your clinic</span>
                    <span style={{ fontSize: 18, fontWeight: 700 }}>Your clinic will contact you.</span>
                    {data.clinic.phone && <span className="soft" style={{ fontSize: 15 }}>{data.clinic.name} · {data.clinic.phone}</span>}
                  </div>
                </section>
              )}
              {data.referrals.map((r: any, i: number) => r.variant === 'stop_now' ? (
                <section key={r.flag_id} className="panel">
                  <div className="stack" style={{ flex: '1 1 280px', gap: 4 }}>
                    <span className="label">F-{String(i + 1).padStart(2, '0')} · Needs you</span>
                    <span style={{ fontSize: 18, fontWeight: 700 }}>{r.title}</span>
                    <span className="soft" style={{ fontSize: 15 }}>{r.body}</span>
                    {(r.who || r.phone) && <span className="soft" style={{ fontSize: 15 }}>{[r.who, r.phone].filter(Boolean).join(' · ')}</span>}
                    {r.show_emergency && <strong className="rust" style={{ fontSize: 15 }}>If someone is in danger right now: call 911 or 988.</strong>}
                  </div>
                  <ProfessionalOptions reload={reload} lang={lang} />
                </section>
              ) : (
                <section key={r.flag_id} className="dark" style={{ flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Flag size={16} pole="#ffffff" />
                    <span className="label" style={{ color: 'var(--gold)' }}>F-{String(i + 1).padStart(2, '0')} · With your clinic{r.who ? ` · ${r.who}` : ''}</span>
                  </div>
                  <div style={{ fontSize: 20, lineHeight: '28px', fontWeight: 700 }}>{r.item || r.title}</div>
                  <p style={{ margin: 0, fontSize: 15, lineHeight: '22px', color: 'var(--on-ink-soft)' }}>
                    {r.title}.{r.prepare?.length ? ` What you can prepare: ${r.prepare.join(', ')}.` : ''}{r.phone ? ` Questions: ${r.phone}.` : ''}
                  </p>
                </section>
              ))}
              {data.reviewer_notes.map((n: any) => (
                <section key={n.id} className="panel">
                  <div className="stack" style={{ flex: '1 1 280px', gap: 4 }}>
                    <span className="label">Note from your clinic</span>
                    {n.label && <span style={{ fontSize: 18, fontWeight: 700 }}>{n.label}</span>}
                    <span className="soft" style={{ fontSize: 15 }}>{n.note}</span>
                  </div>
                </section>
              ))}
              {!flags && <p className="soft" style={{ margin: 0, fontSize: 15 }}>Nothing for a person to decide right now. If something comes up, Ellis will tell you in the chat.</p>}
            </>}
          </div>
        </div>
      </main>
    </Shell>
  )
}
