import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { cx } from '@/lib/cx'

/**
 * A small set of primitives, grouped in one module because each is a handful
 * of lines. Splitting eleven 15-line components into eleven files and an
 * index would be more navigation for no more clarity.
 *
 * They exist so that spacing, focus rings and disabled states are decided
 * once. Without them, every screen re-invents a button and they drift.
 */

/* ------------------------------------------------------------------ Button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-white hover:bg-brand/90 active:bg-brand/95 shadow-sm',
  secondary: 'bg-white text-ink border border-border-strong hover:bg-surface',
  ghost: 'bg-transparent text-ink-muted hover:bg-surface hover:text-ink',
  // The palette has no red, so a destructive action is signalled by the
  // darkest ink plus an explicit label and a confirmation step, not by hue.
  danger: 'bg-ink text-white hover:bg-ink/90',
}

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  isLoading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', isLoading = false, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // Disabled while submitting, so a double click cannot fire the
      // mutation twice.
      disabled={rest.disabled ?? isLoading}
      // Announced to screen readers, which otherwise get no hint that
      // anything is happening.
      aria-busy={isLoading || undefined}
      className={cx(
        'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...rest}
    >
      {isLoading ? <Spinner size={size === 'sm' ? 12 : 14} /> : null}
      {children}
    </button>
  )
})

/* ----------------------------------------------------------------- Spinner */

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span
      role="status"
      aria-label={label ?? 'Loading'}
      className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent"
      style={{ width: size, height: size }}
    />
  )
}

/* ------------------------------------------------------------------- Field */

interface FieldProps {
  label: string
  htmlFor: string
  error?: string | undefined
  hint?: string | undefined
  required?: boolean
  children: ReactNode
}

/**
 * Wraps a control with its label, hint and error.
 *
 * The wiring matters more than the markup: the error is referenced by
 * `aria-describedby` on the control and rendered in a live region, so a
 * screen-reader user hears why the form was rejected instead of only seeing
 * a red outline.
 */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  required,
  children,
}: FieldProps) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="text-ink-subtle ml-1" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${htmlFor}-hint`} className="text-ink-subtle mt-1 text-xs">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p
          id={`${htmlFor}-error`}
          role="alert"
          className="text-violet mt-1 text-xs font-medium"
        >
          {error}
        </p>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ Inputs */

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cx('field', className)} {...rest} />
  },
)

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx('field', className)} {...rest} />
})

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cx('field cursor-pointer', className)} {...rest}>
      {children}
    </select>
  )
})

/* ------------------------------------------------------------------- Badge */

type BadgeTone = 'brand' | 'success' | 'sky' | 'teal' | 'violet' | 'slate' | 'neutral'

const BADGE_TONES: Record<BadgeTone, string> = {
  brand: 'bg-brand/10 text-brand ring-brand/20',
  success: 'bg-success/10 text-success ring-success/20',
  sky: 'bg-sky/15 text-teal ring-sky/30',
  teal: 'bg-teal/10 text-teal ring-teal/20',
  violet: 'bg-violet/10 text-violet ring-violet/20',
  slate: 'bg-slate/10 text-slate ring-slate/20',
  neutral: 'bg-surface text-ink-muted ring-border',
}

export function Badge({
  tone = 'neutral',
  children,
  icon,
}: {
  tone?: BadgeTone
  children: ReactNode
  icon?: ReactNode
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        BADGE_TONES[tone],
      )}
    >
      {icon}
      {children}
    </span>
  )
}

/* ------------------------------------------------------------------- Modal */

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  // `| undefined` is required under `exactOptionalPropertyTypes`: callers
  // pass a conditional value, and the type has to admit it explicitly
  // rather than the flag being switched off.
  description?: string | undefined
  children: ReactNode
  footer?: ReactNode | undefined
}

/**
 * A dialog built on the semantics rather than a styled `div`.
 *
 * What it handles that a bare div does not: Escape to dismiss, a click on the
 * backdrop, focus moved into the dialog on open and restored on close, and
 * `aria-modal` so assistive technology treats the rest of the page as
 * inert. Getting those wrong is what makes a modal unusable by keyboard.
 */
export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    if (!isOpen) return

    previouslyFocused.current = document.activeElement as HTMLElement | null

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)

    // Stops the page behind from scrolling while the dialog is open.
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const firstFocusable = panelRef.current?.querySelector<HTMLElement>(
      'input, select, textarea, button, [tabindex]:not([tabindex="-1"])',
    )
    firstFocusable?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = originalOverflow
      // Returning focus to the trigger is what keeps keyboard navigation
      // coherent after the dialog closes.
      previouslyFocused.current?.focus()
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto bg-ink/40 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className="card w-full max-w-lg rounded-b-none shadow-[--shadow-raised] sm:rounded-[--radius-card]"
      >
        <header className="border-border flex items-start justify-between gap-4 border-b px-5 py-4">
          <div>
            <h2 id={titleId} className="text-ink text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="text-ink-subtle mt-0.5 text-sm">
                {description}
              </p>
            ) : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close dialog">
            <span aria-hidden="true">&#10005;</span>
          </Button>
        </header>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>

        {footer ? (
          <footer className="border-border bg-surface flex flex-col-reverse gap-2 rounded-b-[--radius-card] border-t px-5 py-4 sm:flex-row sm:justify-end">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- EmptyState */

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <div
        aria-hidden="true"
        className="bg-sky/20 text-teal mb-4 grid h-12 w-12 place-items-center rounded-full text-xl"
      >
        &#9636;
      </div>
      <h3 className="text-ink text-sm font-semibold">{title}</h3>
      <p className="text-ink-subtle mt-1 max-w-sm text-sm">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

/* -------------------------------------------------------------- Pagination */

interface PaginationProps {
  page: number
  totalPages: number
  total: number
  pageSize: number
  hasNext: boolean
  hasPrevious: boolean
  onChange: (page: number) => void
}

export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  hasNext,
  hasPrevious,
  onChange,
}: PaginationProps) {
  if (total === 0) return null

  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)

  return (
    <nav
      aria-label="Pagination"
      className="border-border flex flex-col items-center justify-between gap-3 border-t px-4 py-3 sm:flex-row"
    >
      {/* A live region so the range is announced after a page change, not
          only visible. */}
      <p aria-live="polite" className="text-ink-subtle text-xs">
        Showing <span className="text-ink font-medium">{first}</span>&ndash;
        <span className="text-ink font-medium">{last}</span> of{' '}
        <span className="text-ink font-medium">{total}</span>
      </p>

      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onChange(page - 1)}
          disabled={!hasPrevious}
        >
          Previous
        </Button>
        <span className="text-ink-subtle px-1 text-xs">
          Page {page} of {totalPages}
        </span>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onChange(page + 1)}
          disabled={!hasNext}
        >
          Next
        </Button>
      </div>
    </nav>
  )
}

/* ------------------------------------------------------------- Alert / cx  */

export function Alert({
  children,
  tone = 'violet',
}: {
  children: ReactNode
  tone?: 'violet' | 'success'
}) {
  return (
    <div
      role="alert"
      className={cx(
        'rounded-lg px-3 py-2 text-sm ring-1 ring-inset',
        tone === 'violet'
          ? 'bg-violet/5 text-violet ring-violet/20'
          : 'bg-success/5 text-success ring-success/20',
      )}
    >
      {children}
    </div>
  )
}
