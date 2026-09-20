import { api } from '@/lib/apiClient'
import type {
  CreateTaskInput,
  Paginated,
  Task,
  TaskFilters,
  TaskStats,
  UpdateTaskInput,
} from './types'

/**
 * The only place that knows the task endpoints and their query-string shape.
 * Components call hooks; hooks call these.
 */

/** The exact value shapes `apiClient` knows how to serialise. */
export type QueryParams = Record<
  string,
  string | number | boolean | string[] | null | undefined
>

/** Translates the filter state into the query the API expects. */
export function toQueryParams(filters: TaskFilters): QueryParams {
  return {
    page: filters.page,
    page_size: filters.page_size,
    sort_by: filters.sort_by,
    sort_dir: filters.sort_dir,
    // Repeated keys for multi-value filters; the client drops empty arrays.
    status: filters.status,
    priority: filters.priority,
    search: filters.search.trim() || undefined,
    due_before: filters.due_before ? isoStartOfDay(filters.due_before, true) : undefined,
    due_after: filters.due_after ? isoStartOfDay(filters.due_after, false) : undefined,
    // Booleans are only sent when true, so the URL stays readable and the
    // server keeps its own defaults.
    overdue_only: filters.overdue_only || undefined,
    assigned_to_me: filters.assigned_to_me || undefined,
    created_by_me: filters.created_by_me || undefined,
    unassigned_only: filters.unassigned_only || undefined,
  }
}

/**
 * Converts a `<input type="date">` value into an instant.
 *
 * A date input gives `2026-07-01` with no time. "Due before 1 July" almost
 * always means *including* the whole of 1 July, so the upper bound is pushed
 * to the end of that day. Sending midnight instead silently excludes
 * everything due during the day the user picked.
 */
function isoStartOfDay(value: string, endOfDay: boolean): string {
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  const date = endOfDay
    ? new Date(Date.UTC(year, month - 1, day, 23, 59, 59, 999))
    : new Date(Date.UTC(year, month - 1, day, 0, 0, 0, 0))
  return date.toISOString()
}

export const tasksApi = {
  list: (filters: TaskFilters, signal?: AbortSignal) =>
    api.get<Paginated<Task>>('/tasks', toQueryParams(filters), signal),

  stats: (signal?: AbortSignal) => api.get<TaskStats>('/tasks/stats', undefined, signal),

  get: (id: string, signal?: AbortSignal) =>
    api.get<Task>(`/tasks/${id}`, undefined, signal),

  create: (input: CreateTaskInput) => api.post<Task>('/tasks', input),

  update: (id: string, input: UpdateTaskInput) => api.patch<Task>(`/tasks/${id}`, input),

  complete: (id: string) => api.post<Task>(`/tasks/${id}/complete`),

  reopen: (id: string) => api.post<Task>(`/tasks/${id}/reopen`),

  assign: (id: string, assigneeId: string | null) =>
    api.put<Task>(`/tasks/${id}/assignee`, { assignee_id: assigneeId }),

  remove: (id: string) => api.delete<void>(`/tasks/${id}`),
}
