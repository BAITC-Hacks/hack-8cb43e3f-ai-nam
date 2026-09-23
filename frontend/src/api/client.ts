// HTTP-клиент. Токены рабочей области и панели администратора хранятся раздельно:
// вход в админ-панель — отдельный, и его токен не даёт доступа к рабочей области (и наоборот).

export type Scope = 'app' | 'admin'

const KEYS: Record<Scope, string> = { app: 'orgai.token', admin: 'orgai.admin.token' }

export const tokens = {
  get: (scope: Scope) => localStorage.getItem(KEYS[scope]),
  set: (scope: Scope, t: string) => localStorage.setItem(KEYS[scope], t),
  clear: (scope: Scope) => localStorage.removeItem(KEYS[scope]),
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; scope?: Scope; raw?: boolean }

const listeners: Record<Scope, Array<() => void>> = { app: [], admin: [] }
export const onUnauthorized = (scope: Scope, fn: () => void) => {
  listeners[scope].push(fn)
  return () => {
    listeners[scope] = listeners[scope].filter((x) => x !== fn)
  }
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const scope = opts.scope || 'app'
  const headers: Record<string, string> = {}
  const token = tokens.get(scope)
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await fetch(`/api${path}`, { method: opts.method || (body ? 'POST' : 'GET'), headers, body })
  if (res.status === 401 && token) {
    tokens.clear(scope)
    listeners[scope].forEach((f) => f())
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map((d: any) => d.msg).join('; ') : msg
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg || `HTTP ${res.status}`)
  }
  if (opts.raw) return res as unknown as T
  if (res.status === 204) return undefined as T
  return res.json()
}

/** Скачивание файла с авторизацией (имя берётся из Content-Disposition). */
export async function download(path: string, fallbackName = 'file', scope: Scope = 'app') {
  const res = await api<Response>(path, { raw: true, scope })
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="?([^";]+)"?/.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export async function fetchImage(path: string): Promise<string> {
  const res = await api<Response>(path, { raw: true })
  return URL.createObjectURL(await res.blob())
}
