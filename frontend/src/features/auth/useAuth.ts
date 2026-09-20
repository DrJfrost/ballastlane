import { useContext } from 'react'
import { AuthContext } from './authContext'

/**
 * Throws when used outside the provider rather than returning `null`.
 *
 * A nullable return pushes an `if (!auth) return null` into every consumer;
 * an explicit failure points straight at the missing provider.
 */
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return context
}
