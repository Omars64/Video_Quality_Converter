import React, { useEffect, useState } from 'react'
import { version } from '../package.json'
import { clearSession, getApiBaseUrl, getSession, request, saveApiBaseUrl, saveSession } from './api.js'
import { applyTheme, DEFAULT_THEME, loadTheme } from './theme.js'
import { Field, Notice, UploadTool, YouTubeTool, LinkTool } from './Tools.jsx'
import { Queue, useQueue } from './Queue.jsx'

const TOOLS = [
  ['video', 'Video quality', 'Improve clarity and choose your output resolution.'],
  ['photo', 'Enhance photos', 'Clean up, sharpen, and upscale your photos.'],
  ['convert', 'Convert files', 'Convert images and documents into the format you need.'],
  ['youtube', 'YouTube', 'Save a video as MP4 or its audio as MP3.'],
  ['link', 'Download a link', 'Save photos and videos from public websites and social posts.'],
]
function Footer() { return <footer>MEDIA FORGE <span>{version}</span></footer> }

function SignIn({ onSignIn }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async e => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      const result = await request('/api/auth/login', { method: 'POST', body: { password } })
      saveSession(result.token); setPassword(''); onSignIn()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="login-shell"><main className="login-card">
    <div className="brand-mark" aria-hidden="true">M</div><h1>Media Forge</h1><p>Enter your password to continue.</p>
    <form onSubmit={submit}><Field label="Password"><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" autoFocus required maxLength={1024}/></Field>
      <button className="primary" disabled={!password || busy}>{busy ? 'Signing in…' : 'Open Media Forge'}</button><Notice error>{error}</Notice>
    </form></main><Footer/></div>
}

function Settings({ theme, setTheme }) {
  const [server, setServer] = useState(getApiBaseUrl)
  const [error, setError] = useState('')
  const [draftTheme, setDraftTheme] = useState(theme)
  const [appearanceOpen, setAppearanceOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const connect = e => {
    e.preventDefault()
    try { saveApiBaseUrl(server) } catch (e) { setError(e.message) }
  }
  return <details className="settings" open={settingsOpen} onToggle={e => setSettingsOpen(e.currentTarget.open)}><summary>Settings</summary><div className="settings-panel">
    <h2>Settings</h2>
    <details className="setting-group" open={appearanceOpen} onToggle={e => { setAppearanceOpen(e.currentTarget.open); if (e.currentTarget.open) setDraftTheme(theme) }}><summary>Appearance</summary><div className="settings-content">
      <Field label="Accent color"><input type="color" value={draftTheme.accent} onInput={e => setDraftTheme(t => ({ ...t, accent: e.currentTarget.value }))}/></Field>
      <Field label="Background color"><input type="color" value={draftTheme.background} onInput={e => setDraftTheme(t => ({ ...t, background: e.currentTarget.value }))}/></Field>
      <div className="settings-actions"><button type="button" onClick={() => setDraftTheme(DEFAULT_THEME)}>Reset colors</button><button type="button" className="primary" onClick={() => { document.activeElement?.blur(); setTheme(draftTheme); setAppearanceOpen(false); setSettingsOpen(false) }}>Confirm</button></div>
    </div></details>
    <details className="setting-group"><summary>Advanced connection</summary><form className="settings-content" onSubmit={connect}>
      <p>The app connects automatically. Change this only to use your own server.</p>
      <Field label="Custom server URL" hint="Leave blank to use the built-in connection."><input type="url" placeholder="https://your-server.example.com" value={server} onChange={e => setServer(e.target.value)}/></Field>
      <button type="submit">Save and sign in again</button><Notice error>{error}</Notice>
    </form></details>
  </div></details>
}

function Workspace({ theme, setTheme }) {
  const [active, setActive] = useState('video')
  const queue = useQueue()
  const tool = TOOLS.find(item => item[0] === active)
  return <div className="app-shell"><header className="topbar"><a className="brand" href="#" aria-label="Media Forge home">MEDIA <strong>FORGE</strong></a><div className="header-actions"><Settings theme={theme} setTheme={setTheme}/><button type="button" onClick={clearSession}>Sign out</button></div></header>
    <main><div className="intro"><h1>Your media, made better.</h1><p>Choose a tool. Add your files or a link. Save the result.</p></div>
      <nav className="tool-nav" aria-label="Media tools">{TOOLS.map(([id, label]) => <button key={id} aria-pressed={active === id} onClick={() => setActive(id)}>{label}</button>)}</nav>
      <section className="tool-panel" aria-labelledby="tool-title"><h2 id="tool-title">{tool[1]}</h2><p className="tool-description">{tool[2]}</p>
        {['video', 'photo', 'convert'].includes(active) ? <UploadTool key={active} type={active} refresh={queue.refresh}/> : active === 'youtube' ? <YouTubeTool refresh={queue.refresh}/> : <LinkTool refresh={queue.refresh}/>}
      </section><Queue queue={queue}/>
    </main><Footer/></div>
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [checking, setChecking] = useState(Boolean(getSession()))
  const [theme, setTheme] = useState(loadTheme)
  useEffect(() => applyTheme(theme), [theme])
  useEffect(() => {
    let alive = true
    const signout = () => { setAuthenticated(false); setChecking(false) }
    window.addEventListener('media-forge:signout', signout)
    if (getSession()) request('/api/auth/session').then(() => { if (alive) setAuthenticated(true) }).catch(() => { if (alive) clearSession() }).finally(() => { if (alive) setChecking(false) })
    return () => { alive = false; window.removeEventListener('media-forge:signout', signout) }
  }, [])
  if (checking) return <div className="login-shell"><p role="status">Opening Media Forge…</p><Footer/></div>
  return authenticated ? <Workspace theme={theme} setTheme={setTheme}/> : <SignIn onSignIn={() => setAuthenticated(true)}/>
}
