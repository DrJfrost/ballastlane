import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/lib/problemDetail'
import { tasksApi } from './api'
import type {
  CreateTaskInput,
  Paginated,
  Task,
  TaskFilters,
  TaskStats,
  UpdateTaskInput,
} from './types'

/**
 * Server state lives in React Query; the components hold only UI state
 * (which modal is open, what the filter form says).
 *
 * The alternative -- `useEffect` + `useState` per screen -- means
 * hand-writing loading flags, cancellation, and cache invalidation after
 * every mutation, which is where stale lists after a delete come from.
 */

/**
 * Query keys are structured so that one invalidation can target exactly the
 * right slice: `['tasks']` clears everything, `['tasks', 'list', filters]`
 * only the current page.
 */
export const taskKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskKeys.all, 'list'] as const,
  list: (filters: TaskFilters) => [...taskKeys.lists(), filters] as const,
  stats: () => [...taskKeys.all, 'stats'] as const,
  detail: (id: string) => [...taskKeys.all, 'detail', id] as const,
}

export function useTasks(filters: TaskFilters) {
  return useQuery<Paginated<Task>, ApiError>({
    queryKey: taskKeys.list(filters),
    queryFn: ({ signal }) => tasksApi.list(filters, signal),
    // Keeps the previous page on screen while the next one loads, instead of
    // flashing an empty table on every filter change.
    placeholderData: (previous) => previous,
    staleTime: 10_000,
  })
}

export function useTaskStats() {
  return useQuery<TaskStats, ApiError>({
    queryKey: taskKeys.stats(),
    queryFn: ({ signal }) => tasksApi.stats(signal),
    staleTime: 30_000,
  })
}

/**
 * Anything that changes a task invalidates both the lists and the counters.
 *
 * Invalidating rather than hand-patching the cache: a task can move in or
 * out of the current filter as a result of the edit (completing it removes
 * it from an "overdue" view), and the totals shift too. Refetching is
 * correct by construction; splicing the array by hand is not.
 */
function useTaskMutation<TInput>(
  mutationFn: (input: TInput) => Promise<unknown>,
  options: { onSuccess?: () => void } = {},
) {
  const queryClient = useQueryClient()

  return useMutation<unknown, ApiError, TInput>({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: taskKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: taskKeys.stats() }),
      ])
      options.onSuccess?.()
    },
  })
}

export function useCreateTask(onSuccess?: () => void) {
  return useTaskMutation<CreateTaskInput>(
    (input) => tasksApi.create(input),
    onSuccess ? { onSuccess } : {},
  )
}

export function useUpdateTask(onSuccess?: () => void) {
  return useTaskMutation<{ id: string; input: UpdateTaskInput }>(
    ({ id, input }) => tasksApi.update(id, input),
    onSuccess ? { onSuccess } : {},
  )
}

export function useCompleteTask() {
  return useTaskMutation<string>((id) => tasksApi.complete(id))
}

export function useReopenTask() {
  return useTaskMutation<string>((id) => tasksApi.reopen(id))
}

export function useAssignTask() {
  return useTaskMutation<{ id: string; assigneeId: string | null }>(({ id, assigneeId }) =>
    tasksApi.assign(id, assigneeId),
  )
}

export function useDeleteTask(onSuccess?: () => void) {
  return useTaskMutation<string>(
    (id) => tasksApi.remove(id),
    onSuccess ? { onSuccess } : {},
  )
}
