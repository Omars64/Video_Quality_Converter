const SERVER_KEY = 'media-forge-server'
const SESSION_KEY = 'media-forge-session'
const DEFAULT_SERVER = import.meta.env?.VITE_API_BASE_URL || ''

export function getApiBaseUrl() {
  try { return window.localStorage.getItem(SERVER_KEY) || DEFAULT_SERVER } catch { return DEFAULT_SERVER }
}
export function normalizeApiBaseUrl(value) {
  const input = value.trim()
  if (!input) return ''
  let url
  try { url = new URL(input) } catch { throw new Error('Enter a valid server URL.') }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('Enter a server address such as https://api.example.com.')
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(url.hostname)) throw new Error('Use HTTPS for a remote server.')
  return url.origin
}
export function saveApiBaseUrl(value) {
  const normalized = normalizeApiBaseUrl(value)
  window.localStorage.setItem(SERVER_KEY, normalized)
  clearSession()
  return normalized
}
export function apiUrl(path) { return `${getApiBaseUrl()}${path}` }
export function getSession() {
  try { return window.sessionStorage.getItem(SESSION_KEY) || '' } catch { return '' }
}
export function saveSession(token) { window.sessionStorage.setItem(SESSION_KEY, token) }
export function clearSession() {
  window.sessionStorage.removeItem(SESSION_KEY)
  window.dispatchEvent(new Event('media-forge:signout'))
}
export function apiHeaders(extra = {}) {
  const token = getSession()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}
export async function parseResponse(response) {
  const data = await response.json().catch(() => null)
  if (response.status === 401 && getSession()) clearSession()
  if (response.status === 404 && !data?.detail) throw new Error('The processing service is not connected. Please contact the app owner.')
  if (response.status === 502 || response.status === 504) throw new Error('The processing service is starting. Please try again in a minute.')
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `The request could not be completed (${response.status}).`)
  if (!data || typeof data !== 'object') throw new Error('The processing service is not connected. Please contact the app owner.')
  return data
}
export async function request(path, { body, ...options } = {}) {
  let response
  try {
    response = await fetch(apiUrl(path), {
      ...options, headers: apiHeaders(body ? { 'Content-Type': 'application/json' } : {}),
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal: options.signal || AbortSignal.timeout(100_000),
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Unable to reach the processing service. It may be waking up; please try again in a minute.')
  }
  return response.status === 204 ? null : parseResponse(response)
}
export function upload(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl(path))
    for (const [name, value] of Object.entries(apiHeaders())) xhr.setRequestHeader(name, value)
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress?.(Math.round(e.loaded / e.total * 100)) }
    xhr.onerror = () => reject(new Error('Upload interrupted. Check your connection and try again.'))
    xhr.onload = () => parseResponse(new Response(xhr.responseText, { status: xhr.status })).then(resolve, reject)
    xhr.send(form)
  })
}
