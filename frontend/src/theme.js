export const DEFAULT_THEME = { accent: '#4df59b', background: '#0b1113' }
const valid = value => /^#[0-9a-f]{6}$/i.test(value || '')
const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
const light = hex => {
  const [r, g, b] = rgb(hex).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4 })
  return .2126 * r + .7152 * g + .0722 * b > .179
}
const mix = (a, b, ratio) => '#' + rgb(a).map((v, i) => Math.round(v * (1 - ratio) + rgb(b)[i] * ratio).toString(16).padStart(2, '0')).join('')
export function loadTheme() {
  try {
    const value = JSON.parse(localStorage.getItem('media-forge-theme'))
    return valid(value?.accent) && valid(value?.background) ? value : DEFAULT_THEME
  } catch { return DEFAULT_THEME }
}
export function applyTheme(theme) {
  const { accent, background } = theme
  if (!valid(accent) || !valid(background)) return
  const foreground = light(background) ? '#172126' : '#edf4f1'
  const properties = {
    '--accent': accent, '--background': background, '--text': foreground,
    '--on-accent': light(accent) ? '#101713' : '#ffffff',
    '--surface': mix(background, foreground, .045), '--raised': mix(background, foreground, .08),
    '--border': mix(background, foreground, .18), '--muted': mix(background, foreground, .65),
  }
  for (const [name, value] of Object.entries(properties)) document.documentElement.style.setProperty(name, value)
  document.documentElement.style.colorScheme = light(background) ? 'light' : 'dark'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', background)
  try { localStorage.setItem('media-forge-theme', JSON.stringify(theme)) } catch { /* Persistence is optional. */ }
}
