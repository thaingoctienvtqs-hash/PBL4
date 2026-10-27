/** Database timestamps without an offset are UTC; aware timestamps keep their offset. */
export function parseUtcTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null
  const text = value.trim().replace(' ', 'T')
  const aware = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  const normalized = aware ? text : text.includes('T') ? text + 'Z' : text + 'T00:00:00Z'
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatEventTime(value: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  return parseUtcTimestamp(value)?.toLocaleString('vi-VN', options) ?? 'Chưa xác định'
}
