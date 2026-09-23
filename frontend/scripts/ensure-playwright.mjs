#!/usr/bin/env node

import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const run = (command) => {
  execSync(command, { stdio: 'inherit', env: process.env })
}

// Guard: the frontend e2e suite must run on the same Node engine as CI
// (see "engines.node" in package.json and frontend/.nvmrc). A mismatched
// local engine produces results that cannot be honestly compared to CI, so
// fail fast with an actionable message instead of a misleading red. The
// required major version is read from package.json (single source of truth).
const requiredNodeMajor = (() => {
  try {
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
    const match = String(pkg?.engines?.node ?? '').match(/(\d+)/)
    return match ? Number(match[1]) : null
  } catch {
    return null
  }
})()

const guardNodeVersion = () => {
  if (requiredNodeMajor === null) return
  const nodeMajor = Number(process.versions.node.split('.')[0])
  if (Number.isFinite(nodeMajor) && nodeMajor < requiredNodeMajor) {
    console.error(
      `\n✖ The frontend e2e suite requires Node >= ${requiredNodeMajor} ` +
        `(package.json "engines", frontend/.nvmrc), but this is Node ${process.versions.node}.\n` +
        `  Install Node ${requiredNodeMajor} (e.g. "nvm use") and re-run.\n`
    )
    process.exit(1)
  }
}

const ensureBrowser = () => {
  run('npx playwright install chromium')
}

const ensureHostDependencies = () => {
  if (process.platform !== 'linux') return

  const getUid = typeof process.getuid === 'function' ? process.getuid : null
  const isRoot = getUid ? getUid() === 0 : false

  if (!isRoot) {
    console.warn(
      '\n⚠️  Playwright system dependencies could not be installed automatically. ' +
        'If the browser fails to launch, run `npx playwright install-deps chromium` with elevated privileges.\n'
    )
    return
  }

  const cacheFile = join(process.cwd(), 'node_modules', '.cache', 'playwright-deps-installed')
  if (existsSync(cacheFile)) {
    return
  }

  run('npx playwright install-deps chromium')

  mkdirSync(dirname(cacheFile), { recursive: true })
  writeFileSync(cacheFile, '')
}

try {
  guardNodeVersion()
  ensureHostDependencies()
  ensureBrowser()
} catch (error) {
  console.error('\nFailed to prepare Playwright:', error?.message ?? error)
  process.exitCode = error?.status ?? 1
}
