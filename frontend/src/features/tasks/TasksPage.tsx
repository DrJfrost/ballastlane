import { useCallback, useMemo, useState } from 'react'
import { Alert, Button, Modal, Pagination } from '@/components/ui'
import { errorMessage } from '@/lib/problemDetail'
import { pluralise } from '@/lib/format'
import { useDeleteTask, useTaskStats, useTasks } from './hooks'
import { DEFAULT_FILTERS, type Task, type TaskFilters as Filters } from './types'
import { TaskFilters } from './components/TaskFilters'
import { TaskForm } from './components/TaskForm'
import { TaskList } from './components/TaskList'

/**
 * The dashboard.
 *
 * Holds only UI state: the current filters and which dialog is open. Every
 * piece of server data comes from a hook, so this component never manages a
 * loading flag or an effect of its own.
 */
export function TasksPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const [editing, setEditing] = useState<Task | null>(null)
  const [deleting, setDeleting] = useState<Task | null>(null)
  const [isCreating, setCreating] = useState(false)

  const tasks = useTasks(filters)
  const stats = useTaskStats()
  const deleteTask = useDeleteTask(() => setDeleting(null))

  const patchFilters = useCallback((patch: Partial<Filters>) => {
    setFilters((previous) => ({ ...previous, ...patch }))
  }, [])

  const resetFilters = useCallback(() => setFilters(DEFAULT_FILTERS), [])

  const hasActiveFilters = useMemo(
    () =>
      filters.status.length > 0 ||
      filters.priority.length > 0 ||
      filters.search.trim() !== '' ||
      filters.due_before !== '' ||
      filters.due_after !== '' ||
      filters.overdue_only ||
      filters.assigned_to_me ||
      filters.created_by_me ||
      filters.unassigned_only,
    [filters],
  )

  const meta = tasks.data?.meta

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-ink text-xl font-semibold">Tasks</h1>
          <p className="text-ink-subtle mt-0.5 text-sm">
            Everything you own or have been assigned.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>New task</Button>
      </header>

      {stats.data ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile label="Total" value={stats.data.total} />
          <StatTile label="To do" value={stats.data.todo} />
          <StatTile label="In progress" value={stats.data.in_progress} />
          <StatTile label="Completed" value={stats.data.done} accent="success" />
          <StatTile label="Overdue" value={stats.data.overdue} accent="violet" />
        </dl>
      ) : null}

      {tasks.isError ? <Alert>{errorMessage(tasks.error)}</Alert> : null}

      <div className="card overflow-hidden">
        <TaskFilters
          filters={filters}
          onChange={patchFilters}
          onReset={resetFilters}
          hasActiveFilters={hasActiveFilters}
        />

        <div className="border-border border-t">
          <TaskList
            tasks={tasks.data?.items ?? []}
            isLoading={tasks.isLoading}
            isRefetching={tasks.isFetching && !tasks.isLoading}
            onEdit={setEditing}
            onDelete={setDeleting}
            onCreate={() => setCreating(true)}
            hasActiveFilters={hasActiveFilters}
          />
        </div>

        {meta ? (
          <Pagination
            page={meta.page}
            totalPages={meta.total_pages}
            total={meta.total}
            pageSize={meta.page_size}
            hasNext={meta.has_next}
            hasPrevious={meta.has_previous}
            onChange={(page) => patchFilters({ page })}
          />
        ) : null}
      </div>

      <Modal
        isOpen={isCreating}
        onClose={() => setCreating(false)}
        title="New task"
        description="Only a title is required."
      >
        <TaskForm onDone={() => setCreating(false)} onCancel={() => setCreating(false)} />
      </Modal>

      <Modal
        isOpen={editing !== null}
        onClose={() => setEditing(null)}
        title="Edit task"
        description={editing?.can_edit ? undefined : 'You can change the status only.'}
      >
        {/* Keyed on the id so switching tasks remounts the form with fresh
            initial values instead of keeping the previous task's input. */}
        {editing ? (
          <TaskForm
            key={editing.id}
            task={editing}
            onDone={() => setEditing(null)}
            onCancel={() => setEditing(null)}
          />
        ) : null}
      </Modal>

      <Modal
        isOpen={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete this task?"
        description="This cannot be undone."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              isLoading={deleteTask.isPending}
              onClick={() => deleting && deleteTask.mutate(deleting.id)}
            >
              Delete task
            </Button>
          </>
        }
      >
        <p className="text-ink text-sm">
          <span className="font-medium">{deleting?.title}</span> will be removed
          permanently.
        </p>
        {deleteTask.isError ? (
          <div className="mt-3">
            <Alert>{errorMessage(deleteTask.error)}</Alert>
          </div>
        ) : null}
      </Modal>

      {/* Announces the result count to screen readers after every filter
          change, which is otherwise a purely visual update. */}
      <p aria-live="polite" className="sr-only">
        {meta ? `${pluralise(meta.total, 'task')} found` : 'Loading tasks'}
      </p>
    </div>
  )
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent?: 'success' | 'violet'
}) {
  const valueColor =
    accent === 'success'
      ? 'text-success'
      : accent === 'violet'
        ? 'text-violet'
        : 'text-ink'

  return (
    <div className="card px-4 py-3">
      <dt className="text-ink-subtle text-xs font-medium uppercase tracking-wide">
        {label}
      </dt>
      <dd className={`mt-1 text-2xl font-semibold tabular-nums ${valueColor}`}>
        {value}
      </dd>
    </div>
  )
}
