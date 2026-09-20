import { describe, expect, it } from 'vitest'
import { toQueryParams } from './api'
import { DEFAULT_FILTERS, type TaskFilters } from './types'

/**
 * The filter-to-query translation is pure, so it is cheap to test exactly --
 * and it is where a wrong boundary silently returns the wrong rows.
 */

function filters(overrides: Partial<TaskFilters> = {}): TaskFilters {
  return { ...DEFAULT_FILTERS, ...overrides }
}

describe('toQueryParams', () => {
  it('always sends paging and sorting', () => {
    const params = toQueryParams(filters())
    expect(params).toMatchObject({
      page: 1,
      page_size: 10,
      sort_by: 'created_at',
      sort_dir: 'desc',
    })
  })

  it('omits falsy booleans so the URL stays readable', () => {
    const params = toQueryParams(filters())
    // `overdue_only=false` would be sent as a string and override nothing
    // useful; leaving it out keeps the server default.
    expect(params.overdue_only).toBeUndefined()
    expect(params.assigned_to_me).toBeUndefined()
  })

  it('sends booleans when enabled', () => {
    const params = toQueryParams(filters({ overdue_only: true, assigned_to_me: true }))
    expect(params.overdue_only).toBe(true)
    expect(params.assigned_to_me).toBe(true)
  })

  it('passes multi-value filters through as arrays', () => {
    // The client serialises an array as repeated keys, which is what the API
    // accepts: ?status=todo&status=in_progress
    const params = toQueryParams(filters({ status: ['todo', 'in_progress'] }))
    expect(params.status).toEqual(['todo', 'in_progress'])
  })

  it('drops a blank search instead of sending an empty string', () => {
    expect(toQueryParams(filters({ search: '   ' })).search).toBeUndefined()
    expect(toQueryParams(filters({ search: ' audit ' })).search).toBe('audit')
  })

  it('extends "due before" to the end of the chosen day', () => {
    // A date input yields `2026-07-01` with no time. "Due before 1 July"
    // means including all of 1 July; sending midnight would hide every task
    // due during the day the user picked.
    const params = toQueryParams(filters({ due_before: '2026-07-01' }))
    expect(params.due_before).toBe('2026-07-01T23:59:59.999Z')
  })

  it('anchors "due after" to the start of the chosen day', () => {
    const params = toQueryParams(filters({ due_after: '2026-07-01' }))
    expect(params.due_after).toBe('2026-07-01T00:00:00.000Z')
  })

  it('leaves a malformed date untouched for the server to reject', () => {
    // Guessing at a repair here would turn a clear 422 into wrong results.
    expect(toQueryParams(filters({ due_after: 'not-a-date' })).due_after).toBe(
      'not-a-date',
    )
  })
})
