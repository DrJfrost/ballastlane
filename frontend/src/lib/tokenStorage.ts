/**
 * Token persistence.
 *
 * `localStorage` is used knowingly. The genuinely secure option is an
 * httpOnly, SameSite cookie, which JavaScript cannot read and therefore
 * cannot leak to an XSS payload -- but that requires the API to set cookies
 * and a CSRF strategy, which is a backend change beyond this exercise. It is
 * a knowing compromise, not an accident; the README records it alongside the
 * other trade-offs.
 *
 * The mitigation that *is* in place: access tokens live 15 minutes, so a
 * stolen one has a short useful life.
 */

const ACCESS_KEY = 'taskflow.access_token'
const REFRESH_KEY = 'taskflow.refresh_token'

export interface TokenPair {
  accessToken: string
  refreshToken: string
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    // Safari in private mode throws on access. Treat it as "not logged in"
    // rather than crashing the whole app on boot.
    return null
  }
}

export const tokenStorage = {
  read(): TokenPair | null {
    const accessToken = safeGet(ACCESS_KEY)
    const refreshToken = safeGet(REFRESH_KEY)
    if (!accessToken || !refreshToken) return null
    return { accessToken, refreshToken }
  },

  write(tokens: TokenPair): void {
    try {
      window.localStorage.setItem(ACCESS_KEY, tokens.accessToken)
      window.localStorage.setItem(REFRESH_KEY, tokens.refreshToken)
    } catch {
      // Storage unavailable: the session still works until the tab closes.
    }
  },

  clear(): void {
    try {
      window.localStorage.removeItem(ACCESS_KEY)
      window.localStorage.removeItem(REFRESH_KEY)
    } catch {
      /* nothing to clean up */
    }
  },
}
