import { Icon } from '../icons'
import { LANGUAGES, t, type Lang } from './i18n'

// First screen of a chat, under the centered box: suggested questions and what to have ready.
export function GuideStart({ lang, onChip }: { lang: Lang; onChip: (text: string) => void }) {
  const chips = [t(lang, 'chipProcess'), t(lang, 'chipDocs'), t(lang, 'chipInterview'), t(lang, 'chipEllis')]
  return <>
    <div className="btns">
      {chips.map((c) => <button key={c} type="button" className="btn" onClick={() => onChip(c)}>{c}</button>)}
    </div>
    <p className="small">{t(lang, 'fewSessions')} {t(lang, 'haveReady')}: {t(lang, 'greenCard')} · {t(lang, 'passport')}</p>
  </>
}

// The first screen's language picker: fixed bottom-right, opens upward. Render it outside .convo (its containment would trap position: fixed).
export function LangMenu({ lang, onLocale }: { lang: Lang; onLocale: (code: string) => void }) {
  return (
    <details className="more-menu lang-menu">
      <summary className="btn strong"><Icon name="globe" size={18} />{t(lang, 'chooseLanguage')}</summary>
      <div className="more-menu-body">
        {LANGUAGES.flatMap((l) => l.dialects.map((d) => (
          <button key={d.code} type="button" lang={d.code} className="btn" onClick={(e) => { onLocale(d.code); e.currentTarget.closest('details')?.removeAttribute('open') }}>{l.label} · {d.label}</button>
        )))}
      </div>
    </details>
  )
}
