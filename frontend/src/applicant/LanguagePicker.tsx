import { languageOf, t, useLanguages, type Lang } from './i18n'

// The language Ellis talks in, then the accent when the language has more than one (Cartesia's locales). Each
// language is listed in its own name. Picking a language picks its first accent; onChange gets the locale.
export function LanguagePicker({ value, lang, onChange }: { value: string; lang: Lang; onChange: (locale: string) => void }) {
  const list = useLanguages()
  const cur = languageOf(list, value)
  if (!list.length) return <p className="small soft">{t(lang, 'loading')}</p>
  return (
    <div className="stack" style={{ gap: 8 }}>
      <label className="field">
        {t(lang, 'chooseLanguage')}
        <select className="input" value={cur?.code ?? ''} onChange={(e) => {
          const l = list.find((x) => x.code === e.target.value)
          if (l) onChange(l.locales[0].code)
        }}>
          {!cur && <option value="" disabled>{value}</option>}
          {list.map((l) => (
            <option key={l.code} value={l.code} lang={l.code}>{l.native === l.name ? l.native : `${l.native} · ${l.name}`}</option>
          ))}
        </select>
      </label>
      {cur && cur.locales.length > 1 && (
        <label className="field">
          {t(lang, 'chooseDialect')}
          <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
            {cur.locales.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.label ?? l.code}</option>)}
          </select>
        </label>
      )}
      {cur && !cur.voice_input && (
        <p className="small soft">
          {lang === 'es'
            ? `Ellis todavía no puede escuchar ${cur.native} hablado: escriba sus respuestas. Ellis sí le habla en ${cur.native}.`
            : `Ellis can't hear spoken ${cur.name} yet: type your answers. Ellis still talks to you in ${cur.name}.`}
        </p>
      )}
      {cur && cur.copy_lang !== cur.code && (
        <p className="small soft">
          {lang === 'es'
            ? `Ellis habla con usted en ${cur.native}. Los botones y las pantallas siguen en inglés.`
            : `Ellis talks with you in ${cur.name}. Buttons and screens stay in English.`}
        </p>
      )}
    </div>
  )
}
