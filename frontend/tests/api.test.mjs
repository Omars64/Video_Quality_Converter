import test from 'node:test'
import assert from 'node:assert/strict'
import { apiHeaders, apiUrl, getApiBaseUrl, getApiKey, normalizeApiBaseUrl, saveApiBaseUrl, saveApiKey } from '../src/api.js'

const values = new Map()
globalThis.window = {
  localStorage: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  },
}

test('backend origin can be saved and applied to API routes', () => {
  assert.equal(saveApiBaseUrl('https://api.example.com/'), 'https://api.example.com')
  assert.equal(getApiBaseUrl(), 'https://api.example.com')
  assert.equal(apiUrl('/api/jobs'), 'https://api.example.com/api/jobs')
  assert.equal(saveApiBaseUrl(''), '')
  assert.equal(apiUrl('/api/jobs'), '/api/jobs')
})

test('backend URL rejects paths, credentials, and insecure remote origins', () => {
  for (const value of ['https://api.example.com/path', 'https://user:pass@api.example.com', 'http://api.example.com']) {
    assert.throws(() => normalizeApiBaseUrl(value))
  }
  assert.equal(normalizeApiBaseUrl('http://localhost:8000'), 'http://localhost:8000')
})

test('API key is sent only in request headers', () => {
  assert.equal(saveApiKey('  secret  '), 'secret')
  assert.equal(getApiKey(), 'secret')
  assert.deepEqual(apiHeaders({ Accept: 'application/json' }), { Accept: 'application/json', Authorization: 'Bearer secret' })
  assert.equal(saveApiKey(''), '')
  assert.deepEqual(apiHeaders(), {})
})
