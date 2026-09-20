import { useState, type FormEvent } from 'react'
import { Alert, Button, Field, Input, Select, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/problemDetail'
import { fromDateTimeInputValue, toDateTimeInputValue } from '@/lib/format'
import { useUsers } from '@/features/users/hooks'
import { useCreateTask, useUpdateTask } from '../hooks'
import {
  ALLOWED_TRANSITIONS,
  PRIORITY_LABELS,
  STATUS_LABELS,
  TASK_PRIORITIES,
  type Task,
  type TaskPriority,
  type TaskStatus,
  type UpdateTaskInput,
} from '../types'

interface TaskFormProps {
  /** `undefined` creates; a task edits it. */
  task?: Task | undefined
  onDone: () => void
  onCancel: () => void
}

interface FormState {
  title: string
  description: string
  priority: TaskPriority
  status: TaskStatus
  dueDate: string
  assigneeId: string
}

function initialState(task: Task | undefined): FormState {
  return {
    title: task?.title ?? '',
    description: task?.description ?? '',
    priority: task?.priority ?? 'medium',
    status: task?.status ?? 'todo',
    dueDate: toDateTimeInputValue(task?.due_date ?? null),
    assigneeId: task?.assignee?.id ?? '',
  }
}

/**
 * The create/edit form.
 *
 * Client-side validation here is only about *fast feedback*: the server
 * re-validates everything, and its message is what gets displayed when the
 * two disagree. Treating the client as the authority is how a title of 201
 * characters ends up in the database because someone called the API directly.
 */
export function TaskForm({ task, onDone, onCancel }: TaskFormProps) {
  const isEditing = task !== undefined
  const [form, setForm] = useState<FormState>(() => initialState(task))
  const [touched, setTouched] = useState(false)

  const { data: users } = useUsers()
  const createTask = useCreateTask(onDone)
  const updateTask = useUpdateTask(onDone)

  const mutation = isEditing ? updateTask : createTask
  const apiError = mutation.error instanceof ApiError ? mutation.error : null

  const titleProblem =
    form.title.trim().length === 0
      ? 'A title is required.'
      : form.title.trim().length < 3
        ? 'Use at least 3 characters.'
        : form.title.length > 200
          ? 'Use at most 200 characters.'
          : undefined

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }))
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setTouched(true)
    if (titleProblem) return

    const dueDate = fromDateTimeInputValue(form.dueDate)
    const assigneeId = form.assigneeId || null

    if (!isEditing) {
      createTask.mutate({
        title: form.title.trim(),
        description: form.description.trim(),
        priority: form.priority,
        due_date: dueDate,
        assignee_id: assigneeId,
      })
      return
    }

    // Only changed fields are sent. That is what makes `null` meaningful:
    // "clear the deadline" instead of "I did not mention it".
    const patch: UpdateTaskInput = {}
    if (form.title.trim() !== task.title) patch.title = form.title.trim()
    if (form.description.trim() !== task.description) {
      patch.description = form.description.trim()
    }
    if (form.priority !== task.priority) patch.priority = form.priority
    if (form.status !== task.status) patch.status = form.status
    if (dueDate !== task.due_date) patch.due_date = dueDate
    if (assigneeId !== (task.assignee?.id ?? null)) patch.assignee_id = assigneeId

    if (Object.keys(patch).length === 0) {
      onDone()
      return
    }
    updateTask.mutate({ id: task.id, input: patch })
  }

  // An assignee may drive the lifecycle but not rewrite the content, so the
  // content fields are locked rather than hidden -- they are still worth
  // reading.
  const contentLocked = isEditing && !task.can_edit
  const statusOptions: TaskStatus[] = isEditing
    ? [task.status, ...ALLOWED_TRANSITIONS[task.status]]
    : ['todo']

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {apiError && !apiError.isValidationError ? (
        <Alert>{apiError.message}</Alert>
      ) : null}

      {contentLocked ? (
        <Alert tone="success">
          You are the assignee of this task, so you can move it through its
          lifecycle. Only its owner can change the details.
        </Alert>
      ) : null}

      <Field
        label="Title"
        htmlFor="task-title"
        required
        error={
          (touched ? titleProblem : undefined) ?? apiError?.messageFor('title')
        }
      >
        <Input
          id="task-title"
          value={form.title}
          onChange={(event) => update('title', event.target.value)}
          onBlur={() => setTouched(true)}
          disabled={contentLocked}
          maxLength={200}
          placeholder="Draft the Q4 architecture review"
          autoComplete="off"
          aria-invalid={Boolean(touched && titleProblem) || undefined}
          aria-describedby={touched && titleProblem ? 'task-title-error' : undefined}
        />
      </Field>

      <Field
        label="Description"
        htmlFor="task-description"
        hint="Optional. Markdown is not rendered."
        error={apiError?.messageFor('description')}
      >
        <Textarea
          id="task-description"
          rows={3}
          value={form.description}
          onChange={(event) => update('description', event.target.value)}
          disabled={contentLocked}
          maxLength={5000}
          placeholder="Focus on the ingestion pipeline."
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Priority" htmlFor="task-priority">
          <Select
            id="task-priority"
            value={form.priority}
            onChange={(event) => update('priority', event.target.value as TaskPriority)}
            disabled={contentLocked}
          >
            {TASK_PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {PRIORITY_LABELS[priority]}
              </option>
            ))}
          </Select>
        </Field>

        {isEditing ? (
          <Field
            label="Status"
            htmlFor="task-status"
            hint="Only legal transitions are listed."
            error={apiError?.messageFor('status')}
          >
            <Select
              id="task-status"
              value={form.status}
              onChange={(event) => update('status', event.target.value as TaskStatus)}
              disabled={!task.can_change_status}
            >
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Due date"
          htmlFor="task-due"
          hint="Must be in the future. Leave empty for no deadline."
          error={apiError?.messageFor('due_date')}
        >
          <Input
            id="task-due"
            type="datetime-local"
            value={form.dueDate}
            onChange={(event) => update('dueDate', event.target.value)}
            disabled={contentLocked}
          />
        </Field>

        <Field
          label="Assignee"
          htmlFor="task-assignee"
          error={apiError?.messageFor('assignee_id')}
        >
          <Select
            id="task-assignee"
            value={form.assigneeId}
            onChange={(event) => update('assigneeId', event.target.value)}
            disabled={contentLocked}
          >
            <option value="">Unassigned</option>
            {users?.items.map((user) => (
              <option key={user.id} value={user.id}>
                {user.full_name}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="border-border flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={mutation.isPending}>
          {isEditing ? 'Save changes' : 'Create task'}
        </Button>
      </div>
    </form>
  )
}
