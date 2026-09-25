import test from 'node:test'
import assert from 'node:assert/strict'
import { formatEta, parseDownloadEta, updateProgressSample } from '../src/eta.js'

test('download ETA parses real extractor values', () => {
  assert.equal(parseDownloadEta('01:23'), 83)
  assert.equal(parseDownloadEta('1:02:03'), 3723)
  assert.equal(parseDownloadEta('8s'), 8)
  assert.equal(parseDownloadEta('N/A'), null)
  assert.equal(formatEta(83), 'About 2 minutes left')
  assert.equal(formatEta(null), 'Calculating time left…')
})

test('measured ETA requires progress over elapsed time and resets after restart', () => {
  const first = updateProgressSample(null, 10, 1000)
  assert.equal(first.rate, null)
  const second = updateProgressSample(first, 30, 5000)
  assert.equal(second.rate, 5)
  assert.equal(updateProgressSample(second, 30, 8000), second)
  const restarted = updateProgressSample(second, 0, 9000)
  assert.equal(restarted.rate, null)
})
