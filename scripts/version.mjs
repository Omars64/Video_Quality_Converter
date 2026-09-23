import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const write = (file, content) => fs.writeFileSync(path.join(root, file), content)
const pkg = JSON.parse(read('frontend/package.json'))
const lock = JSON.parse(read('frontend/package-lock.json'))
const gradle = read('frontend/android/app/build.gradle')
const arg = process.argv[2]
let parts = pkg.version.split('.').map(Number)
if (arg === '--check') {
  const code = parts[0] * 10000 + parts[1] * 100 + parts[2]
  if (lock.version !== pkg.version || lock.packages[''].version !== pkg.version || !gradle.includes(`versionName "${pkg.version}"`) || !gradle.includes(`versionCode ${code}`) || !read('backend/app/version.py').includes(`"${pkg.version}"`)) throw new Error('Versions are not synchronized')
  console.log(`Versions match: ${pkg.version}`)
} else {
  const index = ['major', 'minor', 'patch'].indexOf(arg)
  if (index < 0) throw new Error('Usage: node scripts/version.mjs major|minor|patch|--check')
  parts[index]++; parts = parts.map((n, i) => i > index ? 0 : n)
  if (parts[1] > 99 || parts[2] > 99) throw new Error('Android version encoding supports minor/patch up to 99')
  pkg.version = parts.join('.')
  lock.version = lock.packages[''].version = pkg.version
  write('frontend/package.json', JSON.stringify(pkg, null, 2) + '\n')
  write('frontend/package-lock.json', JSON.stringify(lock, null, 2) + '\n')
  write('backend/app/version.py', `VERSION = "${pkg.version}"\n`)
  write('frontend/android/app/build.gradle', gradle.replace(/versionCode \d+/, `versionCode ${parts[0]*10000+parts[1]*100+parts[2]}`).replace(/versionName "[^"]+"/, `versionName "${pkg.version}"`))
  console.log(`Updated to ${pkg.version}`)
}
