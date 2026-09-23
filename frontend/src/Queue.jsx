import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Capacitor } from '@capacitor/core'
import { apiUrl, request } from './api.js'
import { bytes, Notice } from './Tools.jsx'

export function useQueue() {
  const [jobs, setJobs] = useState([])
  const [error, setError] = useState('')
  const controller = useRef(null)
  const refresh = useCallback(async () => {
    if (controller.current && !controller.current.signal.aborted) return
    const current = new AbortController(); controller.current = current
    const timeout = window.setTimeout(() => current.abort(), 100_000)
    try {
      const result = await request('/api/jobs?limit=100', { signal: current.signal })
      if (!Array.isArray(result.jobs)) throw new Error('The processing service returned an unexpected response.')
      if (!current.signal.aborted) { setJobs(result.jobs); setError('') }
    } catch (e) { if (!current.signal.aborted) setError(e.message) }
    finally { window.clearTimeout(timeout); if (controller.current === current) controller.current = null }
  }, [])
  useEffect(() => {
    refresh()
    const timer = window.setInterval(() => { if (!document.hidden) refresh() }, 3000)
    return () => { window.clearInterval(timer); controller.current?.abort() }
  }, [refresh])
  return { jobs, error, refresh }
}

async function saveOutput(job) {
  let handle
  if (!Capacitor.isNativePlatform() && 'showSaveFilePicker' in window) {
    try { handle = await window.showSaveFilePicker({ suggestedName: job.outputName || 'download' }) }
    catch (e) { if (e.name === 'AbortError') return }
  }
  const { downloadUrl } = await request(`/api/jobs/${job.id}/download-ticket`, { method: 'POST' })
  const url = apiUrl(downloadUrl)
  if (Capacitor.isNativePlatform()) {
    const [{ Filesystem, Directory }, { FileTransfer }, { Share }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/file-transfer'), import('@capacitor/share')])
    const { uri } = await Filesystem.getUri({ directory: Directory.Cache, path: `${job.id}-${job.outputName || 'download'}` })
    await FileTransfer.downloadFile({ url, path: uri })
    await Share.share({ title: job.outputName || 'Download', files: [uri] })
  } else if (handle) {
    const response = await fetch(url)
    if (!response.ok) throw new Error('The download failed. Please try again.')
    const writable = await handle.createWritable()
    if (response.body) await response.body.pipeTo(writable)
    else { await writable.write(await response.blob()); await writable.close() }
  } else {
    const a = document.createElement('a'); a.href = url; a.download = job.outputName || ''
    document.body.appendChild(a); a.click(); a.remove()
  }
}

export function Queue({ queue }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const action = async (job, operation) => {
    setBusy(job.id); setError('')
    try {
      if (operation === 'save') await saveOutput(job)
      else await request(`/api/jobs/${job.id}${operation === 'delete' ? '' : `/${operation}`}`, { method: operation === 'delete' ? 'DELETE' : 'POST' })
      queue.refresh()
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }
  const actions = {
    queued: [['pause', 'Pause'], ['cancel', 'Cancel']], processing: [['pause', 'Pause'], ['stop', 'Stop'], ['cancel', 'Cancel']],
    paused: [['resume', 'Resume'], ['cancel', 'Cancel']], stopped: [['start', 'Restart'], ['delete', 'Remove']],
    failed: [['start', 'Retry'], ['delete', 'Remove']], cancelled: [['delete', 'Remove']], completed: [['save', 'Save file'], ['delete', 'Remove']],
  }
  return <section className="queue" aria-labelledby="queue-title"><div className="section-title"><h2 id="queue-title">Your files</h2><button onClick={queue.refresh} className="text-button">Refresh</button></div>
    <p className="hint">Files are temporary. Save completed results to keep them.</p><Notice error>{queue.error || error}</Notice>
    {!queue.jobs.length ? <p className="empty">Your uploads and downloads will appear here.</p> : <ul className="jobs">{queue.jobs.map(job => <li key={job.id} className="job">
      <div className="job-heading"><strong>{job.outputName && job.status === 'completed' ? job.outputName : job.originalName}</strong><span className={`status ${job.status}`}>{job.status}</span></div>
      <progress aria-label={`Progress for ${job.originalName}`} max={100} value={job.status === 'completed' ? 100 : job.progress || 0}/>
      <div className="job-bottom"><small>{Math.round(job.progress || 0)}% {job.outputSizeBytes ? `· ${bytes(job.outputSizeBytes)}` : ''}</small><div className="job-actions">{(actions[job.status] || []).map(([op, label]) => <button key={op} className={op === 'save' ? 'primary' : ''} disabled={busy === job.id} onClick={() => action(job, op)}>{busy === job.id && op === 'save' ? 'Saving…' : label}</button>)}</div></div>
      <Notice error>{job.error}</Notice>
    </li>)}</ul>}
  </section>
}
