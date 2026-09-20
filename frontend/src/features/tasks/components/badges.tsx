import { Badge } from '@/components/ui'
import { formatDueLabel } from '@/lib/format'
import {
  PRIORITY_LABELS,
  STATUS_LABELS,
  type TaskPriority,
  type TaskStatus,
} from '../types'

/**
 * Status and priority are mapped to brand accents here, once, so the same
 * status is never two different colours on two different screens.
 */

const STATUS_TONES = {
  todo: 'slate',
  in_progress: 'brand',
  done: 'success',
  cancelled: 'neutral',
} as const

const PRIORITY_TONES = {
  low: 'neutral',
  medium: 'teal',
  high: 'brand',
  urgent: 'violet',
} as const

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <Badge tone={STATUS_TONES[status]}>{STATUS_LABELS[status]}</Badge>
}

export function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return (
    <Badge tone={PRIORITY_TONES[priority]}>
      {/* A leading glyph for `urgent` so priority is not conveyed by colour
          alone -- required by WCAG 1.4.1 and simply clearer. */}
      {priority === 'urgent' ? <span aria-hidden="true">&#9650;</span> : null}
      {PRIORITY_LABELS[priority]}
    </Badge>
  )
}

/**
 * The due date, with an overdue state carried by an icon and the word
 * "overdue" as well as the accent colour.
 */
export function DueBadge({
  daysUntilDue,
  isOverdue,
}: {
  daysUntilDue: number | null
  isOverdue: boolean
}) {
  const label = formatDueLabel(daysUntilDue, isOverdue)
  if (!label) {
    return (
      <span className="text-ink-subtle text-xs">No deadline</span>
    )
  }
  return (
    <Badge
      tone={isOverdue ? 'violet' : daysUntilDue !== null && daysUntilDue <= 2 ? 'sky' : 'neutral'}
      icon={isOverdue ? <span aria-hidden="true">&#9888;</span> : undefined}
    >
      {label}
    </Badge>
  )
}

export function AssigneeChip({
  initials,
  fullName,
}: {
  initials: string
  fullName: string
}) {
  return (
    <span className="inline-flex items-center gap-2" title={fullName}>
      <span
        aria-hidden="true"
        className="bg-brand/10 text-brand grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold"
      >
        {initials}
      </span>
      <span className="text-ink truncate text-sm">{fullName}</span>
    </span>
  )
}
