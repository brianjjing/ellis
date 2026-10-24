import { useState } from 'react'
import { Icon } from './icons'

export default function SignIn() {
  const [step, setStep] = useState<'start' | 'code' | 'new'>('start')
  const toStart = () => setStep('start')

  return (
    <div className="page col">
      <header className="top">
        <span className="wordmark">Ellis</span>
        <button type="button" className="btn"><Icon name="globe" />English</button>
      </header>

      <main className="signin">
        <div key={step} className="enter">
          {step === 'start' && <>
            <h1 className="display">Sign in to Ellis</h1>
            <p className="lead soft pull">Your forms and documents are private. Only you can open them.</p>
            <div className="card">
              <label htmlFor="email" className="field">Email</label>
              <input id="email" type="email" autoComplete="email" defaultValue="maria@example.com" className="input" />
              <a href="#/chat" className="btn lg primary"><Icon name="lock" />Sign in with passkey</a>
              <button type="button" className="btn" style={{ height: 48, fontSize: 15 }} onClick={() => setStep('code')}>Email me a code instead</button>
              <p className="small">A passkey uses your face, fingerprint or phone screen lock. No password to remember.</p>
            </div>
            <p className="switch">New to Ellis? <button type="button" className="link-btn" onClick={() => setStep('new')}>Create an account</button></p>
          </>}

          {step === 'code' && <>
            <h1 className="display">Check your email</h1>
            <p className="lead soft pull">We sent a 6-digit code to maria@example.com. It works for 10 minutes.</p>
            <div className="card">
              <label htmlFor="code" className="field">Code</label>
              <input id="code" type="text" inputMode="numeric" autoComplete="one-time-code" placeholder="000000" className="input code" />
              <a href="#/chat" className="btn lg primary">Sign in</a>
              <div className="btns" style={{ justifyContent: 'space-between' }}>
                <button type="button" className="link-btn" style={{ height: 40, fontSize: 15 }}>Send a new code</button>
                <button type="button" className="btn" onClick={toStart}>Back</button>
              </div>
            </div>
          </>}

          {step === 'new' && <>
            <h1 className="display">Create your account</h1>
            <p className="lead soft pull">It's free. About 1 minute. Your documents stay locked to you.</p>
            <div className="card">
              <label htmlFor="name" className="field">Your name</label>
              <input id="name" type="text" autoComplete="name" className="input" />
              <label htmlFor="new-email" className="field">Email</label>
              <input id="new-email" type="email" autoComplete="email" className="input" />
              <label htmlFor="phone" className="field">Phone <span className="soft" style={{ fontWeight: 400 }}>(for reminders, optional)</span></label>
              <input id="phone" type="tel" autoComplete="tel" className="input" />
              <a href="#/chat" className="btn lg primary"><Icon name="lock" />Create account with passkey</a>
              <p className="small">Ellis is not a law firm and is not part of USCIS. We never share your information without asking you.</p>
            </div>
            <p className="switch">Already have an account? <button type="button" className="link-btn" onClick={toStart}>Sign in</button></p>
          </>}
        </div>
      </main>
    </div>
  )
}
