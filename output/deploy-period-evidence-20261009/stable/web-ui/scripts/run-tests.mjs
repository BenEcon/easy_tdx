/** All frontend logic suites; no shell globs, works on Windows as well as POSIX. */
import { readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const cwd = fileURLToPath(new URL('.', import.meta.url))
const files = readdirSync(cwd).filter(name => name.endsWith('.test.mjs')).sort()
if (!files.length) throw new Error('No frontend regression suites found')
const root = fileURLToPath(new URL('..', import.meta.url))
for (const args of [
  ['--experimental-strip-types', '--test', ...files.map(file => `scripts/${file}`)],
  ['scripts/run-grading-tests.mjs'],
]) {
  const result = spawnSync(process.execPath, args, { cwd: root, stdio: 'inherit' })
  if (result.error) console.error(result.error)
  if (result.status !== 0) process.exit(result.status ?? 1)
}
