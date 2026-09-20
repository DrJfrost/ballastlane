/**
 * The API answers every failure with an RFC 9457 problem document, so the
 * frontend needs exactly one error type and one parser -- not a chain of
 * `err.detail ?? err.message ?? err.error` guesses at each call site.
 */

export interface ProblemDetail {
  readonly type: string
  readonly title: string
  readonly status: number
  readonly detail: string
  readonly code: string
  readonly errors?: Record<string, unknown>
  readonly requestId?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /** Field-keyed messages, from schema validation (`{title: "too short"}`). */
  readonly fieldErrors: Record<string, string>
  /**
   * The single field a *domain* error blames, e.g. `due_date`. Domain errors
   * carry one human message in `detail` plus the field name in `errors.field`,
   * so a form can render `error.message` under `error.field`.
   */
  readonly field: string | undefined
  readonly requestId: string | undefined

  constructor(problem: ProblemDetail) {
    super(problem.detail || problem.title)
    this.name = 'ApiError'
    this.status = problem.status
    this.code = problem.code
    this.fieldErrors = flattenFieldErrors(problem.errors)
    const blamed = problem.errors?.field
    this.field = typeof blamed === 'string' ? blamed : undefined
    this.requestId = problem.requestId
  }

  /** The message to show beneath a given form field, if any. */
  messageFor(name: string): string | undefined {
    if (this.fieldErrors[name]) return this.fieldErrors[name]
    if (this.field === name) return this.message
    return undefined
  }

  /** True when re-authenticating could plausibly fix it. */
  get isAuthError(): boolean {
    return this.status === 401
  }

  get isValidationError(): boolean {
    return this.status === 422
  }

  /**
   * Retrying is only reasonable for transient failures. A 409 means the
   * state is wrong, and repeating the request will fail identically.
   */
  get isRetryable(): boolean {
    return this.status >= 500 || this.status === 429
  }
}

/**
 * Flattens the `errors` object into `{ field: message }`.
 *
 * The API sends two shapes: Pydantic field errors (`{"title": "too short"}`)
 * and domain error details (`{"field": "due_date", "min_length": 3}`). Both
 * are normalised here so a form can look up `fieldErrors[name]` and not care
 * which produced it.
 */
function flattenFieldErrors(
  errors: Record<string, unknown> | undefined,
): Record<string, string> {
  if (!errors) return {}

  // The domain-error shape (`{field, min_length, ...}`) carries metadata
  // rather than per-field messages; `ApiError.field` handles that case.
  if (typeof errors.field === 'string') return {}

  const flat: Record<string, string> = {}
  for (const [key, value] of Object.entries(errors)) {
    if (typeof value === 'string') {
      // Strip the "query."/"body." prefix FastAPI adds to the location.
      flat[key.replace(/^(query|body|path)\./, '')] = value
    }
  }
  return flat
}

/**
 * Builds an ApiError from a Response, falling back sensibly when the body is
 * not a problem document (a proxy 502 returning HTML, for instance).
 */
/**
 * Reads a string field defensively.
 *
 * `String(value)` would happily turn an unexpected object into the literal
 * text `[object Object]` and show it to the user. Only genuine strings and
 * numbers are accepted; anything else falls back.
 */
function asString(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.length > 0) return value
  if (typeof value === 'number') return String(value)
  return fallback
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}

export async function toApiError(response: Response): Promise<ApiError> {
  let problem: ProblemDetail
  try {
    const body = asRecord(await response.json()) ?? {}
    const errors = asRecord(body.errors)
    problem = {
      type: asString(body.type, 'about:blank'),
      title: asString(body.title, response.statusText),
      status: typeof body.status === 'number' ? body.status : response.status,
      detail: asString(body.detail, 'The request failed.'),
      code: asString(body.code, 'http_error'),
      ...(errors ? { errors } : {}),
      ...(typeof body.request_id === 'string'
        ? { requestId: body.request_id }
        : {}),
    }
  } catch {
    problem = {
      type: 'about:blank',
      title: response.statusText || 'Request failed',
      status: response.status,
      detail:
        response.status >= 500
          ? 'The server is unavailable. Please try again shortly.'
          : 'The request failed.',
      code: 'http_error',
    }
  }
  return new ApiError(problem)
}

/** A user-facing message for anything thrown by the client. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) {
    // fetch rejects with a TypeError when the network itself failed.
    return 'Cannot reach the server. Check your connection and try again.'
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
