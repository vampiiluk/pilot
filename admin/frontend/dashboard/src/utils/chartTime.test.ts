import assert from 'node:assert/strict'
import test from 'node:test'

import { withIsoTime } from './chartTime.ts'

const EPOCH = 1790920707534
const ISO = '2026-10-02T05:58:27.534Z'

// A `time` x-axis in frappe-ui places a point with toDate(), which reads a Date
// or an ISO string and nothing else. A bare number returns null, every row is
// dropped, and the chart reports "No data to show" while holding the data.

test('epoch milliseconds become an ISO string', () => {
  const [row] = withIsoTime([{ time: EPOCH, Connected: 1 }])

  assert.equal(row.time, ISO)
  assert.equal(row.Connected, 1)
})

test('a Date becomes its ISO string rather than being re-wrapped', () => {
  const [row] = withIsoTime([{ time: new Date(EPOCH) }])

  assert.equal(row.time, ISO)
})

test('a value that is already ISO passes through unchanged', () => {
  const [row] = withIsoTime([{ time: ISO }])

  assert.equal(row.time, ISO)
})

test('the time column can be named', () => {
  const [row] = withIsoTime([{ at: EPOCH }], 'at')

  assert.equal(row.at, ISO)
})

// A row with no readable instant has nowhere on a time axis to sit. Leaving it
// as it is lets the chart drop it with a warning, rather than inventing a date.
test('a row with no usable time is passed through untouched', () => {
  const rows = [{ time: null }, { time: undefined }, { time: 'not-a-date' }, {}]

  assert.deepEqual(withIsoTime(rows), rows)
})

test('the input series is not mutated', () => {
  const row = { time: EPOCH }
  const rows = [row]

  withIsoTime(rows)

  assert.equal(row.time, EPOCH)
  assert.equal(rows[0], row)
})

test('an empty series stays empty', () => {
  assert.deepEqual(withIsoTime([]), [])
})
