import { useState, type FormEvent } from 'react'
import { Alert, Button, Field, Input } from '@/components/ui'
import { errorMessage } from '@/lib/problemDetail'
import { useAuth } from './useAuth'

type Mode = 'login' | 'register'

/** Filled from the seeded dataset so a reviewer can sign in immediately. */
const DEMO = { email: 'ada@taskflow.dev', password: 'DemoPassw0rd!2026' }

export function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
      } else {
        await register(email.trim(), fullName.trim(), password)
      }
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setSubmitting(false)
    }
  }

  function useDemoAccount() {
    setMode('login')
    setEmail(DEMO.email)
    setPassword(DEMO.password)
    setError(null)
  }

  return (
    <main className="bg-surface flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div
            aria-hidden="true"
            className="bg-brand mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl text-lg font-bold text-white"
          >
            T
          </div>
          <h1 className="text-ink text-2xl font-semibold">TaskFlow</h1>
          <p className="text-ink-subtle mt-1 text-sm">
            {mode === 'login' ? 'Sign in to continue.' : 'Create your account.'}
          </p>
        </div>

        <div className="card p-6">
          {/* `void` is explicit: the handler is async and React expects a
              void-returning listener. Passing the promise straight through
              makes a rejection an unhandled one with no stack in the UI. */}
          <form
            onSubmit={(event) => void handleSubmit(event)}
            noValidate
            className="space-y-4"
          >
            {error ? <Alert>{error}</Alert> : null}

            {mode === 'register' ? (
              <Field label="Full name" htmlFor="full-name" required>
                <Input
                  id="full-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  autoComplete="name"
                  required
                  minLength={2}
                  maxLength={120}
                />
              </Field>
            ) : null}

            <Field label="Email" htmlFor="email" required>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                // The right autocomplete tokens let a password manager fill
                // the form, which is the single biggest usability win on a
                // login screen.
                autoComplete="email"
                required
                placeholder="you@example.com"
              />
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              required
              hint={mode === 'register' ? 'At least 10 characters.' : undefined}
            >
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'register' ? 10 : 1}
              />
            </Field>

            <Button type="submit" isLoading={isSubmitting} className="w-full">
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>

          <div className="border-border mt-5 space-y-3 border-t pt-5">
            <Button variant="secondary" className="w-full" onClick={useDemoAccount}>
              Use the demo account
            </Button>
            <p className="text-ink-subtle text-center text-sm">
              {mode === 'login' ? 'No account yet?' : 'Already registered?'}{' '}
              <button
                type="button"
                onClick={() => {
                  setMode(mode === 'login' ? 'register' : 'login')
                  setError(null)
                }}
                className="text-brand font-medium underline underline-offset-2"
              >
                {mode === 'login' ? 'Create one' : 'Sign in'}
              </button>
            </p>
          </div>
        </div>

        <p className="text-ink-subtle mt-6 text-center text-xs">
          Seeded accounts: ada@, grace@, alan@, margaret@taskflow.dev &mdash; password{' '}
          <code className="text-ink-muted">DemoPassw0rd!2026</code>
        </p>
      </div>
    </main>
  )
}
