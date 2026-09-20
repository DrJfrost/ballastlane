/**
 * Types mirroring the API contract.
 *
 * Hand-written rather than generated, so the file doubles as documentation of
 * what the frontend actually consumes. `snake_case` is kept exactly as the
 * API sends it: silently renaming fields at the boundary makes it harder to
 * match a network response to the code reading it.
 */

export const TASK_STATUSES = ['todo', 'in_progress', 'done', 'cancelled'] as const
export type TaskStatus = (typeof TASK_STATUSES)[number]

export const TASK_PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const
export type TaskPriority = (typeof TASK_PRIORITIES)[number]

export const SORT_FIELDS = [
  'created_at',
  'updated_at',
  'due_date',
  'priority',
  'title',
  'status',
] as const
export type SortField = (typeof SORT_FIELDS)[number]

export type SortDirection = 'asc' | 'desc'

export interface UserSummary {
  id: string
  email: string
  full_name: string
  initials: string
}

export interface Task {
  id: string
  title: string
  description: string
  status: TaskStatus
  priority: TaskPriority
  due_date: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  owner: UserSummary | null
  assignee: UserSummary | null
  is_overdue: boolean
  days_until_due: number | null
  /**
   * Sent by the API, projected from the same entity predicates the write
   * path enforces. The UI disables what it may not do instead of
   * re-implementing the permission rules and drifting from them.
   */
  can_edit: boolean
  can_change_status: boolean
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
  has_next: boolean
  has_previous: boolean
}

export interface Paginated<T> {
  items: T[]
  meta: PageMeta
}

export interface TaskStats {
  total: number
  todo: number
  in_progress: number
  done: number
  cancelled: number
  overdue: number
  assigned_to_me: number
}

export interface CurrentUser {
  id: string
  email: string
  full_name: string
  initials: string
  is_active: boolean
  created_at: string
}

/** Exactly the filters the list endpoint understands. */
export interface TaskFilters {
  status: TaskStatus[]
  priority: TaskPriority[]
  search: string
  due_before: string
  due_after: string
  overdue_only: boolean
  assigned_to_me: boolean
  created_by_me: boolean
  unassigned_only: boolean
  sort_by: SortField
  sort_dir: SortDirection
  page: number
  page_size: number
}

export const DEFAULT_FILTERS: TaskFilters = {
  status: [],
  priority: [],
  search: '',
  due_before: '',
  due_after: '',
  overdue_only: false,
  assigned_to_me: false,
  created_by_me: false,
  unassigned_only: false,
  sort_by: 'created_at',
  sort_dir: 'desc',
  page: 1,
  page_size: 10,
}

export interface CreateTaskInput {
  title: string
  description: string
  priority: TaskPriority
  due_date: string | null
  assignee_id: string | null
}

/**
 * A PATCH payload. Every key is optional; `null` on `due_date` or
 * `assignee_id` is a deliberate "clear this", which the API distinguishes
 * from an omitted key.
 */
export interface UpdateTaskInput {
  title?: string
  description?: string
  priority?: TaskPriority
  status?: TaskStatus
  due_date?: string | null
  assignee_id?: string | null
}

export const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  done: 'Done',
  cancelled: 'Cancelled',
}

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
}

export const SORT_LABELS: Record<SortField, string> = {
  created_at: 'Created',
  updated_at: 'Updated',
  due_date: 'Due date',
  priority: 'Priority',
  title: 'Title',
  status: 'Status',
}

/** Statuses a task may legally move to, mirroring the domain transitions. */
export const ALLOWED_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  todo: ['in_progress', 'done', 'cancelled'],
  in_progress: ['todo', 'done', 'cancelled'],
  done: ['todo', 'in_progress'],
  cancelled: ['todo'],
}
