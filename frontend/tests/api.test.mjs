import test from 'node:test'
import assert from 'node:assert/strict'
import { apiHeaders, apiUrl, getApiBaseUrl, getSession, normalizeApiBaseUrl, saveApiBaseUrl, saveSession, clearSession, parseResponse } from '../src/api.js'

const values = new Map()
globalThis.window = {
  localStorage: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  },
  sessionStorage: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  },
  dispatchEvent: () => {},
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

test('session is sent only in request headers and cleared on signout', () => {
  saveSession('secret')
  assert.equal(getSession(), 'secret')
  assert.deepEqual(apiHeaders({ Accept: 'application/json' }), { Accept: 'application/json', Authorization: 'Bearer secret' })
  clearSession()
  assert.deepEqual(apiHeaders(), {})
})

test('HTML errors are explained and expired sessions cleared', async () => {
  await assert.rejects(parseResponse(new Response('<html>404</html>', {status:404})), /not connected/)
  await assert.rejects(parseResponse(new Response('bad gateway', {status:502})), /starting/)
  saveSession('expired')
  await assert.rejects(parseResponse(new Response(JSON.stringify({detail:'Please sign in'}), {status:401})), /sign in/)
  assert.equal(getSession(), '')
})
