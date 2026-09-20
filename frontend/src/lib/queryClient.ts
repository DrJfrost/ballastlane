import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './problemDetail'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      // Refetching on every window focus is a sensible default for a
      // dashboard, but it makes tests and dev-tools noisy, so it is opt-in
      // per query instead.
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Retrying a 404 or a 403 is pointless: the answer will not change.
        // Only transient failures are worth a second attempt.
        if (error instanceof ApiError && !error.isRetryable) return false
        return failureCount < 2
      },
    },
    mutations: {
      // A write is never retried automatically: without idempotency keys a
      // retried POST can create a second task.
      retry: false,
    },
  },
})
