import { api } from '@/lib/apiClient'
import type { Paginated, UserSummary } from '@/features/tasks/types'

export const usersApi = {
  list: (search?: string, signal?: AbortSignal) =>
    api.get<Paginated<UserSummary>>(
      '/users',
      // The directory only feeds the assignee picker, so one generous page
      // is simpler than paginating a dropdown.
      { page_size: 100, active_only: true, search: search ?? undefined },
      signal,
    ),
}
