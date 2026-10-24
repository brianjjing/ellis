// Landing page for the demo: the clinic is the customer; applicants arrive by an expiring link.
export default function Home() {
  return (
    <div className="page col">
      <header className="top">
        <span className="wordmark">Ellis</span>
        <a href="/clinic" data-nav className="btn md strong">Clinic sign in</a>
      </header>
      <main className="signin">
        <div>
          <h1 className="display">Naturalization intake for small legal clinics</h1>
          <p className="lead soft">
            Applicants talk to a Spanish voice liaison at their own pace. AI staff build the case file. Your attorneys
            and accredited representatives review flagged items and approve. Ellis never files and never gives legal advice.
          </p>
          <div className="card">
            <div className="label">DEMO (SYNTHETIC DATA)</div>
            <p className="small">Clinic staff: admin@valle.demo, dana@valle.demo (reviewer), sam@valle.demo (intake). Password: ellis-demo</p>
            <div className="btns">
              <a className="btn md primary" href="/clinic" data-nav>Open the clinic workspace</a>
            </div>
            <p className="small">Applicant links (Spanish):</p>
            <div className="btns">
              <a className="btn" href="/a/demo-maria" data-nav>María (F1)</a>
              <a className="btn" href="/a/demo-jorge" data-nav>Jorge (F2)</a>
              <a className="btn" href="/a/demo-ana" data-nav>Ana Lucía (F3)</a>
              <a className="btn" href="/a/demo-rosa" data-nav>Rosa (F4)</a>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
