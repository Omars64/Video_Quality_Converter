import { Capacitor, registerPlugin } from '@capacitor/core'

const MediaFolder = registerPlugin('MediaFolder')
const destinations = new Map()
const saved = new Set()
const directoryLocks = new WeakMap()

export function canChooseFolder() {
  return Capacitor.isNativePlatform() || typeof window.showDirectoryPicker === 'function'
}

export async function chooseFolder() {
  if (Capacitor.isNativePlatform()) {
    const { uri } = await MediaFolder.pickDirectory()
    return { kind: 'android', uri }
  }
  return { kind: 'web', handle: await window.showDirectoryPicker({ mode: 'readwrite' }) }
}

export function rememberDestination(jobId, destination) {
  if (jobId && destination) destinations.set(jobId, destination)
}
export function destinationFor(jobId) { return destinations.get(jobId) }
export function wasSaved(jobId) { return saved.has(jobId) }
export function markSaved(jobId) { saved.add(jobId) }

export function uniqueName(name, index) {
  if (index === 1) return name
  const dot = name.lastIndexOf('.')
  return dot > 0 ? `${name.slice(0, dot)}-${index}${name.slice(dot)}` : `${name}-${index}`
}

export async function createUniqueWebFile(directory, name) {
  const prior = directoryLocks.get(directory) || Promise.resolve()
  let release
  const done = new Promise(resolve => { release = resolve })
  directoryLocks.set(directory, prior.then(() => done))
  await prior
  try {
    for (let index = 1; index <= 1000; index++) {
      const candidate = uniqueName(name, index)
      try { await directory.getFileHandle(candidate) }
      catch (error) {
        if (error.name === 'NotFoundError') return directory.getFileHandle(candidate, { create: true })
        throw error
      }
    }
    throw new Error('The selected folder has too many files with this name.')
  } finally {
    release()
  }
}
