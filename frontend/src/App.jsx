import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Capacitor } from '@capacitor/core'
import { apiHeaders, apiUrl, getApiBaseUrl, getApiKey, saveApiBaseUrl, saveApiKey } from './api.js'

function Icon({ name, size = 18 }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
  const icons = {
    film: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4"/></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m5 17 4.5-4.5 3 3 2-2L19 18"/></>,
    files: <><path d="M8 3h8l4 4v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M16 3v5h5M10 12h6M10 16h6"/></>,
    youtube: <><rect x="3" y="6" width="18" height="12" rx="4"/><path d="m10 9 5 3-5 3V9Z"/></>,
    link: <><path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/></>,
    upload: <><path d="M12 16V4m0 0-4 4m4-4 4 4"/><path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/></>,
    sparkles: <><path d="m12 3 1.2 3.4L16.5 8l-3.3 1.6L12 13l-1.2-3.4L7.5 8l3.3-1.6L12 3Z"/><path d="m18.5 14 .8 2.1 2.2.9-2.2.9-.8 2.1-.8-2.1-2.2-.9 2.2-.9.8-2.1Z"/></>,
    download: <><path d="M12 4v11m0 0 4-4m-4 4-4-4"/><path d="M5 19h14"/></>,
    check: <><circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
    wand: <><path d="m15 4 5 5L8 21l-5-5L15 4Z"/><path d="m6 13 5 5M5 4v3M3.5 5.5h3M19 16v4M17 18h4"/></>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    play: <path d="m8 5 11 7-11 7V5Z"/>,
    stop: <rect x="6" y="6" width="12" height="12" rx="1"/>,
    x: <><path d="m6 6 12 12M18 6 6 18"/></>,
    trash: <><path d="M5 7h14M9 7V4h6v3M8 10v8M12 10v8M16 10v8M7 7l1 14h8l1-14"/></>,
    cpu: <><rect x="7" y="7" width="10" height="10" rx="1"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3M10 10h4v4h-4z"/></>,
    queue: <><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/></>,
    music: <><path d="M9 18V5l10-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></>,
  }
  return <svg {...common}>{icons[name] || icons.info}</svg>
}

const TOOLS = [
  { id: 'video', label: 'Video Enhance', caption: 'Up to 1080p source → 1080p / 1440p / 4K', icon: 'film' },
  { id: 'photo', label: 'Photo Enhance', caption: 'Batch sharpen, clean and upscale', icon: 'image' },
  { id: 'convert', label: 'Image Convert', caption: 'PDF, Word and image formats', icon: 'files' },
  { id: 'youtube', label: 'YouTube', caption: 'MP4 qualities or tagged MP3', icon: 'youtube' },
  { id: 'link', label: 'Internet Link', caption: 'Public video / photo resolver', icon: 'link' },
]

function formatBytes(bytes) {
  if (bytes === undefined || bytes === null) return '—'
  let value = Number(bytes); let i = 0
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1 }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`
}
function formatDuration(seconds) {
  if (seconds === undefined || seconds === null || Number.isNaN(Number(seconds))) return '—'
  const total = Math.max(0, Math.round(Number(seconds))); const h = Math.floor(total / 3600); const m = Math.floor((total % 3600) / 60); const s = total % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}
async function parseResponse(response) {
  const text = await response.text(); let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status}).`)
  if (data === null) throw new Error('Backend did not return JSON. Set the backend URL in Backend connection.')
  return data
}
function postForm(endpoint, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open('POST', apiUrl(endpoint))
    for (const [name, value] of Object.entries(apiHeaders())) xhr.setRequestHeader(name, value)
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)) }
    xhr.onerror = () => reject(new Error('Upload failed. Check that the backend is reachable.'))
    xhr.onload = () => {
      let data = null; try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null } catch { data = null }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else reject(new Error(data?.detail || `Request failed (${xhr.status}).`))
    }
    xhr.send(formData)
  })
}
async function postJson(endpoint, payload) {
  return parseResponse(await fetch(apiUrl(endpoint), { method: 'POST', headers: apiHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload) }))
}

function useQueue() {
  const [data, setData] = useState({ jobs: [], summary: { active: 0, queued: 0, workers: 1 } })
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    try { setData(await parseResponse(await fetch(apiUrl('/api/jobs?limit=100'), { headers: apiHeaders() }))); setError('') } catch (e) { setError(e.message) }
  }, [])
  useEffect(() => { refresh(); const id = window.setInterval(refresh, 1000); return () => window.clearInterval(id) }, [refresh])
  return { ...data, error, refresh }
}

async function saveAs(job) {
  const getDownloadUrl = async () => {
    if (!getApiKey()) return apiUrl(job.downloadUrl || `/api/jobs/${job.id}/download`)
    const ticket = await parseResponse(await fetch(apiUrl(`/api/jobs/${job.id}/download-ticket`), { method: 'POST', headers: apiHeaders() }))
    return apiUrl(ticket.downloadUrl)
  }
  if (Capacitor.isNativePlatform()) {
    const [{ Filesystem, Directory }, { FileTransfer }, { Share }] = await Promise.all([
      import('@capacitor/filesystem'), import('@capacitor/file-transfer'), import('@capacitor/share'),
    ])
    const filename = `${job.id}-${job.outputName || 'download'}`
    const { uri } = await Filesystem.getUri({ directory: Directory.Cache, path: filename })
    await FileTransfer.downloadFile({ url: await getDownloadUrl(), path: uri })
    await Share.share({ title: job.outputName || 'Media Forge output', files: [uri] })
    return
  }
  if ('showSaveFilePicker' in window) {
    try {
      const handle = await window.showSaveFilePicker({ suggestedName: job.outputName || 'download' })
      const response = await fetch(await getDownloadUrl())
      if (!response.ok) throw new Error(`Download failed (${response.status}).`)
      const writable = await handle.createWritable()
      if (response.body) await response.body.pipeTo(writable)
      else { await writable.write(await response.blob()); await writable.close() }
      return
    } catch (error) {
      if (error?.name === 'AbortError') return
      console.warn('Save picker failed, using browser download fallback.', error)
    }
  }
  const a = document.createElement('a'); a.href = await getDownloadUrl(); a.download = job.outputName || ''; document.body.appendChild(a); a.click(); a.remove()
}

function SelectField({ label, value, onChange, options, help }) {
  return <label className="field"><span>{label}</span><select value={value} onChange={(e) => onChange(e.target.value)}>{options.map(o => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}</select>{help ? <small>{help}</small> : null}</label>
}
function FilePicker({ files, setFiles, accept, title, subtitle, multiple = true }) {
  const ref = useRef(null); const [drag, setDrag] = useState(false)
  const add = (list) => {
    const next = Array.from(list || [])
    if (!next.length) return
    setFiles(prev => multiple ? [...prev, ...next.filter(n => !prev.some(p => p.name === n.name && p.size === n.size && p.lastModified === n.lastModified))] : [next[0]])
  }
  return <div>
    <button type="button" className={`dropzone ${drag ? 'dragging' : ''}`} onClick={() => ref.current?.click()} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files) }}>
      <input ref={ref} hidden type="file" multiple={multiple} accept={accept} onChange={e => { add(e.target.files); e.target.value = '' }} />
      <span className="drop-icon"><Icon name="upload" size={25}/></span><strong>{title}</strong><span>{subtitle}</span>
    </button>
    {files.length > 0 && <div className="staged-list">{files.map((file, idx) => <div className="staged" key={`${file.name}-${file.lastModified}-${idx}`}><span><strong>{file.name}</strong><small>{formatBytes(file.size)}</small></span><button type="button" onClick={() => setFiles(prev => prev.filter((_, i) => i !== idx))}><Icon name="x" size={15}/></button></div>)}</div>}
  </div>
}
function BatchMessage({ batch }) {
  if (!batch.message && !batch.error) return null
  return <div className={`message ${batch.error ? 'error' : 'success'}`}><Icon name={batch.error ? 'alert' : 'check'} size={17}/><span>{batch.error || batch.message}</span></div>
}
function ToolHeader({ icon, kicker, title, description }) {
  return <div className="tool-heading"><div className="tool-title"><span className="tool-icon"><Icon name={icon} size={21}/></span><div><small>{kicker}</small><h2>{title}</h2></div></div><p>{description}</p></div>
}
function Metric({ label, value }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div> }

function VideoTool({ health, refreshQueue }) {
  const [files, setFiles] = useState([]); const [target, setTarget] = useState('1080'); const [engine, setEngine] = useState('auto'); const [profile, setProfile] = useState('fast'); const [enhancement, setEnhancement] = useState('light')
  const [batch, setBatch] = useState({ busy: false, progress: 0, message: '', error: '' })
  const hw = health?.hardware || {}; const engineOptions = (hw.engines || [{ value: 'auto', label: 'Auto · recommended' }, { value: 'cpu', label: 'CPU · x264' }]).map(e => ({ ...e, disabled: !e.available }))
  const queue = async () => {
    if (!files.length || batch.busy) return
    setBatch({ busy: true, progress: 0, message: '', error: '' }); let ok = 0; const failures = []
    for (let i = 0; i < files.length; i += 1) {
      const form = new FormData(); form.append('file', files[i]); form.append('target_height', target); form.append('profile', profile); form.append('enhancement', enhancement); form.append('engine', engine)
      try { await postForm('/api/video/enhance', form, p => setBatch(b => ({ ...b, progress: Math.round(((i + p / 100) / files.length) * 100) }))); ok += 1; refreshQueue() }
      catch (e) { failures.push(`${files[i].name}: ${e.message}`) }
    }
    setFiles([]); setBatch({ busy: false, progress: 100, message: ok ? `${ok} video${ok === 1 ? '' : 's'} added to the work queue.` : '', error: failures.join(' | ') })
  }
  return <section className="tool-panel"><ToolHeader icon="film" kicker="VIDEO ENHANCER" title="Batch enhance video up to 1080p sources" description="Queue several videos, choose 1080p/1440p/4K output, and let Auto select the fastest working hardware path."/>
    <div className="two-column"><div className="control-card"><h3>1. Source & processing</h3><FilePicker files={files} setFiles={setFiles} accept="video/*,.mkv,.mts,.m2ts,.ts" title="Add one or more videos" subtitle="Source up to 1920×1080 · max 90 minutes each"/>
      <div className="field-grid"><SelectField label="Target quality" value={target} onChange={setTarget} options={[{value:'1080',label:'1080p · Full HD'},{value:'1440',label:'1440p · QHD'},{value:'2160',label:'2160p · 4K UHD'}]}/><SelectField label="Engine" value={engine} onChange={setEngine} options={engineOptions}/><SelectField label="Speed profile" value={profile} onChange={setProfile} options={[{value:'fast',label:'Fast · default'},{value:'balanced',label:'Balanced'},{value:'quality',label:'Quality'}]}/><SelectField label="Enhancement" value={enhancement} onChange={setEnhancement} options={[{value:'light',label:'Light · fastest / clean source'},{value:'medium',label:'Medium · denoise + sharpen'},{value:'strong',label:'Strong · heavier cleanup'}]}/></div>
      <button className="primary-button" type="button" disabled={!files.length || batch.busy} onClick={queue}><Icon name="wand"/> {batch.busy ? `Uploading batch · ${batch.progress}%` : `Queue ${files.length || ''} enhancement${files.length === 1 ? '' : 's'}`}</button><BatchMessage batch={batch}/></div>
      <div className="result-card"><h3>2. Acceleration</h3><div className="metric-grid"><Metric label="Recommended" value={(hw.recommendedEngine || 'CPU').toUpperCase()}/><Metric label="NVIDIA" value={hw.nvencAvailable ? 'NVENC ready' : hw.cudaScaleAvailable ? 'CUDA scale only' : 'Unavailable'}/><Metric label="Intel QSV" value={hw.qsvAvailable ? 'Ready' : hw.qsvCompiled ? 'Compiled / no runtime' : 'Unavailable'}/><Metric label="Workers" value={String(health?.workerCount || 1)}/></div>
        {hw.nvidiaName && !hw.nvencAvailable && hw.cudaScaleAvailable ? <div className="message neutral"><Icon name="info"/><span>{hw.nvidiaName} can CUDA-scale, but H.264 encoding remains CPU-based because NVENC is unavailable.</span></div> : null}
        {hw.qsvCompiled && !hw.qsvAvailable ? <div className="message neutral"><Icon name="cpu"/><span>Quick Sync exists in FFmpeg but is not accessible to this backend. On Windows Docker Desktop, use the native Windows launcher for QSV.</span></div> : null}
      </div></div></section>
}

function PhotoTool({ refreshQueue }) {
  const [files, setFiles] = useState([]); const [scale, setScale] = useState('2'); const [strength, setStrength] = useState('natural'); const [format, setFormat] = useState('jpg'); const [batch, setBatch] = useState({ busy:false, message:'', error:'' })
  const queue = async () => { if (!files.length || batch.busy) return; setBatch({busy:true,message:'',error:''}); let ok=0; const bad=[]; for (const file of files) { const form=new FormData(); form.append('file',file); form.append('scale',scale); form.append('strength',strength); form.append('output_format',format); try { await postForm('/api/photo/enhance',form); ok+=1; refreshQueue() } catch(e){ bad.push(`${file.name}: ${e.message}`) } } setFiles([]); setBatch({busy:false,message:ok?`${ok} photo job${ok===1?'':'s'} queued.`:'',error:bad.join(' | ')}) }
  return <section className="tool-panel"><ToolHeader icon="image" kicker="PHOTO ENHANCER" title="Enhance several photos in one pass" description="Each selected image becomes its own queue item, so you can keep adding work while earlier photos process."/><div className="two-column"><div className="control-card"><h3>1. Photos</h3><FilePicker files={files} setFiles={setFiles} accept="image/*,.avif,.tif,.tiff" title="Add photos" subtitle="JPG, PNG, WebP, TIFF, BMP, AVIF where supported"/><div className="field-grid"><SelectField label="Upscale" value={scale} onChange={setScale} options={[{value:'1',label:'1× cleanup'},{value:'2',label:'2× upscale'},{value:'4',label:'4× upscale'}]}/><SelectField label="Strength" value={strength} onChange={setStrength} options={[{value:'natural',label:'Natural'},{value:'strong',label:'Strong'}]}/><SelectField label="Output" value={format} onChange={setFormat} options={[{value:'jpg',label:'JPG'},{value:'png',label:'PNG'},{value:'webp',label:'WebP'}]}/></div><button className="primary-button" disabled={!files.length || batch.busy} onClick={queue}><Icon name="sparkles"/> Queue {files.length || ''} photo job{files.length===1?'':'s'}</button><BatchMessage batch={batch}/></div><div className="result-card"><h3>2. Queue behavior</h3><p className="muted">Photo jobs are independent. Pause/cancel controls are available in the global work queue; image operations pause cooperatively between processing steps.</p></div></div></section>
}

function ConvertTool({ refreshQueue }) {
  const [files,setFiles]=useState([]); const [format,setFormat]=useState('pdf'); const [batch,setBatch]=useState({busy:false,message:'',error:''})
  const queue=async()=>{ if(!files.length||batch.busy)return; setBatch({busy:true,message:'',error:''}); const form=new FormData(); files.forEach(f=>form.append('files',f)); form.append('output_format',format); try{await postForm('/api/images/convert',form); setFiles([]); setBatch({busy:false,message:'Conversion job added to the queue.',error:''}); refreshQueue()}catch(e){setBatch({busy:false,message:'',error:e.message})}}
  return <section className="tool-panel"><ToolHeader icon="files" kicker="IMAGE / DOCUMENT CONVERTER" title="Convert images or merge them into PDF / Word" description="Multiple images can become one PDF/DOCX, or be converted into image formats and returned as a ZIP."/><div className="two-column"><div className="control-card"><h3>1. Images</h3><FilePicker files={files} setFiles={setFiles} accept="image/*,.avif,.tif,.tiff" title="Add images" subtitle="Up to 100 files per conversion job"/><SelectField label="Output format" value={format} onChange={setFormat} options={[{value:'pdf',label:'PDF · merge pages'},{value:'docx',label:'Word DOCX · merge pages'},{value:'jpg',label:'JPG'},{value:'png',label:'PNG'},{value:'webp',label:'WebP'},{value:'bmp',label:'BMP'},{value:'tiff',label:'TIFF'}]}/><button className="primary-button" disabled={!files.length||batch.busy} onClick={queue}><Icon name="files"/> Queue conversion</button><BatchMessage batch={batch}/></div><div className="result-card"><h3>2. Current selection</h3><div className="metric-grid"><Metric label="Files" value={String(files.length)}/><Metric label="Output" value={format.toUpperCase()}/></div><p className="muted">After a job is accepted you can immediately submit another conversion while it waits in the shared queue.</p></div></div></section>
}

function YouTubeTool({ refreshQueue }) {
  const [url,setUrl]=useState(''); const [info,setInfo]=useState(null); const [inspecting,setInspecting]=useState(false); const [outputType,setOutputType]=useState('mp4'); const [quality,setQuality]=useState('best'); const [audioQuality,setAudioQuality]=useState('192'); const [title,setTitle]=useState(''); const [album,setAlbum]=useState(''); const [message,setMessage]=useState(''); const [error,setError]=useState('')
  const inspect=async()=>{if(!url.trim()||inspecting)return; setInspecting(true);setError('');setInfo(null);try{const data=await postJson('/api/youtube/inspect',{url:url.trim()});setInfo(data);setQuality(data.qualities?.[0]?.value||'best');setTitle(data.title||'');setAlbum(data.album||'')}catch(e){setError(e.message)}finally{setInspecting(false)}}
  const queue=async()=>{if(!info)return;setError('');setMessage('');try{await postJson('/api/youtube/download',{url:url.trim(),outputType,quality,audioQuality,title:title||null,album:album||null});setMessage(`${outputType.toUpperCase()} download added to the queue.`);refreshQueue()}catch(e){setError(e.message)}}
  return <section className="tool-panel"><ToolHeader icon="youtube" kicker="YOUTUBE" title="Queue MP4 video or MP3 audio" description="Inspect source qualities, choose MP4 resolution or MP3 bitrate, and optionally edit the MP3 title and album tags."/><div className="two-column"><div className="control-card"><h3>1. YouTube media</h3><label className="field"><span>Video URL</span><input type="url" value={url} onChange={e=>{setUrl(e.target.value);setInfo(null);setError('')}} placeholder="https://www.youtube.com/watch?v=..."/></label><button className="secondary-button solid" disabled={!url.trim()||inspecting} onClick={inspect}><Icon name="youtube"/> {inspecting?'Checking…':'Check video'}</button>{info&&<div className="youtube-preview">{info.thumbnail&&<img src={info.thumbnail} alt="Video thumbnail"/>}<div><strong>{info.title}</strong><span>{info.channel||'YouTube'} {info.durationSeconds?`· ${formatDuration(info.durationSeconds)}`:''}</span></div></div>}
    {info&&<><SelectField label="Output type" value={outputType} onChange={setOutputType} options={[{value:'mp4',label:'MP4 · video + sound'},{value:'mp3',label:'MP3 · audio only'}]}/>{outputType==='mp4'?<SelectField label="Video quality" value={quality} onChange={setQuality} options={info.qualities||[{value:'best',label:'Best available'}]}/>:<><SelectField label="MP3 quality" value={audioQuality} onChange={setAudioQuality} options={[{value:'128',label:'128 kbps'},{value:'192',label:'192 kbps'},{value:'256',label:'256 kbps'},{value:'320',label:'320 kbps'}]}/><label className="field"><span>Title tag</span><input value={title} onChange={e=>setTitle(e.target.value)}/></label><label className="field"><span>Album tag</span><input value={album} onChange={e=>setAlbum(e.target.value)}/></label></>}<button className="primary-button" onClick={queue}><Icon name={outputType==='mp3'?'music':'download'}/> Add {outputType.toUpperCase()} to queue</button></>}{message&&<div className="message success"><Icon name="check"/><span>{message}</span></div>}{error&&<div className="message error"><Icon name="alert"/><span>{error}</span></div>}</div><div className="result-card"><h3>2. Fast download path</h3><div className="metric-grid"><Metric label="Fragments" value="Concurrent"/><Metric label="HTTP" value="aria2 when available"/><Metric label="Merge" value="FFmpeg"/><Metric label="Audio" value="128–320 kbps"/></div></div></div></section>
}

function LinkTool({ refreshQueue }) {
  const [text,setText]=useState(''); const [batch,setBatch]=useState({busy:false,message:'',error:''}); const urls=useMemo(()=>text.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),[text])
  const queue=async()=>{if(!urls.length||batch.busy)return;setBatch({busy:true,message:'',error:''});let ok=0;const bad=[];for(const url of urls){try{await postJson('/api/remote/download',{url});ok+=1;refreshQueue()}catch(e){bad.push(`${url}: ${e.message}`)}}if(ok===urls.length)setText('');setBatch({busy:false,message:ok?`${ok} link${ok===1?'':'s'} queued.`:'',error:bad.join(' | ')})}
  return <section className="tool-panel"><ToolHeader icon="link" kicker="INTERNET MEDIA LINK" title="Resolve public video and image links" description="Paste one or several public URLs. Media Forge tries direct media, supported site extraction, then HTML video/image discovery."/><div className="two-column"><div className="control-card"><h3>1. URLs</h3><label className="field"><span>One URL per line</span><textarea rows="8" value={text} onChange={e=>setText(e.target.value)} placeholder={'https://example.com/video.mp4\nhttps://example.com/page-with-photo'}/></label><button className="primary-button" disabled={!urls.length||batch.busy} onClick={queue}><Icon name="download"/> Queue {urls.length||''} link{urls.length===1?'':'s'}</button><BatchMessage batch={batch}/></div><div className="result-card"><h3>2. Resolver order</h3><div className="resolver"><span>01</span><p><strong>Direct media</strong>Parallel HTTP ranges when the server supports them.</p><span>02</span><p><strong>Site extractor</strong>yt-dlp handles supported public media pages and stream manifests.</p><span>03</span><p><strong>HTML discovery</strong>OpenGraph, video/source tags, images, lazy-src and srcset.</p></div></div></div></section>
}

function QueuePanel({ queue }) {
  const [busy,setBusy]=useState(''); const [error,setError]=useState('')
  const action=async(job,op)=>{setBusy(`${job.id}:${op}`);setError('');try{if(op==='save')await saveAs(job);else if(op==='delete'){await fetch(apiUrl(`/api/jobs/${job.id}`),{method:'DELETE',headers:apiHeaders()}).then(r=>{if(!r.ok)return parseResponse(r);return null})}else await parseResponse(await fetch(apiUrl(`/api/jobs/${job.id}/${op}`),{method:'POST',headers:apiHeaders()}));await queue.refresh()}catch(e){setError(e.message)}finally{setBusy('')}}
  const jobs=queue.jobs
  return <section className="queue-panel"><div className="queue-heading"><div><span className="eyebrow small"><Icon name="queue" size={14}/> WORK QUEUE</span><h2>Queued and completed work</h2></div><div className="queue-summary"><span>Active <strong>{queue.summary.active}</strong></span><span>Queued <strong>{queue.summary.queued}</strong></span><span>Workers <strong>{queue.summary.workers}</strong></span></div></div>{error&&<div className="message error"><Icon name="alert"/><span>{error}</span></div>}{queue.error&&<div className="message error"><Icon name="alert"/><span>{queue.error}</span></div>}
    {!jobs.length?<div className="empty-queue">No jobs yet. Add work from any tool above.</div>:<div className="job-list">{jobs.map(job=><QueueRow key={job.id} job={job} busy={busy} action={action}/>)}</div>}</section>
}
function QueueRow({job,busy,action}) {
  const d=job.details||{}; const locked=busy.startsWith(job.id); const status=job.status
  return <article className={`job-row status-${status}`}><div className="job-main"><div className="job-top"><span className="job-name" title={job.originalName}>{job.originalName}</span><span className={`status-pill ${status}`}>{status}{job.queuePosition?` #${job.queuePosition}`:''}</span></div><div className="job-meta"><span>{job.operation}</span>{job.width&&<span>{job.width}×{job.height}</span>}{d.targetHeight&&<span>→ {d.targetHeight}p</span>}{d.engineActual&&<span>{d.engineActual}</span>}{d.fps&&<span>{d.fps} FPS</span>}{d.realtime&&<span>{d.realtime}× realtime</span>}{d.downloadSpeed&&<span>{d.downloadSpeed}</span>}{d.etaSeconds!==undefined&&d.etaSeconds!==null&&<span>ETA {formatDuration(d.etaSeconds)}</span>}</div><div className="queue-progress"><span style={{width:`${status==='completed'?100:job.progress||0}%`}}/></div><div className="job-meta"><span>{Math.round(job.progress||0)}%</span>{job.inputSizeBytes&&<span>{formatBytes(job.inputSizeBytes)} input</span>}{job.outputSizeBytes&&<span>{formatBytes(job.outputSizeBytes)} output</span>}{job.error&&<span className="error-text">{job.error}</span>}</div></div><div className="job-actions">
    {status==='queued'&&<><button disabled={locked} onClick={()=>action(job,'pause')}><Icon name="pause"/> Pause</button><button className="danger" disabled={locked} onClick={()=>action(job,'cancel')}><Icon name="x"/> Cancel</button></>}
    {status==='processing'&&<><button disabled={locked} onClick={()=>action(job,'pause')}><Icon name="pause"/> Pause</button><button disabled={locked} onClick={()=>action(job,'stop')}><Icon name="stop"/> Stop</button><button className="danger" disabled={locked} onClick={()=>action(job,'cancel')}><Icon name="x"/> Cancel</button></>}
    {status==='paused'&&<><button disabled={locked} onClick={()=>action(job,'resume')}><Icon name="play"/> Resume</button><button disabled={locked} onClick={()=>action(job,'stop')}><Icon name="stop"/> Stop</button><button className="danger" disabled={locked} onClick={()=>action(job,'cancel')}><Icon name="x"/> Cancel</button></>}
    {status==='stopped'&&<><button disabled={locked} onClick={()=>action(job,'start')}><Icon name="play"/> Start</button><button className="danger" disabled={locked} onClick={()=>action(job,'cancel')}><Icon name="x"/> Cancel</button></>}
    {status==='failed'&&<><button disabled={locked} onClick={()=>action(job,'start')}><Icon name="play"/> Retry</button><button disabled={locked} onClick={()=>action(job,'delete')}><Icon name="trash"/> Delete</button></>}
    {status==='completed'&&<><button className="save" disabled={locked} onClick={()=>action(job,'save')}><Icon name="download"/> Save As</button><button disabled={locked} onClick={()=>action(job,'delete')}><Icon name="trash"/> Delete</button></>}
    {status==='cancelled'&&<button disabled={locked} onClick={()=>action(job,'delete')}><Icon name="trash"/> Delete</button>}
    {status==='stopping'&&<span className="muted">Stopping…</span>}
  </div></article>
}

function App() {
  const [active,setActive]=useState('video'); const [health,setHealth]=useState(null); const [healthError,setHealthError]=useState(''); const [backendDraft,setBackendDraft]=useState(getApiBaseUrl); const [keyDraft,setKeyDraft]=useState(getApiKey); const [connectionRevision,setConnectionRevision]=useState(0); const [connectionError,setConnectionError]=useState(''); const queue=useQueue()
  useEffect(()=>{let dead=false;setHealth(null);setHealthError('');fetch(apiUrl('/api/health'),{headers:apiHeaders()}).then(parseResponse).then(d=>{if(!dead)setHealth(d)}).catch(e=>{if(!dead)setHealthError(e.message)});queue.refresh();return()=>{dead=true}},[connectionRevision])
  const saveConnection=(event)=>{event.preventDefault();try{const normalized=saveApiBaseUrl(backendDraft);saveApiKey(keyDraft);setBackendDraft(normalized);setConnectionRevision(value=>value+1);setConnectionError('')}catch(error){setConnectionError(error.message)}}
  return <main className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><Icon name="wand"/></span><span>MEDIA <strong>FORGE</strong></span></div><div className={`health-pill ${health?'online':'offline'}`}><span className="health-dot"/>{health?`Backend ${health.version}`:healthError||'Checking backend…'}</div></header>
    <form className="connection-bar" onSubmit={saveConnection}><label htmlFor="backend-url"><strong>Backend connection</strong><span>{getApiBaseUrl() || 'Same origin (local setup)'}</span></label><input id="backend-url" type="url" value={backendDraft} onChange={event=>setBackendDraft(event.target.value)} placeholder="https://your-backend.example.com" aria-describedby="backend-help"/><input type="password" value={keyDraft} onChange={event=>setKeyDraft(event.target.value)} placeholder="API key (if configured)" aria-label="Backend API key" autoComplete="off"/><button type="submit">Connect</button><small id="backend-help">Use a persistent HTTPS FastAPI server for web and Android. Leave the URL blank for local Vite or Docker.</small>{connectionError&&<span className="connection-error" role="alert">{connectionError}</span>}</form>
    <section className="hero"><div className="eyebrow"><Icon name="sparkles" size={14}/> MEDIA TOOLKIT · HARDWARE-AWARE QUEUE</div><h1>Enhance, convert<br/><span>and download media.</span></h1><p>Batch media processing with pause/resume/stop/cancel, CPU/NVIDIA/Intel QSV selection, faster downloads and Save As.</p></section>
    <nav className="tool-nav">{TOOLS.map(t=><button key={t.id} className={active===t.id?'active':''} onClick={()=>setActive(t.id)}><Icon name={t.icon} size={20}/><span><strong>{t.label}</strong><small>{t.caption}</small></span></button>)}</nav>
    <div className="tool-stack">{active==='video'&&<VideoTool health={health} refreshQueue={queue.refresh}/>} {active==='photo'&&<PhotoTool refreshQueue={queue.refresh}/>} {active==='convert'&&<ConvertTool refreshQueue={queue.refresh}/>} {active==='youtube'&&<YouTubeTool refreshQueue={queue.refresh}/>} {active==='link'&&<LinkTool refreshQueue={queue.refresh}/>}</div>
    <QueuePanel queue={queue}/>
    <section className="capability-strip"><div><span>01</span><strong>Batch queue</strong><small>Add more jobs while other work is running.</small></div><div><span>02</span><strong>Hardware aware</strong><small>NVENC, CUDA scale, Intel QSV or x264 fallback.</small></div><div><span>03</span><strong>Real controls</strong><small>Pause/resume processes; stop and restart; cancel permanently.</small></div><div><span>04</span><strong>Save As</strong><small>Native browser file picker when supported.</small></div></section>
    <footer><span>MEDIA FORGE 3.2</span><p>Public media resolvers do not bypass authentication, DRM, paywalls or private-network protections.</p></footer></main>
}
export default App
