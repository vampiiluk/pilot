// Chart series carry time as epoch milliseconds, because that is what the
// monitoring endpoints emit and what every axis bound is arithmetic on
// (`now - window_seconds * 1000`). A `time` x-axis does not accept that.
//
// frappe-ui places a point on a time axis with `toDate()`, which reads a `Date`
// or a string matching an ISO date and nothing else - a bare number returns null,
// so every row is dropped and the chart reports "No data to show" while holding
// hundreds of points. `plotRows` is called with `quiet = true`, so its "Dropped N
// rows" warning never fires and the console stays silent.
//
// Converting at the chart boundary keeps the wire format numeric: the axis
// min/max are still epoch milliseconds, and only the rows handed to the chart
// carry the ISO string it can read.

/** One chart row: the `time` column becomes an ISO string, everything else passes through. */
export type ChartRow = Record<string, unknown>

const isoOrNull = (value: unknown): string | null => {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString()
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value).toISOString()
  return null
}

/**
 * Copy a series with its `time` column as ISO strings, for a `type: 'time'`
 * x-axis. A row with no readable time is passed through untouched: it has
 * nowhere on the scale to sit, and the chart drops it with a warning rather than
 * being handed a fabricated instant.
 */
export const withIsoTime = (rows: readonly ChartRow[], key = 'time'): ChartRow[] =>
  rows.map((row) => {
    const iso = isoOrNull(row[key])
    return iso === null ? row : { ...row, [key]: iso }
  })
