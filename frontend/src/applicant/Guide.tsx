import { LANGUAGES, t, type Lang } from './i18n'

// First screen of a chat: language, what to have ready, and a way to start. No blank box.
export function GuideStart({ lang, onLocale, onTalk, onType, onChip }: {
  lang: Lang
  onLocale: (code: string) => void
  onTalk: () => void
  onType: () => void
  onChip: (text: string) => void
}) {
  const chips = [t(lang, 'chipProcess'), t(lang, 'chipDocs'), t(lang, 'chipInterview'), t(lang, 'chipEllis')]
  return (
    <section className="guide">
      <p className="lead">{t(lang, 'fewSessions')}</p>
      <p className="label">{t(lang, 'chooseLanguage')}</p>
      <div className="btns">
        {LANGUAGES.flatMap((l) => l.dialects).map((d) => (
          <button key={d.code} type="button" className="btn" onClick={() => onLocale(d.code)}>{lLabel(d.code, d.label)}</button>
        ))}
      </div>
      <p className="label">{t(lang, 'haveReady')}</p>
      <p>{t(lang, 'greenCard')} · {t(lang, 'passport')}</p>
      <div className="btns">
        <button type="button" className="btn lg primary" onClick={onTalk}>{t(lang, 'startTalking')}</button>
        <button type="button" className="btn" onClick={onType}>{t(lang, 'typeInsteadShort')}</button>
      </div>
      <div className="btns">
        {chips.map((c) => <button key={c} type="button" className="btn" onClick={() => onChip(c)}>{c}</button>)}
      </div>
    </section>
  )
}

function lLabel(code: string, place: string) {
  return `${code.startsWith('es') ? 'Español' : 'English'} · ${place}`
}
