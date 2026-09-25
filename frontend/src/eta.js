export function parseDownloadEta(value) {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value
  if (typeof value !== 'string') return null
  const input = value.trim()
  if (/^\d+s$/.test(input)) return Number(input.slice(0, -1))
  if (!/^\d+(?::\d{2}){1,2}$/.test(input)) return null
  return input.split(':').reduce((total, part) => total * 60 + Number(part), 0)
}

export function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'Calculating time left…'
  const rounded = Math.ceil(seconds)
  if (rounded < 60) return `About ${rounded} second${rounded === 1 ? '' : 's'} left`
  const minutes = Math.ceil(rounded / 60)
  if (minutes < 60) return `About ${minutes} minute${minutes === 1 ? '' : 's'} left`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `About ${hours}h ${rest}m left`
}

export function updateProgressSample(previous, progress, now) {
  if (!previous || progress < previous.progress) return { progress, time: now, rate: null }
  const elapsed = (now - previous.time) / 1000
  const gain = progress - previous.progress
  if (elapsed < 1 || gain < 0.25) return previous
  const measured = gain / elapsed
  return { progress, time: now, rate: previous.rate ? previous.rate * 0.65 + measured * 0.35 : measured }
}
