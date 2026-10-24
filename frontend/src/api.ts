// Thin fetch/WebSocket helpers for the Case API. Cookies carry auth (httpOnly), so every call is same-origin.

export class ApiError extends Error {
  code: string
  status: number
  details: any
  constructor(status: number, code: string, message: string, details?: any) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.body || opts.form ? 'POST' : 'GET'), credentials: 'same-origin' }
  if (opts.form) init.body = opts.form
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const r = await fetch(path, init)
  const text = await r.text()
  const data = text ? JSON.parse(text) : {}
  if (!r.ok) {
    const e = data.error ?? {}
    throw new ApiError(r.status, e.code ?? 'error', e.message ?? r.statusText, e.failing ?? e.details)
  }
  return data as T
}

export function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}`
}

// Reconnecting event stream: calls onMessage for each JSON message.
export function stream(path: string, onMessage: (m: any) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 500
  const open = () => {
    ws = new WebSocket(wsUrl(path))
    ws.onmessage = (e) => {
      retry = 500
      try { onMessage(JSON.parse(e.data)) } catch { /* ignore */ }
    }
    ws.onclose = () => {
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 8000)))
    }
  }
  open()
  return () => { closed = true; ws?.close() }
}

export function debounce<F extends (...a: any[]) => void>(f: F, ms: number) {
  let t: ReturnType<typeof setTimeout> | undefined
  return (...a: Parameters<F>) => {
    clearTimeout(t)
    t = setTimeout(() => f(...a), ms)
  }
}

export const fmtTime = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—')
