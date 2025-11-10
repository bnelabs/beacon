#!/usr/bin/env node

import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const run = (command) => {
  execSync(command, { stdio: 'inherit', env: process.env })
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
  ensureHostDependencies()
  ensureBrowser()
} catch (error) {
  console.error('\nFailed to prepare Playwright:', error?.message ?? error)
  process.exitCode = error?.status ?? 1
}
