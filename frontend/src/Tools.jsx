import React, { useRef, useState } from 'react'
import { request, upload } from './api.js'
import { canChooseFolder, chooseFolder, rememberDestination } from './destination.js'

export const bytes = value => value == null ? '' : value < 1024 * 1024 ? `${(value / 1024).toFixed(0)} KB` : `${(value / (1024 * 1024)).toFixed(1)} MB`
export function Field({ label, children, hint }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}
function Select({ label, value, onChange, options }) {
  return <Field label={label}><select value={value} onChange={e => onChange(e.target.value)}>{options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></Field>
}
function SaveLocation({ value, onChange }) {
  return canChooseFolder()
    ? <div><Select label="Save finished files" value={value} onChange={onChange} options={[["folder", "Choose a folder when starting"], ["later", "Use Save file when finished"]]}/>{value === 'folder' && <p className="hint save-hint">Keep the app open until the result is saved to this folder.</p>}</div>
    : <p className="hint">Use “Save file” when the result is ready to choose where it goes.</p>
}
async function startingFolder(choice) {
  if (choice !== 'folder' || !canChooseFolder()) return { destination: null, cancelled: false }
  try { return { destination: await chooseFolder(), cancelled: false } }
  catch (error) {
    if (error.name === 'AbortError' || /cancelled|canceled/i.test(error.message)) return { destination: null, cancelled: true }
    throw error
  }
}
export function Notice({ error, children }) {
  return children ? <p className={`notice ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>{children}</p> : null
}
function FilePicker({ files, setFiles, accept }) {
  const input = useRef(null)
  const add = list => setFiles(prev => [...prev, ...Array.from(list || []).filter(n => !prev.some(p => p.name === n.name && p.size === n.size && p.lastModified === n.lastModified))])
  return <div className="file-picker">
    <input ref={input} className="file-input" type="file" multiple accept={accept} aria-label="Choose files" onChange={e => { add(e.target.files); e.target.value = '' }}/>
    <button type="button" className="dropzone" onClick={() => input.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}>
      <span aria-hidden="true" className="upload-icon">↑</span><strong>Choose files</strong><span>or drag and drop them here</span>
    </button>
    {files.length > 0 && <ul className="files">{files.map((file, index) => <li key={`${file.name}-${index}`}><span>{file.name}<small>{bytes(file.size)}</small></span><button type="button" aria-label={`Remove ${file.name}`} onClick={() => setFiles(items => items.filter((_, i) => i !== index))}>×</button></li>)}</ul>}
  </div>
}
export function UploadTool({ type, refresh }) {
  const [files, setFiles] = useState([])
  const [resolution, setResolution] = useState('1080')
  const [scale, setScale] = useState('2')
  const [strength, setStrength] = useState('natural')
  const [format, setFormat] = useState(type === 'convert' ? 'pdf' : 'jpg')
  const [profile, setProfile] = useState('fast')
  const [enhancement, setEnhancement] = useState('light')
  const [engine, setEngine] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saveChoice, setSaveChoice] = useState(canChooseFolder() ? 'folder' : 'later')
  const submit = async e => {
    e.preventDefault()
    if (!files.length || busy) return
    let destination
    try {
      const selection = await startingFolder(saveChoice)
      if (selection.cancelled) return
      destination = selection.destination
    } catch (error) { setError(error.message); return }
    setBusy(true); setProgress(0); setError(''); setMessage('')
    const failures = []; let accepted = 0
    const batches = type === 'convert' ? [files] : files.map(file => [file])
    for (let i = 0; i < batches.length; i++) {
      const form = new FormData()
      for (const file of batches[i]) form.append(type === 'convert' ? 'files' : 'file', file)
      const values = type === 'video' ? { target_height: resolution, engine, profile, enhancement } : type === 'photo' ? { scale, strength, output_format: format } : { output_format: format }
      Object.entries(values).forEach(([name, value]) => form.append(name, value))
      const endpoint = { video: '/api/video/enhance', photo: '/api/photo/enhance', convert: '/api/images/convert' }[type]
      try {
        const job = await upload(endpoint, form, value => setProgress(Math.round((i + value / 100) / batches.length * 100)))
        rememberDestination(job.id, destination)
        accepted++; refresh()
      } catch (e) { failures.push({ files: batches[i], error: e.message }) }
    }
    setFiles(failures.flatMap(item => item.files))
    setError(failures.map(item => `${item.files[0].name}: ${item.error}`).join(' '))
    setMessage(accepted ? `${accepted} ${accepted === 1 ? 'job added' : 'jobs added'}. Your results will appear below.` : '')
    setBusy(false)
  }
  return <form onSubmit={submit} className="tool-form">
    <FilePicker files={files} setFiles={setFiles} accept={type === 'video' ? 'video/*,.mkv,.mts,.m2ts,.ts' : type === 'convert' ? 'image/*,.pdf,.docx' : 'image/*'}/>
    <div className="field-grid">
      {type === 'video' && <Select label="Output quality" value={resolution} onChange={setResolution} options={[[1080, '1080p · Full HD'], [1440, '1440p · QHD'], [2160, '4K · Ultra HD']]}/>}
      {type === 'photo' && <><Select label="Image size" value={scale} onChange={setScale} options={[[1, 'Original size'], [2, '2× larger'], [4, '4× larger']]}/><Select label="Enhancement" value={strength} onChange={setStrength} options={[["natural", 'Natural'], ['strong', 'Strong']]}/></>}
      {type !== 'video' && <Select label="Output format" value={format} onChange={setFormat} options={(type === 'convert' ? ['pdf', 'docx', 'jpg', 'png', 'webp', 'bmp', 'tiff'] : ['jpg', 'png', 'webp']).map(value => [value, value.toUpperCase()])}/>}
    </div>
    {type === 'video' && <details className="advanced"><summary>More options</summary><div className="field-grid">
      <Select label="Processing speed" value={profile} onChange={setProfile} options={[["fast", 'Fast'], ['balanced', 'Balanced'], ['quality', 'High quality']]}/>
      <Select label="Enhancement" value={enhancement} onChange={setEnhancement} options={[["light", 'Light'], ['medium', 'Medium'], ['strong', 'Strong']]}/>
      <Select label="Processor" value={engine} onChange={setEngine} options={[["auto", 'Automatic'], ['cpu', 'CPU'], ['nvidia', 'NVIDIA'], ['qsv', 'Intel Quick Sync']]}/>
    </div></details>}
    {type === 'convert' && <p className="hint">Images, PDF, and DOCX. Multiple image outputs download as a ZIP. Documents are converted as pages; DOCX output contains page images.</p>}
    <SaveLocation value={saveChoice} onChange={setSaveChoice}/>
    <button className="primary" disabled={!files.length || busy}>{busy ? `Uploading · ${progress}%` : type === 'video' ? 'Enhance video' : type === 'photo' ? 'Enhance photos' : 'Convert files'}</button>
    <Notice>{message}</Notice><Notice error>{error}</Notice>
  </form>
}
export function YouTubeTool({ refresh }) {
  const [url, setUrl] = useState('')
  const [format, setFormat] = useState('mp4')
  const [quality, setQuality] = useState('best')
  const [audio, setAudio] = useState('192')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saveChoice, setSaveChoice] = useState(canChooseFolder() ? 'folder' : 'later')
  const submit = async e => {
    e.preventDefault(); if (busy) return
    let destination
    try {
      const selection = await startingFolder(saveChoice)
      if (selection.cancelled) return
      destination = selection.destination
    } catch (error) { setError(error.message); return }
    setBusy(true); setError(''); setMessage('')
    try {
      const job = await request('/api/youtube/download', { method: 'POST', body: { url: url.trim(), outputType: format, quality, audioQuality: audio } })
      rememberDestination(job.id, destination)
      setMessage('Download added. Your file will appear below.'); refresh()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <form className="tool-form" onSubmit={submit}>
    <Field label="YouTube link"><input type="url" required placeholder="Paste a video or Shorts link" value={url} onChange={e => setUrl(e.target.value)}/></Field>
    <div className="field-grid"><Select label="Format" value={format} onChange={setFormat} options={[["mp4", 'MP4 video'], ['mp3', 'MP3 audio']]}/>
      {format === 'mp4' ? <Select label="Quality" value={quality} onChange={setQuality} options={[["best", 'Best available'], ['2160', '4K'], ['1440', '1440p'], ['1080', '1080p'], ['720', '720p'], ['480', '480p'], ['360', '360p']]}/> : <Select label="Audio quality" value={audio} onChange={setAudio} options={[[128, '128 kbps'], [192, '192 kbps'], [256, '256 kbps'], [320, '320 kbps']]}/>}
    </div><SaveLocation value={saveChoice} onChange={setSaveChoice}/><button className="primary" disabled={!url.trim() || busy}>{busy ? 'Adding…' : `Download ${format.toUpperCase()}`}</button>
    <Notice>{message}</Notice><Notice error>{error}</Notice>
  </form>
}
export function LinkTool({ refresh }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saveChoice, setSaveChoice] = useState(canChooseFolder() ? 'folder' : 'later')
  const submit = async e => {
    e.preventDefault(); if (busy) return
    const urls = [...new Set(text.split(/\r?\n/).map(value => value.trim()).filter(Boolean))]
    let destination
    try {
      const selection = await startingFolder(saveChoice)
      if (selection.cancelled) return
      destination = selection.destination
    } catch (error) { setError(error.message); return }
    setBusy(true); setError(''); setMessage(''); const failures = []; let count = 0
    for (const url of urls) {
      try { const job = await request('/api/remote/download', { method: 'POST', body: { url } }); rememberDestination(job.id, destination); count++; refresh() }
      catch (e) { failures.push({ url, error: e.message }) }
    }
    setText(failures.map(item => item.url).join('\n')); setError(failures.map(item => item.error).join(' '))
    setMessage(count ? `${count} ${count === 1 ? 'download added' : 'downloads added'}.` : ''); setBusy(false)
  }
  return <form className="tool-form" onSubmit={submit}><Field label="Photo, video, or social post link" hint="You can paste several links, one per line."><textarea required rows={4} value={text} onChange={e => setText(e.target.value)} placeholder="https://…"/></Field>
    <SaveLocation value={saveChoice} onChange={setSaveChoice}/>
    <button className="primary" disabled={!text.trim() || busy}>{busy ? 'Adding…' : 'Download media'}</button><Notice>{message}</Notice><Notice error>{error}</Notice>
  </form>
}
