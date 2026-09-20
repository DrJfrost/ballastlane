import { ApiError, toApiError } from './problemDetail'
import { tokenStorage, type TokenPair } from './tokenStorage'

/**
 * A thin fetch wrapper with one job beyond serialisation: transparently
 * refreshing an expired access token.
 *
 * Access tokens live 15 minutes, so a user on a dashboard will hit an expiry
 * mid-session. Without this, they would be bounced to the login screen while
 * still legitimately authenticated.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const API_PREFIX = '/api/v1'

type SessionExpiredListener = () => void

/**
 * Tracks the single in-flight refresh.
 *
 * Without this, a page that fires five queries on mount and gets five 401s
 * would start five refreshes. Four of them race, and because refresh tokens
 * are *rotated* server-side, the losers present an already-replaced token and
 * fail -- logging the user out precisely when the refresh was working. One
 * shared promise means the five callers all await the same round trip.
 */
let refreshInFlight: Promise<TokenPair> | null = null

const sessionExpiredListeners = new Set<SessionExpiredListener>()

export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener)
  return () => sessionExpiredListeners.delete(listener)
}

function notifySessionExpired(): void {
  tokenStorage.clear()
  for (const listener of sessionExpiredListeners) listener()
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Query parameters; `undefined` and `null` entries are dropped. */
  params?: Record<string, string | number | boolean | undefined | null | string[]>
  signal?: AbortSignal
  /** Skips the Authorization header and the refresh dance (login, register). */
  anonymous?: boolean
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(
    `${BASE_URL}${API_PREFIX}${path}`,
    typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
  )

  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      // Repeated keys, which is how the API accepts multi-valued filters:
      // ?status=todo&status=in_progress
      for (const item of value) url.searchParams.append(key, item)
    } else {
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function refreshTokens(): Promise<TokenPair> {
  const current = tokenStorage.read()
  if (!current) throw new Error('No refresh token available')

  const response = await fetch(buildUrl('/auth/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: current.refreshToken }),
  })

  if (!response.ok) throw await toApiError(response)

  const body = (await response.json()) as {
    access_token: string
    refresh_token: string
  }
  const tokens: TokenPair = {
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
  }
  tokenStorage.write(tokens)
  return tokens
}

function refreshOnce(): Promise<TokenPair> {
  refreshInFlight ??= refreshTokens().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

async function send(
  path: string,
  options: RequestOptions,
  accessToken: string | null,
): Promise<Response> {
  const headers: Record<string, string> = {}
  // Bracket notation is required for a hyphenated header name.
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  return fetch(buildUrl(path, options.params), {
    method: options.method ?? 'GET',
    headers,
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    ...(options.signal ? { signal: options.signal } : {}),
  })
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const tokens = options.anonymous ? null : tokenStorage.read()
  let response = await send(path, options, tokens?.accessToken ?? null)

  if (response.status === 401 && !options.anonymous && tokens) {
    try {
      const refreshed = await refreshOnce()
      response = await send(path, options, refreshed.accessToken)
    } catch {
      // The refresh token is gone or rejected: this really is a logout.
      notifySessionExpired()
      throw await toApiError(response)
    }
  }

  if (!response.ok) {
    const error = await toApiError(response)
    if (error.isAuthError && !options.anonymous) notifySessionExpired()
    throw error
  }

  // 204 No Content has no body to parse.
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, params?: RequestOptions['params'], signal?: AbortSignal) =>
    request<T>(path, {
      ...(params ? { params } : {}),
      ...(signal ? { signal } : {}),
    }),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', ...(body !== undefined ? { body } : {}) }),

  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body }),

  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body }),

  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),

  /** For login and register, which must not send a stale token. */
  anonymousPost: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body, anonymous: true }),
}

export { ApiError }
