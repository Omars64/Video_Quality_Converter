import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Capacitor, registerPlugin } from '@capacitor/core'
import { apiUrl, request } from './api.js'
import { bytes, Notice } from './Tools.jsx'
import { destinationFor, markSaved, wasSaved, pickSaveFile, writeDownload } from './destination.js'
import { formatEta, parseDownloadEta, updateProgressSample } from './eta.js'

const MediaFolder = registerPlugin('MediaFolder')

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
  try { handle = await pickSaveFile(job.outputName) }
  catch (e) { if (e.name === 'AbortError') return false; throw e }
  const { downloadUrl } = await request(`/api/jobs/${job.id}/download-ticket`, { method: 'POST' })
  const url = apiUrl(downloadUrl)
  if (Capacitor.isNativePlatform()) {
    const [{ Filesystem, Directory }, { FileTransfer }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/file-transfer')])
    const { uri } = await Filesystem.getUri({ directory: Directory.Cache, path: `${job.id}-${job.outputName || 'download'}` })
    try {
      await FileTransfer.downloadFile({ url, path: uri })
      const info = await Filesystem.stat({ path: uri })
      if (job.outputSizeBytes != null && info.size !== job.outputSizeBytes) throw new Error('Incomplete file transfer. Please download again.')
      await MediaFolder.saveToDownloads({ sourceUri: uri, name: job.outputName || 'download', mime: job.outputMime || 'application/octet-stream' })
    } finally { await Filesystem.deleteFile({ path: uri }).catch(() => {}) }
  } else if (handle) {
    await writeDownload(handle, await fetch(url), job.outputSizeBytes)
  } else {
    const a = document.createElement('a'); a.href = url; a.download = job.outputName || ''
    document.body.appendChild(a); a.click(); a.remove()
  }
  return true
}

function JobRow({ job, busy, action, autoSaving, autoError }) {
  const sample = useRef(null)
  const [measuredEta, setMeasuredEta] = useState(null)
  useEffect(() => {
    if (job.status !== 'processing' || job.progress >= 100) { sample.current = null; setMeasuredEta(null); return }
    sample.current = updateProgressSample(sample.current, Number(job.progress) || 0, Date.now())
    setMeasuredEta(sample.current.rate ? (100 - job.progress) / sample.current.rate : null)
  }, [job.status, job.progress])
  const sourceEta = parseDownloadEta(job.details?.etaSeconds ?? job.details?.downloadEtaSeconds ?? job.details?.downloadEta)
  const eta = sourceEta ?? measuredEta
  const actions = {
    queued: [['pause', 'Pause'], ['cancel', 'Cancel']], processing: [['pause', 'Pause'], ['stop', 'Stop'], ['cancel', 'Cancel']],
    paused: [['resume', 'Resume'], ['cancel', 'Cancel']], stopped: [['start', 'Restart'], ['delete', 'Remove']],
    failed: [['start', 'Retry'], ['delete', 'Remove']], cancelled: [['delete', 'Remove']], completed: [['save', 'Download media'], ['delete', 'Remove']],
  }
  return <li className="job">
    <div className="job-heading"><strong>{job.outputName && job.status === 'completed' ? job.outputName : job.originalName}</strong><span className={`status ${job.status}`}>{job.status}</span></div>
    <progress aria-label={`Progress for ${job.originalName}`} max={100} value={job.status === 'completed' ? 100 : job.progress || 0}/>
    <small className="job-eta" role="status">{job.status === 'processing' ? formatEta(eta) : job.status === 'queued' ? 'Waiting to start · ETA available during processing' : job.status === 'paused' ? 'Paused · ETA unavailable' : job.status === 'completed' ? autoSaving ? 'Saving to Downloads…' : wasSaved(job.id) ? Capacitor.isNativePlatform() ? 'Saved to Downloads' : 'Download saved' : 'Ready to download' : ''}</small>
    <div className="job-bottom"><small>{Math.round(job.progress || 0)}% {job.outputSizeBytes ? `· ${bytes(job.outputSizeBytes)}` : ''}</small><div className="job-actions">{(actions[job.status] || []).map(([op, label]) => <button key={op} className={op === 'save' ? 'primary' : ''} disabled={busy === job.id || autoSaving} onClick={() => action(job, op)}>{busy === job.id && op === 'save' ? 'Saving…' : label}</button>)}</div></div>
    <Notice error>{job.error || autoError}</Notice>
  </li>
}

export function Queue({ queue }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [autoSaving, setAutoSaving] = useState({})
  const [autoErrors, setAutoErrors] = useState({})
  const autoAttempted = useRef(new Set())
  useEffect(() => {
    for (const job of queue.jobs) {
      if (job.status !== 'completed' || !destinationFor(job.id) || autoAttempted.current.has(job.id)) continue
      autoAttempted.current.add(job.id)
      setAutoSaving(previous => ({ ...previous, [job.id]: true }))
      saveOutput(job).then(saved => { if (saved) markSaved(job.id) })
        .catch(cause => setAutoErrors(previous => ({ ...previous, [job.id]: `Automatic save failed: ${cause.message}. Use “Download media” to try again.` })))
        .finally(() => setAutoSaving(previous => ({ ...previous, [job.id]: false })))
    }
  }, [queue.jobs])
  const action = async (job, operation) => {
    setBusy(job.id); setError('')
    try {
      if (operation === 'save') {
        const saved = await saveOutput(job)
        if (saved) markSaved(job.id)
        setAutoErrors(previous => ({ ...previous, [job.id]: '' }))
      }
      else await request(`/api/jobs/${job.id}${operation === 'delete' ? '' : `/${operation}`}`, { method: operation === 'delete' ? 'DELETE' : 'POST' })
      queue.refresh()
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }
  return <section className="queue" aria-labelledby="queue-title"><div className="section-title"><h2 id="queue-title">Your files</h2><button onClick={queue.refresh} className="text-button">Refresh</button></div>
    <p className="hint">{Capacitor.isNativePlatform() ? 'New results save automatically to Downloads while this app is open.' : 'When a result is ready, Download media opens Save As. Browsers without Save As support use their download settings.'} Files on the server are temporary.</p><Notice error>{queue.error || error}</Notice>
    {!queue.jobs.length ? <p className="empty">Your uploads and downloads will appear here.</p> : <ul className="jobs">{queue.jobs.map(job => <JobRow key={job.id} job={job} busy={busy} action={action} autoSaving={Boolean(autoSaving[job.id])} autoError={autoErrors[job.id]}/>)}</ul>}
  </section>
}
