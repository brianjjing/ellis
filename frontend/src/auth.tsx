// Who is signed in, from /api/auth/me: a guest, an applicant (with an account, or link-only), or clinic staff.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import { navigate } from './main'
import type { Me as StaffMe } from './clinic/ClinicApp'

export type Me =
  | { kind: 'guest' }
  | { kind: 'applicant'; account: { id: string; name: string; email: string } | null; case_id: string }
  | ({ kind: 'staff' } & StaffMe)

type Ctx = { me: Me | null; refresh: () => Promise<Me> }
const AuthCtx = createContext<Ctx>(null!)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const refresh = useCallback(() => api<Me>('/api/auth/me').catch((): Me => ({ kind: 'guest' })).then((m) => { setMe(m); return m }), [])
  useEffect(() => { refresh() }, [refresh])
  return <AuthCtx.Provider value={{ me, refresh }}>{children}</AuthCtx.Provider>
}

// Only same-origin paths: "/form" yes, "//evil.test" and "https://…" no.
export const safeNext = (raw: string | null, fallback: string) => (raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : fallback)

export const goSignIn = (next: string) => navigate(`/signin?next=${encodeURIComponent(next)}`)

// Where a fresh login lands: staff in the clinic workspace, applicants where they were headed.
export const landing = (me: Me, next: string | null) => navigate(me.kind === 'staff' ? '/clinic' : safeNext(next, '/'), true)

export async function signOut(refresh: () => Promise<Me>) {
  await api('/api/auth/logout', { body: {} })
  await refresh()
  navigate('/', true)
}
