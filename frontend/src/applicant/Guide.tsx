import { Icon } from '../icons'
import { LANGUAGES, t, type Lang } from './i18n'

// First screen of a chat, under the centered box: suggested questions.
export function GuideStart({ lang, onChip }: { lang: Lang; onChip: (text: string) => void }) {
  const chips = [t(lang, 'chipProcess'), t(lang, 'chipDocs'), t(lang, 'chipInterview'), t(lang, 'chipEllis')]
  return (
    <div className="btns">
      {chips.map((c) => <button key={c} type="button" className="btn sm" onClick={() => onChip(c)}>{c}</button>)}
    </div>
  )
}

// First screen's footer, last in .convo: what to have ready (bottom middle) and the language picker (bottom right, opens upward).
export function GuideFoot({ lang, onLocale }: { lang: Lang; onLocale: (code: string) => void }) {
  return (
    <div className="guide-foot">
      <p className="small">
        {t(lang, 'fewSessions')} {t(lang, 'haveYour')} <strong>{t(lang, 'greenCard').toLowerCase()}</strong> {t(lang, 'andYour')} <strong>{t(lang, 'passport').toLowerCase()}</strong>.
      </p>
      <details className="more-menu lang-menu">
        <summary className="btn strong"><Icon name="globe" size={18} />{t(lang, 'chooseLanguage')}</summary>
        <div className="more-menu-body">
          {LANGUAGES.flatMap((l) => l.dialects.map((d) => (
            <button key={d.code} type="button" lang={d.code} className="btn" onClick={(e) => { onLocale(d.code); e.currentTarget.closest('details')?.removeAttribute('open') }}>{l.label} · {d.label}</button>
          )))}
        </div>
      </details>
    </div>
  )
}
