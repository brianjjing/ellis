// Minimal i18n for the applicant-facing chrome around and during the conversation. Ellis talks in every language
// Cartesia's Sonic speaks (the list comes from GET /api/languages, backend/config/languages.yaml); this screen text
// exists in Spanish and English only, so every language but Spanish reads English here.
import { useEffect, useState } from 'react'
import { api } from '../api'

export type Lang = 'es' | 'en'

// The screen-text language for a case's persisted locale ("es-MX" -> 'es', "fr-CA" -> 'en'). Defaults to English for
// an unset locale, matching Case.language's own DB default.
export function langOf(data: { language?: string | null }): Lang {
  return (data.language || 'en-US').startsWith('es') ? 'es' : 'en'
}

export type Language = {
  code: string; name: string; native: string; rtl: boolean; voice_input: boolean; copy_lang: Lang
  locales: { code: string; label: string | null }[]
}

let languages: Promise<Language[]> | null = null
export function loadLanguages(): Promise<Language[]> {
  languages ??= api<{ languages: Language[] }>('/api/languages').then((r) => r.languages)
    .catch((e) => { languages = null; throw e })
  return languages
}

// Every language and accent Ellis talks in ([] until loaded).
export function useLanguages(): Language[] {
  const [list, setList] = useState<Language[]>([])
  useEffect(() => { loadLanguages().then(setList).catch(() => undefined) }, [])
  return list
}

export function languageOf(list: Language[], locale?: string | null): Language | undefined {
  const base = (locale || '').split(/[-_]/)[0].toLowerCase()
  return list.find((l) => l.code === base)
}

// "Français (Canada)", "Tiếng Việt"; native: false gives the English name ("French (Canada)").
export function localeName(list: Language[], locale?: string | null, native = true): string {
  const l = languageOf(list, locale)
  if (!l) return locale || ''
  const label = l.locales.length > 1 ? l.locales.find((x) => x.code === locale)?.label : null
  const name = native ? l.native : l.name
  return label ? `${name} (${label})` : name
}

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
    fewSessions: 'Esto toma unas sesiones cortas. Puede parar cuando quiera.',
    haveYour: 'Tenga a mano su',
    andYour: 'y su',
    greenCard: 'Tarjeta de residente',
    passport: 'Pasaporte',
    chipProcess: '¿Cómo funciona la solicitud?',
    chipDocs: '¿Qué documentos necesito?',
    chipInterview: '¿Qué es la entrevista?',
    chipEllis: '¿Qué es Ellis?',
    signInToTalk: 'Inicie sesión para hablar con Ellis',
    micHint: '¡Use el botón del micrófono para hablar o parar!',
    stop: 'Parar',
    talk: 'Hablar',
    typeWord: 'Escribir',
    connecting: 'Conectando…',
    listening: 'Escuchando…',
    thinking: 'Pensando…',
    ellisSpeaking: 'Ellis está hablando',
    paused: 'En pausa',
    voiceEnded: 'Terminó',
    iAgree: 'Estoy de acuerdo',
    notNow: 'Ahora no',
    consentLater: 'Puede estar de acuerdo cuando quiera. Ellis no guarda respuestas hasta entonces.',
    chatWithEllis: 'Hablar con Ellis',
    logIn: 'Iniciar sesión',
    signUp: 'Crear cuenta',
    you: 'Usted',
    ellis: 'Ellis',
    saveAccount: 'Cree una cuenta gratis para guardar esta conversación y empezar su N-400.',
  },
  en: {
    chooseLanguage: 'Choose language',
    chooseLanguageSub: 'You can change it later if you need to.',
    chooseDialect: 'Which country?',
    continue: 'Continue',
    preparedFor: 'Prepared for you by',
    demoData: 'Demo data',
    welcomeTitle: 'Prepare your citizenship application, by talking.',
    welcomeLine1: "I'll ask you questions and you answer with your voice.",
    welcomeLine2: "You review and sign everything. We never submit anything to USCIS.",
    welcomeLine3: "I'm an AI assistant, not a lawyer. Your clinic reviews your case.",
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
    fewSessions: 'This takes a few short sessions. You can stop whenever you want.',
    haveYour: 'Have your',
    andYour: 'and',
    greenCard: 'Green card',
    passport: 'Passport',
    chipProcess: 'How does applying work?',
    chipDocs: 'What documents do I need?',
    chipInterview: 'What is the interview?',
    chipEllis: 'What is Ellis?',
    signInToTalk: 'Sign in to talk with Ellis',
    micHint: 'Toggle speaking on/off with the mic button!',
    stop: 'Stop',
    talk: 'Talk',
    typeWord: 'Type',
    connecting: 'Connecting…',
    listening: 'Listening…',
    thinking: 'Thinking…',
    ellisSpeaking: 'Ellis is speaking',
    paused: 'Paused',
    voiceEnded: 'Paused or ended',
    iAgree: 'I agree',
    notNow: 'Not now',
    consentLater: 'You can agree whenever you are ready. Ellis will not save answers until you do.',
    chatWithEllis: 'Chat with Ellis',
    logIn: 'Log in',
    signUp: 'Sign up',
    you: 'You',
    ellis: 'Ellis',
    saveAccount: 'Create a free account to save this conversation and start your N-400.',
  },
} as const

export type StringKey = keyof (typeof STRINGS)['es']

export function t(lang: Lang, key: StringKey): string {
  return STRINGS[lang][key] ?? STRINGS.es[key]
}
