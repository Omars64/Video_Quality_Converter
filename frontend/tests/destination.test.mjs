import test from 'node:test'
import assert from 'node:assert/strict'
import { createUniqueWebFile, uniqueName } from '../src/destination.js'

test('new saves do not overwrite similarly named files', async () => {
  const existing = new Set(['movie.mp4', 'movie-2.mp4'])
  const directory = {
    async getFileHandle(name, options = {}) {
      if (existing.has(name)) return { name }
      if (!options.create) throw new DOMException('Missing', 'NotFoundError')
      existing.add(name)
      return { name }
    },
  }
  assert.equal((await createUniqueWebFile(directory, 'movie.mp4')).name, 'movie-3.mp4')
  const concurrent = await Promise.all([createUniqueWebFile(directory, 'movie.mp4'), createUniqueWebFile(directory, 'movie.mp4')])
  assert.deepEqual(concurrent.map(item => item.name), ['movie-4.mp4', 'movie-5.mp4'])
  assert.equal(uniqueName('photo', 2), 'photo-2')
})
