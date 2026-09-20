import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, onSessionExpired } from '@/lib/apiClient'
import { tokenStorage } from '@/lib/tokenStorage'
import type { CurrentUser } from '@/features/tasks/types'
import { AuthContext, type AuthState } from './authContext'

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isBootstrapping, setBootstrapping] = useState(true)

  const logout = useCallback(() => {
    tokenStorage.clear()
    setUser(null)
  }, [])

  /**
   * On boot, a stored token is *verified* rather than trusted.
   *
   * The token could be expired, signed with a rotated key, or belong to an
   * account that has since been deactivated. Decoding it client-side would
   * happily accept all three and show a dashboard whose every request then
   * fails with a 401.
   */
  useEffect(() => {
    let cancelled = false

    async function restore() {
      if (!tokenStorage.read()) {
        setBootstrapping(false)
        return
      }
      try {
        const current = await api.get<CurrentUser>('/auth/me')
        if (!cancelled) setUser(current)
      } catch {
        if (!cancelled) tokenStorage.clear()
      } finally {
        if (!cancelled) setBootstrapping(false)
      }
    }

    void restore()
    return () => {
      cancelled = true
    }
  }, [])

  /**
   * The API client cannot import this context (that would be a cycle), so it
   * announces an unrecoverable 401 through a subscription and the provider
   * turns that into a logout.
   */
  useEffect(() => onSessionExpired(() => setUser(null)), [])

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.anonymousPost<TokenResponse>('/auth/login', {
      email,
      password,
    })
    tokenStorage.write({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
    })
    setUser(await api.get<CurrentUser>('/auth/me'))
  }, [])

  const register = useCallback(
    async (email: string, fullName: string, password: string) => {
      await api.anonymousPost('/auth/register', {
        email,
        full_name: fullName,
        password,
      })
      // Register deliberately does not return tokens, so sign in afterwards:
      // one code path issues credentials, which is one place to audit.
      await login(email, password)
    },
    [login],
  )

  const value = useMemo<AuthState>(
    () => ({ user, isBootstrapping, login, register, logout }),
    [user, isBootstrapping, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
