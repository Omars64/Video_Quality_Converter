import { Capacitor } from '@capacitor/core'
const destinations = new Map()
const saved = new Set()
export function rememberDestination(jobId) {
  if (jobId && Capacitor.isNativePlatform()) destinations.set(jobId, { kind: 'android-downloads' })
}
export function destinationFor(jobId) { return destinations.get(jobId) }
export function wasSaved(jobId) { return saved.has(jobId) }
export function markSaved(jobId) { saved.add(jobId) }

// Called directly from the Download button, before any network await.
export async function pickSaveFile(name) {
  if (Capacitor.isNativePlatform() || typeof window.showSaveFilePicker !== 'function') return null
  return window.showSaveFilePicker({ suggestedName: name || 'download' })
}

export async function writeDownload(handle, response, expectedSize) {
  if (!response.ok) throw new Error('The download failed. Please try again.')
  const writable = await handle.createWritable()
  let received = 0
  try {
    if (response.body) {
      const reader = response.body.getReader()
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          received += value.byteLength
          await writable.write(value)
        }
      } finally { await reader.cancel(); reader.releaseLock() }
    } else {
      const blob = await response.blob()
      received = blob.size
      await writable.write(blob)
    }
    if (expectedSize != null && received !== expectedSize) throw new Error('The file transfer was incomplete. Please download again.')
    await writable.close()
  } catch (error) {
    await writable.abort().catch(() => {})
    throw error
  }
}
