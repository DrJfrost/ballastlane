/**
 * Joins class names, dropping falsy entries.
 *
 * Lives in `lib/` rather than alongside the components so that the UI module
 * exports components only -- which is what lets React Fast Refresh replace
 * them without reloading the page.
 */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}
