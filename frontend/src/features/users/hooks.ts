import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '@/lib/problemDetail'
import type { Paginated, UserSummary } from '@/features/tasks/types'
import { usersApi } from './api'

export const userKeys = {
  all: ['users'] as const,
  list: (search?: string) => [...userKeys.all, 'list', search ?? ''] as const,
}

/**
 * The teammate directory.
 *
 * Cached for five minutes: it feeds a dropdown, changes rarely, and
 * refetching it on every modal open would add a request per interaction for
 * data that is almost always identical.
 */
export function useUsers(search?: string) {
  return useQuery<Paginated<UserSummary>, ApiError>({
    queryKey: userKeys.list(search),
    queryFn: ({ signal }) => usersApi.list(search, signal),
    staleTime: 5 * 60 * 1000,
  })
}
