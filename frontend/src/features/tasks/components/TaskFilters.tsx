import { useEffect, useState } from 'react'
import { Button, Field, Input, Select } from '@/components/ui'
import {
  PRIORITY_LABELS,
  SORT_FIELDS,
  SORT_LABELS,
  STATUS_LABELS,
  TASK_PRIORITIES,
  TASK_STATUSES,
  type SortField,
  type TaskFilters as Filters,
  type TaskPriority,
  type TaskStatus,
} from '../types'

interface TaskFiltersProps {
  filters: Filters
  onChange: (patch: Partial<Filters>) => void
  onReset: () => void
  hasActiveFilters: boolean
}

/**
 * The filter bar.
 *
 * Every control writes straight into the single `filters` object that also
 * forms the React Query key, so "what the user asked for", "what was
 * requested" and "what is cached" cannot drift apart.
 */
export function TaskFilters({
  filters,
  onChange,
  onReset,
  hasActiveFilters,
}: TaskFiltersProps) {
  const search = useDebouncedSearch(filters.search, (value) =>
    onChange({ search: value, page: 1 }),
  )

  function toggle<T extends string>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
  }

  return (
    <section aria-labelledby="filters-heading" className="space-y-4 px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <h2 id="filters-heading" className="text-ink text-sm font-semibold">
          Filters
        </h2>
        {hasActiveFilters ? (
          <Button variant="ghost" size="sm" onClick={onReset}>
            Clear all
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <div className="lg:col-span-2">
          <Field label="Search" htmlFor="filter-search">
            <Input
              id="filter-search"
              type="search"
              value={search.value}
              onChange={(event) => search.setValue(event.target.value)}
              placeholder="Search titles and descriptions"
            />
          </Field>
        </div>

        <Field label="Due after" htmlFor="filter-due-after">
          <Input
            id="filter-due-after"
            type="date"
            value={filters.due_after}
            onChange={(event) => onChange({ due_after: event.target.value, page: 1 })}
          />
        </Field>

        <Field
          label="Due before"
          htmlFor="filter-due-before"
          hint="Inclusive of the whole day."
        >
          <Input
            id="filter-due-before"
            type="date"
            value={filters.due_before}
            onChange={(event) => onChange({ due_before: event.target.value, page: 1 })}
          />
        </Field>
      </div>

      {/* Multi-select as toggle groups rather than a <select multiple>, which
          is close to unusable on a touch screen. */}
      <fieldset>
        <legend className="label">Status</legend>
        <div className="flex flex-wrap gap-2">
          {TASK_STATUSES.map((status) => (
            <ToggleChip
              key={status}
              label={STATUS_LABELS[status]}
              isActive={filters.status.includes(status)}
              onClick={() =>
                onChange({ status: toggle<TaskStatus>(filters.status, status), page: 1 })
              }
            />
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="label">Priority</legend>
        <div className="flex flex-wrap gap-2">
          {TASK_PRIORITIES.map((priority) => (
            <ToggleChip
              key={priority}
              label={PRIORITY_LABELS[priority]}
              isActive={filters.priority.includes(priority)}
              onClick={() =>
                onChange({
                  priority: toggle<TaskPriority>(filters.priority, priority),
                  page: 1,
                })
              }
            />
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <fieldset className="sm:col-span-2 lg:col-span-2">
          <legend className="label">Scope</legend>
          <div className="flex flex-wrap gap-4">
            <Checkbox
              id="filter-overdue"
              label="Overdue only"
              checked={filters.overdue_only}
              onChange={(checked) => onChange({ overdue_only: checked, page: 1 })}
            />
            <Checkbox
              id="filter-assigned"
              label="Assigned to me"
              checked={filters.assigned_to_me}
              onChange={(checked) => onChange({ assigned_to_me: checked, page: 1 })}
            />
            <Checkbox
              id="filter-created"
              label="Created by me"
              checked={filters.created_by_me}
              onChange={(checked) => onChange({ created_by_me: checked, page: 1 })}
            />
            <Checkbox
              id="filter-unassigned"
              label="Unassigned"
              checked={filters.unassigned_only}
              onChange={(checked) => onChange({ unassigned_only: checked, page: 1 })}
            />
          </div>
        </fieldset>

        <Field label="Sort by" htmlFor="filter-sort">
          <Select
            id="filter-sort"
            value={filters.sort_by}
            onChange={(event) =>
              onChange({ sort_by: event.target.value as SortField, page: 1 })
            }
          >
            {SORT_FIELDS.map((field) => (
              <option key={field} value={field}>
                {SORT_LABELS[field]}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Direction" htmlFor="filter-direction">
          <Select
            id="filter-direction"
            value={filters.sort_dir}
            onChange={(event) =>
              onChange({ sort_dir: event.target.value as 'asc' | 'desc', page: 1 })
            }
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </Select>
        </Field>
      </div>
    </section>
  )
}

function ToggleChip({
  label,
  isActive,
  onClick,
}: {
  label: string
  isActive: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      // `aria-pressed` is what tells a screen reader this is a toggle, not a
      // command button; without it the selected state is invisible.
      aria-pressed={isActive}
      onClick={onClick}
      className={
        isActive
          ? 'bg-brand rounded-full px-3 py-1 text-xs font-medium text-white'
          : 'border-border text-ink-muted hover:border-border-strong hover:text-ink rounded-full border bg-white px-3 py-1 text-xs font-medium'
      }
    >
      {label}
    </button>
  )
}

function Checkbox({
  id,
  label,
  checked,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label htmlFor={id} className="text-ink flex cursor-pointer items-center gap-2 text-sm">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="border-border-strong text-brand focus:ring-brand h-4 w-4 rounded"
      />
      {label}
    </label>
  )
}

/**
 * Debounces the search box.
 *
 * Firing a request per keystroke means ten requests to type "kubernetes",
 * nine of which are thrown away -- and the responses can arrive out of order,
 * so the list briefly shows results for a prefix.
 */
function useDebouncedSearch(initial: string, commit: (value: string) => void) {
  const [value, setValue] = useState(initial)

  useEffect(() => {
    if (value === initial) return
    const timer = window.setTimeout(() => commit(value), 300)
    return () => window.clearTimeout(timer)
    // `commit` is recreated per render by the parent; depending on it would
    // reset the timer on every keystroke and defeat the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, initial])

  // Keeps the box in sync when the filters are reset from outside.
  useEffect(() => {
    setValue(initial)
  }, [initial])

  return { value, setValue }
}
