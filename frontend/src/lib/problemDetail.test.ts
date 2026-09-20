import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage, toApiError } from './problemDetail'

/**
 * The error layer is worth testing because everything downstream depends on
 * it: a form that cannot find its field error just silently shows nothing.
 */

function problemResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  })
}

describe('toApiError', () => {
  it('parses a problem document', async () => {
    const error = await toApiError(
      problemResponse(409, {
        title: 'Conflicting state',
        status: 409,
        detail: 'Task is already completed.',
        code: 'conflict',
        request_id: 'abc123',
      }),
    )

    expect(error.status).toBe(409)
    expect(error.code).toBe('conflict')
    expect(error.message).toBe('Task is already completed.')
    expect(error.requestId).toBe('abc123')
  })

  it('maps schema validation errors to fields', async () => {
    const error = await toApiError(
      problemResponse(422, {
        title: 'Validation error',
        status: 422,
        detail: 'The request payload is invalid.',
        code: 'validation_error',
        errors: { title: 'String should have at least 3 characters' },
      }),
    )

    expect(error.isValidationError).toBe(true)
    expect(error.messageFor('title')).toContain('at least 3')
    expect(error.messageFor('description')).toBeUndefined()
  })

  it('strips the location prefix FastAPI adds to query errors', async () => {
    const error = await toApiError(
      problemResponse(422, {
        title: 'Validation error',
        status: 422,
        detail: 'invalid',
        code: 'validation_error',
        errors: { 'query.page_size': 'Input should be less than or equal to 100' },
      }),
    )

    // A form looks up `page_size`, not `query.page_size`.
    expect(error.messageFor('page_size')).toContain('less than or equal')
  })

  it('attaches a domain error to the field it blames', async () => {
    const error = await toApiError(
      problemResponse(422, {
        title: 'Validation error',
        status: 422,
        detail: 'Due date must be in the future.',
        code: 'validation_error',
        errors: { field: 'due_date', value: '2020-01-01T00:00:00Z' },
      }),
    )

    // The domain shape carries metadata, not a per-field message, so the
    // top-level detail is what belongs under the field.
    expect(error.field).toBe('due_date')
    expect(error.messageFor('due_date')).toBe('Due date must be in the future.')
    expect(error.messageFor('title')).toBeUndefined()
  })

  it('survives a non-JSON body from a proxy', async () => {
    const error = await toApiError(
      new Response('<html>502 Bad Gateway</html>', { status: 502 }),
    )

    // A gateway returning HTML must not crash the parser.
    expect(error.status).toBe(502)
    expect(error.message).toContain('unavailable')
    expect(error.isRetryable).toBe(true)
  })
})

describe('ApiError classification', () => {
  const build = (status: number) =>
    new ApiError({
      type: 'about:blank',
      title: 'x',
      status,
      detail: 'x',
      code: 'x',
    })

  it('treats 401 as an auth problem', () => {
    expect(build(401).isAuthError).toBe(true)
    expect(build(403).isAuthError).toBe(false)
  })

  it('only retries transient failures', () => {
    // Repeating a 404 or a 409 gets the same answer; retrying wastes a
    // round trip and delays the error the user needs to see.
    expect(build(500).isRetryable).toBe(true)
    expect(build(429).isRetryable).toBe(true)
    expect(build(404).isRetryable).toBe(false)
    expect(build(409).isRetryable).toBe(false)
  })
})

describe('errorMessage', () => {
  it('explains a network failure in plain language', () => {
    // fetch rejects with a TypeError when the request never left.
    expect(errorMessage(new TypeError('Failed to fetch'))).toContain('Cannot reach')
  })

  it('falls back for unknown throwables', () => {
    expect(errorMessage('a bare string')).toBe('Something went wrong.')
  })
})
