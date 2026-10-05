/** Display only: keep intraday precision and never parse/convert time zones. */
export function structureDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.replace(/^(\d{4}-\d{2}-\d{2})[T ]00:00:00$/, '$1').replace(/^(\d{4}-\d{2}-\d{2})T/, '$1 ')
}
