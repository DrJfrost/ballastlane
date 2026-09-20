import { Spinner } from '@/components/ui'
import { AppShell } from '@/components/AppShell'
import { LoginPage } from '@/features/auth/LoginPage'
import { useAuth } from '@/features/auth/useAuth'
import { TasksPage } from '@/features/tasks/TasksPage'

/**
 * Three states, kept explicit.
 *
 * The middle one matters: while the stored token is being verified the app is
 * neither logged in nor logged out. Collapsing it into "not logged in" makes
 * the login screen flash on every refresh for an already-authenticated user.
 */
export function App() {
  const { user, isBootstrapping } = useAuth()

  if (isBootstrapping) {
    return (
      <div className="bg-surface flex min-h-full items-center justify-center">
        <Spinner size={24} label="Restoring your session" />
      </div>
    )
  }

  if (!user) return <LoginPage />

  return (
    <AppShell>
      <TasksPage />
    </AppShell>
  )
}
