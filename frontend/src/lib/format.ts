/** Date and text formatting shared across the UI. */

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/**
 * `Intl` rather than a hand-rolled `toLocaleDateString` template, so the
 * output follows the reader's locale (and their 12/24-hour preference)
 * instead of the developer's.
 */
export function formatDate(iso: string | null): string {
  if (!iso) return '--'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '--' : dateFormatter.format(date)
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '--'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '--' : dateTimeFormatter.format(date)
}

/**
 * A short relative description of a deadline.
 *
 * Derived from the API's `days_until_due` rather than recomputed from the
 * timestamp, so the label always agrees with the `is_overdue` flag the server
 * sent -- no disagreement caused by a client clock that is minutes off.
 */
export function formatDueLabel(
  daysUntilDue: number | null,
  isOverdue: boolean,
): string | null {
  if (daysUntilDue === null) return null
  if (isOverdue) {
    const late = Math.abs(daysUntilDue)
    if (late === 0) return 'Due today, overdue'
    return `${late} day${late === 1 ? '' : 's'} overdue`
  }
  if (daysUntilDue === 0) return 'Due today'
  if (daysUntilDue === 1) return 'Due tomorrow'
  return `Due in ${daysUntilDue} days`
}

/** Converts an API timestamp into a `<input type="datetime-local">` value. */
export function toDateTimeInputValue(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  // The input expects local wall-clock time with no offset, so the UTC
  // instant has to be shifted before slicing.
  const offsetMs = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16)
}

/** Converts a `datetime-local` value back into an ISO instant. */
export function fromDateTimeInputValue(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export function pluralise(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`
}
