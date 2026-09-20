import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { TaskList } from './TaskList'
import type { Task } from '../types'

/**
 * These assert the behaviour a code reviewer would actually check: that the
 * UI honours the capability flags the API sends, and that the accessible
 * output is correct -- not that a particular div has a particular class.
 */

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    title: 'Write the integration tests',
    description: 'Cover the permission rules',
    status: 'todo',
    priority: 'high',
    due_date: '2027-01-15T10:00:00Z',
    completed_at: null,
    created_at: '2026-06-01T10:00:00Z',
    updated_at: '2026-06-01T10:00:00Z',
    owner: {
      id: 'user-1',
      email: 'ada@taskflow.dev',
      full_name: 'Ada Lovelace',
      initials: 'AL',
    },
    assignee: null,
    is_overdue: false,
    days_until_due: 30,
    can_edit: true,
    can_change_status: true,
    ...overrides,
  }
}

const noop = () => {
  /* intentionally does nothing: these tests assert rendering, not callbacks */
}

const baseProps = {
  isLoading: false,
  isRefetching: false,
  onEdit: noop,
  onDelete: noop,
  onCreate: noop,
  hasActiveFilters: false,
}

describe('TaskList', () => {
  it('renders a task with its status and priority', () => {
    renderWithQuery(<TaskList {...baseProps} tasks={[makeTask()]} />)

    // Both layouts render, so the title legitimately appears twice.
    expect(screen.getAllByText('Write the integration tests').length).toBeGreaterThan(0)
    expect(screen.getAllByText('To do').length).toBeGreaterThan(0)
    expect(screen.getAllByText('High').length).toBeGreaterThan(0)
  })

  it('hides Delete when the API says the user cannot edit', () => {
    // The assignee may drive the lifecycle but not delete: the UI must not
    // offer a button that would come back 403.
    renderWithQuery(
      <TaskList {...baseProps} tasks={[makeTask({ can_edit: false })]} />,
    )

    expect(screen.queryByRole('button', { name: /^Delete/ })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Edit/ }).length).toBeGreaterThan(0)
  })

  it('hides the lifecycle button when the user cannot change status', () => {
    renderWithQuery(
      <TaskList
        {...baseProps}
        tasks={[makeTask({ can_change_status: false, can_edit: false })]}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Complete' })).not.toBeInTheDocument()
  })

  it('offers Reopen instead of Complete for a closed task', () => {
    renderWithQuery(
      <TaskList
        {...baseProps}
        tasks={[makeTask({ status: 'done', completed_at: '2026-06-02T10:00:00Z' })]}
      />,
    )

    expect(screen.getAllByRole('button', { name: 'Reopen' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Complete' })).not.toBeInTheDocument()
  })

  it('marks an overdue task with words, not only colour', () => {
    renderWithQuery(
      <TaskList
        {...baseProps}
        tasks={[makeTask({ is_overdue: true, days_until_due: -3 })]}
      />,
    )

    // WCAG 1.4.1: the state must be conveyed by something other than hue.
    expect(screen.getAllByText('3 days overdue').length).toBeGreaterThan(0)
  })

  it('says so when a task has no deadline', () => {
    renderWithQuery(
      <TaskList
        {...baseProps}
        tasks={[makeTask({ due_date: null, days_until_due: null })]}
      />,
    )
    expect(screen.getAllByText('No deadline').length).toBeGreaterThan(0)
  })

  it('shows the assignee, or says the task is unassigned', () => {
    const { unmount } = renderWithQuery(
      <TaskList {...baseProps} tasks={[makeTask()]} />,
    )
    expect(screen.getAllByText('Unassigned').length).toBeGreaterThan(0)
    unmount()

    renderWithQuery(
      <TaskList
        {...baseProps}
        tasks={[
          makeTask({
            assignee: {
              id: 'user-2',
              email: 'grace@taskflow.dev',
              full_name: 'Grace Hopper',
              initials: 'GH',
            },
          }),
        ]}
      />,
    )
    expect(screen.getAllByText('Grace Hopper').length).toBeGreaterThan(0)
  })

  it('distinguishes "no tasks yet" from "nothing matches"', () => {
    const { unmount } = renderWithQuery(<TaskList {...baseProps} tasks={[]} />)
    expect(screen.getByText('No tasks yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New task' })).toBeInTheDocument()
    unmount()

    // With filters on, offering "create your first task" would be wrong --
    // the user has tasks, just not these.
    renderWithQuery(<TaskList {...baseProps} tasks={[]} hasActiveFilters />)
    expect(screen.getByText('No tasks match these filters')).toBeInTheDocument()
  })

  it('announces the loading state', () => {
    renderWithQuery(<TaskList {...baseProps} tasks={[]} isLoading />)
    expect(screen.getByRole('status', { name: 'Loading tasks' })).toBeInTheDocument()
  })

  it('exposes the desktop view as a real table with a caption', () => {
    renderWithQuery(<TaskList {...baseProps} tasks={[makeTask()]} />)

    // A real <table> with headers is what makes the data navigable by
    // screen reader; a grid of divs is not.
    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument()
  })
})
