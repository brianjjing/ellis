import { useState, type ReactNode } from 'react'
import Shell from './Shell'
import { Flag, Icon } from './icons'

const tabs = [
  { id: 'docs', label: 'Documents' },
  { id: 'case', label: 'Case details' },
  { id: 'flags', label: 'Attorney' },
  { id: 'privacy', label: 'Account' },
]

const docs = [
  { name: 'Passport', note: 'Used for Parts 2 and 9', sensitive: true },
  { name: 'Green card', note: 'Used for Parts 1 and 2', sensitive: true },
  { name: 'Birth certificate', note: 'Needs a certified English translation', sensitive: true, warn: true },
  { name: 'Marriage certificate', note: 'Used for Part 6', sensitive: true },
  { name: '2024 tax return', note: 'Used for Parts 4 and 8' },
  { name: 'Flight receipts, Mexico 2023', note: 'Shared with your attorney' },
]

const facts = [
  ['A-Number', 'A-123-456-789'],
  ['Green card since', 'Feb 2, 2022'],
  ['Path', '5 years as a resident'],
  ['Earliest day to file', 'Nov 4, 2026'],
  ['Home address', '418 Elm St, Apt 3B, Queens, NY'],
  ['Spouse', 'Daniel Alvarez, U.S. citizen'],
]

const signIns = [
  { name: 'This laptop', note: 'Passkey · signed in now', action: <span className="status green">This device</span> },
  { name: "Maria's phone", note: 'Passkey · last used Oct 22', action: <button type="button" className="btn danger">Remove</button> },
  { name: 'Backup: email code', note: 'If you lose your devices', action: <button type="button" className="btn">Add a passkey</button> },
]

const privacy = [
  { name: 'Lock sensitive documents', note: 'Ask for your passkey again after 15 minutes', action: 'Change' },
  { name: 'Who opened your documents', note: 'Last: Ellis read your passport, Oct 24', action: 'See log' },
  { name: 'Language', note: 'English. Ellis understands any language.', action: 'Change' },
]

function Setting({ name, note, children }: { name: string; note: string; children: ReactNode }) {
  return (
    <div className="row" style={{ minHeight: 64, padding: '10px 0' }}>
      <span className="stack" style={{ flex: '1 1 260px' }}>
        <span style={{ fontSize: 17, fontWeight: 700 }}>{name}</span>
        <span className="soft" style={{ fontSize: 15 }}>{note}</span>
      </span>
      {children}
    </div>
  )
}

export default function Advanced() {
  const [tab, setTab] = useState('docs')
  const [dialog, setDialog] = useState(false)
  const [unlocked, setUnlocked] = useState(false)

  return (
    <Shell active="advanced">
      <main className="main">
        <header className="bar">
          <h1 className="h1">Advanced</h1>
          <div role="tablist" aria-label="Sections" className="tabs">
            {tabs.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={t.id === tab} className="tab" onClick={() => setTab(t.id)}>{t.label}</button>
            ))}
          </div>
        </header>

        <div key={tab} className="content enter" style={{ padding: '40px 24px 48px', gap: 20 }}>
          {tab === 'docs' && <>
            <div className="btns" style={{ gap: 12, alignItems: 'center', justifyContent: 'space-between' }}>
              <p className="soft" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 }}>
                <Icon name="lock" />
                {unlocked ? 'Unlocked for 15 minutes' : '4 sensitive documents are locked'}
              </p>
              <button type="button" className="btn md primary"><Icon name="upload" />Upload</button>
            </div>
            <div className="stack">
              {docs.map((d) => (
                <div key={d.name} className="row" style={{ minHeight: 64, padding: '10px 0' }}>
                  <span className="stack" style={{ flex: '1 1 260px', gap: 2 }}>
                    <span style={{ fontSize: 17, fontWeight: 700 }}>{d.name}</span>
                    <span className={d.warn ? 'rust' : 'soft'} style={{ fontSize: 15, fontWeight: d.warn ? 700 : undefined }}>{d.note}</span>
                  </span>
                  {d.sensitive && !unlocked
                    ? <button type="button" className="btn ink" style={{ padding: '0 16px' }} onClick={() => setDialog(true)}>Unlock</button>
                    : <button type="button" className="btn" style={{ padding: '0 16px' }}>View</button>}
                </div>
              ))}
            </div>
          </>}

          {tab === 'case' && <>
            <dl className="stack" style={{ margin: 0 }}>
              {facts.map(([k, v]) => (
                <div key={k} className="row" style={{ gap: '4px 16px', alignItems: 'baseline', padding: '18px 0' }}>
                  <dt className="soft" style={{ flex: '0 0 220px', fontSize: 15 }}>{k}</dt>
                  <dd style={{ margin: 0, flex: '1 1 260px', fontSize: 17, fontWeight: 700 }}>{v}</dd>
                </div>
              ))}
            </dl>
            <p className="soft" style={{ margin: 0, fontSize: 15, lineHeight: '22px' }}>To change anything here, just tell Ellis in the chat.</p>
          </>}

          {tab === 'flags' && <>
            <p className="lead soft">Ellis isn't a lawyer. These are questions a person should decide.</p>
            <section className="dark" style={{ flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Flag size={16} pole="#ffffff" />
                <span className="label" style={{ color: 'var(--gold)' }}>F-01 · WITH ATTORNEY · REPLY BY OCT 29</span>
              </div>
              <div style={{ fontSize: 20, lineHeight: '28px', fontWeight: 700 }}>Mexico trip of 217 days</div>
              <p style={{ margin: 0, fontSize: 15, lineHeight: '22px', color: 'var(--on-ink-soft)' }}>A trip over 6 months can raise a question about continuous residence. Your attorney is checking whether your proof is enough.</p>
            </section>
            <section className="panel">
              <div className="stack" style={{ flex: '1 1 280px', gap: 4 }}>
                <span className="label">F-02 · NEEDS YOU</span>
                <span style={{ fontSize: 18, fontWeight: 700 }}>Traffic ticket from 2019</span>
                <span className="soft" style={{ fontSize: 15 }}>Send it to an attorney, or ask for free legal help.</span>
              </div>
              <button type="button" className="btn md primary">Send for review</button>
            </section>
          </>}

          {tab === 'privacy' && <>
            <section aria-labelledby="profile" className="panel" style={{ gap: 16 }}>
              <span aria-hidden="true" className="avatar" style={{ flex: '0 0 56px', height: 56, borderRadius: 6, fontSize: 26, lineHeight: '56px' }}>M</span>
              <div className="stack" style={{ flex: '1 1 240px', gap: 2 }}>
                <h2 id="profile" style={{ margin: 0, fontSize: 19, lineHeight: '24px', fontWeight: 700 }}>Maria Alvarez</h2>
                <span className="soft" style={{ fontSize: 15 }}>maria@example.com · (555) 014-2290</span>
              </div>
              <button type="button" className="btn">Edit</button>
            </section>
            <h3 className="h3 rule" style={{ marginTop: 12 }}>How you sign in</h3>
            <div className="stack" style={{ marginTop: -20 }}>
              {signIns.map((s) => <Setting key={s.name} name={s.name} note={s.note}>{s.action}</Setting>)}
            </div>
            <h3 className="h3 rule" style={{ marginTop: 12 }}>Privacy</h3>
            <div className="stack" style={{ marginTop: -20 }}>
              {privacy.map((s) => <Setting key={s.name} name={s.name} note={s.note}><button type="button" className="btn">{s.action}</button></Setting>)}
              <div className="btns" style={{ paddingTop: 20 }}>
                <button type="button" className="btn md">Download all my data</button>
                <button type="button" className="btn md danger">Delete my account</button>
                <a href="#/signin" className="btn md strong">Sign out</a>
              </div>
            </div>
          </>}
        </div>
      </main>

      {dialog && (
        // Native modal: focus trap, Esc to close and an inert page behind it, for free.
        <dialog ref={(d) => { if (d && !d.open) d.showModal() }} onClose={() => setDialog(false)} aria-labelledby="unlock-title" className="dialog enter">
          <h2 id="unlock-title" className="h1">Confirm it's you</h2>
          <p className="soft" style={{ margin: 0, fontSize: 16, lineHeight: '26px' }}>You're signed in as maria@example.com. To open sensitive documents, use your passkey once more. They lock again after 15 minutes.</p>
          <button type="button" className="btn lg primary" onClick={() => { setDialog(false); setUnlocked(true) }}>Use passkey</button>
          <button type="button" className="btn md" onClick={() => setDialog(false)}>Cancel</button>
        </dialog>
      )}
    </Shell>
  )
}
