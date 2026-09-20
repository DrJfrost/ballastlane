import { createContext } from 'react'
import type { CurrentUser } from '@/features/tasks/types'

/**
 * The context object, kept in its own module.
 *
 * A file that exports both a context and a component cannot be hot-replaced
 * by React Fast Refresh -- editing the provider reloads the whole page and
 * loses the session you were testing. Splitting them is a two-line change
 * that keeps the dev loop fast.
 */
export interface AuthState {
  user: CurrentUser | null
  /** True until the stored token has been validated against the API. */
  isBootstrapping: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, fullName: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)
