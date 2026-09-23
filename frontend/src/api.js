const STORAGE_KEY = 'media-forge-api-base-url'
const API_KEY_STORAGE = 'media-forge-api-key'

export function getApiBaseUrl() {
  try { return window.localStorage.getItem(STORAGE_KEY) || '' } catch { return '' }
}

export function normalizeApiBaseUrl(value) {
  const input = value.trim()
  if (!input) return ''
  let url
  try { url = new URL(input) } catch { throw new Error('Enter a valid backend URL.') }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Enter the backend origin, such as https://api.example.com.')
  }
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(url.hostname)) {
    throw new Error('Use HTTPS for a remote backend.')
  }
  return url.origin
}

export function saveApiBaseUrl(value) {
  const normalized = normalizeApiBaseUrl(value)
  window.localStorage.setItem(STORAGE_KEY, normalized)
  return normalized
}

export function apiUrl(path) {
  return `${getApiBaseUrl()}${path}`
}

export function getApiKey() {
  try { return window.localStorage.getItem(API_KEY_STORAGE) || '' } catch { return '' }
}

export function saveApiKey(value) {
  const key = value.trim()
  window.localStorage.setItem(API_KEY_STORAGE, key)
  return key
}

export function apiHeaders(extra = {}) {
  const key = getApiKey()
  return key ? { ...extra, Authorization: `Bearer ${key}` } : extra
}
