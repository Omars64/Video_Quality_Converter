import test from 'node:test'
import assert from 'node:assert/strict'
import { pickSaveFile, writeDownload } from '../src/destination.js'

test('Save As opens for the actual file without directory access', async () => {
  const handle = { name: 'reel.mp4' }
  let options
  globalThis.window = { showSaveFilePicker(value) { options = value; return Promise.resolve(handle) } }
  const selected = pickSaveFile('reel.mp4')
  assert.deepEqual(options, { suggestedName: 'reel.mp4' }) // before awaiting
  assert.equal(await selected, handle)
  delete globalThis.window
})

test('cancellation propagates without starting a download', async () => {
  globalThis.window = { showSaveFilePicker() { throw new DOMException('Canceled', 'AbortError') } }
  await assert.rejects(pickSaveFile('reel.mp4'), { name: 'AbortError' })
  delete globalThis.window
})

test('a complete transfer writes identical bytes and closes atomically', async () => {
  const chunks = []; let closed = false
  const handle = { async createWritable() { return {
    async write(value) { chunks.push(...value) },
    async close() { closed = true },
    async abort() { assert.fail('unexpected abort') },
  } } }
  await writeDownload(handle, new Response(new Uint8Array([1, 2, 3, 4])), 4)
  assert.deepEqual(chunks, [1, 2, 3, 4])
  assert.equal(closed, true)
})

test('an incomplete transfer aborts instead of committing a damaged file', async () => {
  let aborted = false
  const handle = { async createWritable() { return {
    async write() {}, async close() { assert.fail('incomplete file committed') },
    async abort() { aborted = true },
  } } }
  await assert.rejects(writeDownload(handle, new Response('short'), 100), /incomplete/)
  assert.equal(aborted, true)
})

test('HTTP errors do not open or overwrite a file', async () => {
  await assert.rejects(writeDownload({ createWritable() { assert.fail('file opened') } }, new Response('', { status: 500 }), 0), /failed/)
})
