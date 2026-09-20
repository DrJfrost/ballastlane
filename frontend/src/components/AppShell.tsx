import type { ReactNode } from 'react'
import { Button } from '@/components/ui'
import { useAuth } from '@/features/auth/useAuth'

/** Header, main landmark and the sign-out control. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-full">
      {/* First tab stop, so a keyboard user can jump past the header. */}
      <a
        href="#main"
        className="sr-only-focusable bg-brand fixed left-4 top-4 z-50 rounded-lg px-4 py-2 text-sm font-medium text-white"
      >
        Skip to content
      </a>

      <header className="border-border sticky top-0 z-30 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="bg-brand grid h-8 w-8 place-items-center rounded-lg text-sm font-bold text-white"
            >
              T
            </span>
            <span className="text-ink text-base font-semibold">TaskFlow</span>
          </div>

          {user ? (
            <div className="flex items-center gap-3">
              <div className="hidden text-right sm:block">
                <p className="text-ink text-sm font-medium leading-tight">
                  {user.full_name}
                </p>
                <p className="text-ink-subtle text-xs leading-tight">{user.email}</p>
              </div>
              <span
                aria-hidden="true"
                className="bg-brand/10 text-brand grid h-8 w-8 place-items-center rounded-full text-xs font-semibold"
              >
                {user.initials}
              </span>
              <Button variant="secondary" size="sm" onClick={logout}>
                Sign out
              </Button>
            </div>
          ) : null}
        </div>
      </header>

      <main id="main" className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {children}
      </main>
    </div>
  )
}
