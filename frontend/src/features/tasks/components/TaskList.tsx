import { Button, EmptyState, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'
import { useCompleteTask, useReopenTask } from '../hooks'
import type { Task } from '../types'
import { AssigneeChip, DueBadge, PriorityBadge, StatusBadge } from './badges'

interface TaskListProps {
  tasks: Task[]
  isLoading: boolean
  isRefetching: boolean
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
  onCreate: () => void
  hasActiveFilters: boolean
}

/**
 * Responsive by *structure*, not by hiding columns.
 *
 * Below `md` the same data is rendered as stacked cards; from `md` up it is a
 * real `<table>`. A table squeezed onto a phone either scrolls horizontally
 * or drops the columns that matter, so the layout changes rather than the
 * content.
 */
export function TaskList({
  tasks,
  isLoading,
  isRefetching,
  onEdit,
  onDelete,
  onCreate,
  hasActiveFilters,
}: TaskListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20">
        <Spinner size={20} label="Loading tasks" />
        <span className="text-ink-subtle text-sm">Loading tasks…</span>
      </div>
    )
  }

  if (tasks.length === 0) {
    return hasActiveFilters ? (
      <EmptyState
        title="No tasks match these filters"
        description="Try widening the date range or clearing a filter."
      />
    ) : (
      <EmptyState
        title="No tasks yet"
        description="Create your first task to get started."
        action={<Button onClick={onCreate}>New task</Button>}
      />
    )
  }

  return (
    <div
      // Dims slightly while a refetch is in flight, so a filter change is
      // visibly acknowledged without the list disappearing.
      className={isRefetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}
      aria-busy={isRefetching || undefined}
    >
      {/* ------------------------------------------- mobile: cards */}
      <ul className="divide-border divide-y md:hidden">
        {tasks.map((task) => (
          <li key={task.id} className="px-4 py-4">
            <TaskCard
              task={task}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          </li>
        ))}
      </ul>

      {/* ------------------------------------------- desktop: table */}
      <div className="hidden md:block">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Tasks you own or are assigned to, with status, priority, assignee
            and due date.
          </caption>
          <thead>
            <tr className="border-border text-ink-subtle border-b text-xs uppercase tracking-wide">
              <th scope="col" className="px-4 py-3 font-medium">
                Task
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Status
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Priority
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Assignee
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Due
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-border divide-y">
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ row */

function TaskRow({
  task,
  onEdit,
  onDelete,
}: {
  task: Task
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
}) {
  return (
    <tr className="hover:bg-surface/70 transition-colors">
      <td className="max-w-xs px-4 py-3">
        <p className="text-ink truncate font-medium">{task.title}</p>
        {task.description ? (
          <p className="text-ink-subtle mt-0.5 truncate text-xs">{task.description}</p>
        ) : null}
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={task.status} />
      </td>
      <td className="px-4 py-3">
        <PriorityBadge priority={task.priority} />
      </td>
      <td className="max-w-[10rem] px-4 py-3">
        {task.assignee ? (
          <AssigneeChip
            initials={task.assignee.initials}
            fullName={task.assignee.full_name}
          />
        ) : (
          <span className="text-ink-subtle text-xs">Unassigned</span>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-col gap-1">
          <DueBadge daysUntilDue={task.days_until_due} isOverdue={task.is_overdue} />
          {task.due_date ? (
            <span className="text-ink-subtle text-xs">{formatDate(task.due_date)}</span>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-3">
        <TaskActions task={task} onEdit={onEdit} onDelete={onDelete} />
      </td>
    </tr>
  )
}

/* ----------------------------------------------------------------- card */

function TaskCard({
  task,
  onEdit,
  onDelete,
}: {
  task: Task
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
}) {
  return (
    <article className="space-y-3">
      <div>
        <h3 className="text-ink text-sm font-medium">{task.title}</h3>
        {task.description ? (
          <p className="text-ink-subtle mt-1 line-clamp-2 text-xs">{task.description}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={task.status} />
        <PriorityBadge priority={task.priority} />
        <DueBadge daysUntilDue={task.days_until_due} isOverdue={task.is_overdue} />
      </div>

      <div className="flex items-center justify-between gap-3">
        {task.assignee ? (
          <AssigneeChip
            initials={task.assignee.initials}
            fullName={task.assignee.full_name}
          />
        ) : (
          <span className="text-ink-subtle text-xs">Unassigned</span>
        )}
        <TaskActions task={task} onEdit={onEdit} onDelete={onDelete} />
      </div>
    </article>
  )
}

/* -------------------------------------------------------------- actions */

function TaskActions({
  task,
  onEdit,
  onDelete,
}: {
  task: Task
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
}) {
  const complete = useCompleteTask()
  const reopen = useReopenTask()
  const isBusy = complete.isPending || reopen.isPending
  const isClosed = task.status === 'done' || task.status === 'cancelled'

  return (
    <div className="flex items-center justify-end gap-1">
      {/* Every button is gated on the capability flags the API computed, so
          the UI never offers an action that would come back 403. */}
      {task.can_change_status ? (
        isClosed ? (
          <Button
            variant="ghost"
            size="sm"
            isLoading={isBusy}
            onClick={() => reopen.mutate(task.id)}
          >
            Reopen
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            isLoading={isBusy}
            onClick={() => complete.mutate(task.id)}
          >
            Complete
          </Button>
        )
      ) : null}

      <Button
        variant="ghost"
        size="sm"
        onClick={() => onEdit(task)}
        aria-label={`Edit ${task.title}`}
      >
        Edit
      </Button>

      {task.can_edit ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(task)}
          aria-label={`Delete ${task.title}`}
        >
          Delete
        </Button>
      ) : null}
    </div>
  )
}
