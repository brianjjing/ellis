// Minimal i18n for the applicant-facing chrome around and during the conversation. The conversation itself
// (questions, read-backs, flags) is driven by the backend in the chosen language; this covers the static
// screen text so the surrounding UI isn't stuck in Spanish when English is selected.
export type Lang = 'es' | 'en'

// Derive the UI language from a case's persisted locale (e.g. "en-US" -> 'en'). Defaults to Spanish for an
// unset/unrecognized locale, matching Case.language's own DB default.
export function langOf(data: { language?: string | null }): Lang {
  return (data.language || 'es-MX').startsWith('en') ? 'en' : 'es'
}

export const LANGUAGES: { code: Lang; label: string; dialects: { code: string; label: string }[] }[] = [
  { code: 'es', label: 'Español', dialects: [
    { code: 'es-MX', label: 'México' },
    { code: 'es-US', label: 'Estados Unidos' },
    { code: 'es-ES', label: 'España' },
  ] },
  { code: 'en', label: 'English', dialects: [
    { code: 'en-US', label: 'United States' },
    { code: 'en-GB', label: 'United Kingdom' },
  ] },
]

const STRINGS = {
  es: {
    chooseLanguage: 'Elija su idioma',
    chooseLanguageSub: 'Puede cambiarlo después si lo necesita.',
    chooseDialect: '¿De qué país?',
    continue: 'Continuar',
    preparedFor: 'Preparado para usted por',
    demoData: 'Datos de demostración',
    welcomeTitle: 'Prepare su solicitud de ciudadanía, hablando en español.',
    welcomeLine1: 'Le haré preguntas y usted contesta con su voz.',
    welcomeLine2: 'Usted revisa y firma todo. Nosotros no enviamos nada a USCIS.',
    welcomeLine3: 'Soy un asistente de inteligencia artificial, no un abogado. Su clínica revisa su caso.',
    startTalking: 'Empezar a hablar',
    howItWorks: '¿Cómo funciona?',
    micTitle: 'Su navegador le va a pedir usar el micrófono.',
    micSub: 'Toque «Permitir».',
    micContinue: 'Continuar',
    micDeniedTitle: 'Sin micrófono no podemos hablar.',
    micDeniedSub: 'Puede activarlo en la configuración de su navegador.',
    micRetry: 'Intentar otra vez',
    micSkip: 'Seguir sin micrófono (escribir)',
    endForToday: 'Terminar por hoy',
    endConfirm: '¿Terminar por hoy? Todo lo que dijo está guardado.',
    endYes: 'Sí, terminar',
    endNo: 'Seguir',
    typeInstead: 'Escribir en lugar de hablar',
    uploadDoc: 'Subir un documento',
    whatWeHave: 'Lo que tenemos',
    loading: 'Cargando…',
    linkExpired: 'Este enlace ya venció',
    couldNotOpen: 'No pudimos abrir su caso',
    tryAgain: 'Intentar otra vez',
  },
  en: {
    chooseLanguage: 'Choose your language',
    chooseLanguageSub: 'You can change it later if you need to.',
    chooseDialect: 'Which country?',
    continue: 'Continue',
    preparedFor: 'Prepared for you by',
    demoData: 'Demo data',
    welcomeTitle: 'Prepare your citizenship application, by talking.',
    welcomeLine1: "I'll ask you questions and you answer with your voice.",
    welcomeLine2: "You review and sign everything. We never submit anything to USCIS.",
    welcomeLine3: "I'm an AI assistant, not a lawyer. Your clinic reviews your case.",
    startTalking: 'Start talking',
    howItWorks: 'How does this work?',
    micTitle: 'Your browser is going to ask to use the microphone.',
    micSub: 'Tap "Allow."',
    micContinue: 'Continue',
    micDeniedTitle: "Without a microphone we can't talk.",
    micDeniedSub: 'You can turn it on in your browser settings.',
    micRetry: 'Try again',
    micSkip: 'Continue without a microphone (type)',
    endForToday: 'Finish for today',
    endConfirm: 'Finish for today? Everything you said is saved.',
    endYes: 'Yes, finish',
    endNo: 'Keep going',
    typeInstead: 'Type instead of talking',
    uploadDoc: 'Upload a document',
    whatWeHave: 'What we have',
    loading: 'Loading…',
    linkExpired: 'This link has expired',
    couldNotOpen: "We couldn't open your case",
    tryAgain: 'Try again',
  },
} as const

export type StringKey = keyof (typeof STRINGS)['es']

export function t(lang: Lang, key: StringKey): string {
  return STRINGS[lang][key] ?? STRINGS.es[key]
}
