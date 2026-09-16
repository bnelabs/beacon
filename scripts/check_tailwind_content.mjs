#!/usr/bin/env node
/**
 * Fail when Tailwind's `content` globs stop matching real source files.
 *
 * why: a Tailwind glob that matches nothing does not fail anything. The build
 * succeeds, the dev server starts, and the emitted stylesheet simply lacks
 * every utility class -- the app renders as unstyled HTML with collapsed
 * layout. That is exactly what happened when the TypeScript migration renamed
 * every `src/**\/*.jsx` to `.tsx` while `tailwind.config.js` still said
 * `{js,jsx}`: main shipped an empty-ish 5.9 kB sheet, and only the (then
 * nightly-only) Playwright suite could see it, two tiers away from the change
 * that caused it. The failure mode is silent by construction, so the check
 * has to be loud by construction: this script resolves the configured globs
 * against the real tree and exits non-zero, naming the glob, when a
 * src-targeting pattern matches zero files.
 *
 * It deliberately needs no dependencies (no glob library): the patterns used
 * by this repo are `./dir/**\/*.{ext,ext}` shapes, and the check only needs
 * "does any file under the glob's directory carry one of the glob's
 * extensions", which a recursive walk and an extension set answer exactly.
 * If the config ever grows a pattern this parser cannot understand, it says
 * so and fails rather than guessing.
 *
 * Runs in frontend-ci.yml (the sub-minute gate) next to the e2e mock-coverage
 * audit; both are static, dependency-free checks that name a silent failure.
 */
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { dirname, join, resolve, extname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = join(ROOT, 'frontend')
const CONFIG_PATH = join(FRONTEND, 'tailwind.config.js')

function fail(message) {
  console.error(`\ntailwind content check FAILED: ${message}\n`)
  process.exit(1)
}

if (!existsSync(CONFIG_PATH)) {
  fail(`${CONFIG_PATH} does not exist`)
}

const config = (await import(pathToFileURL(CONFIG_PATH).href)).default
const patterns = config?.content
if (!Array.isArray(patterns) || patterns.length === 0) {
  fail('tailwind.config.js has no `content` array')
}

/** Parse a recursive-extension glob (`dir` + star-star + `*.{a,b}` or
 *  `*.a`) into { dir, extensions }; null when the shape is not recognised. */
function parsePattern(pattern) {
  const match = /^(.*?)\*\*\/\*\.(?:\{([^}]+)\}|(\w+))$/.exec(pattern)
  if (!match) return null
  const [, dirPart, braceList, singleExt] = match
  const extensions = (braceList ? braceList.split(',') : [singleExt])
    .map((ext) => ext.trim().replace(/^\./, ''))
    .filter(Boolean)
    .map((ext) => `.${ext}`)
  return { dir: dirPart.replace(/\/$/, ''), extensions }
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      walk(full, out)
    } else {
      out.push(full)
    }
  }
  return out
}

let checkedSrcPatterns = 0
for (const rawPattern of patterns) {
  const pattern = String(rawPattern)
  const parsed = parsePattern(pattern)
  if (!parsed) {
    if (pattern.includes('**')) {
      fail(
        `cannot understand content glob ${JSON.stringify(pattern)}; ` +
        'extend parsePattern() in scripts/check_tailwind_content.mjs rather than weakening the check'
      )
    }
    // A literal file path (e.g. ./index.html): it must exist.
    const literal = resolve(FRONTEND, pattern.replace(/^\.\//, ''))
    if (!existsSync(literal)) {
      fail(`content entry ${JSON.stringify(pattern)} does not exist on disk`)
    }
    continue
  }

  const dir = resolve(FRONTEND, parsed.dir.replace(/^\.\//, ''))
  if (!existsSync(dir)) {
    fail(`content glob ${JSON.stringify(pattern)} points at missing directory ${dir}`)
  }
  if (!dir.startsWith(join(FRONTEND, 'src'))) {
    continue // only src-targeting globs can silently empty the sheet
  }
  checkedSrcPatterns += 1

  const files = walk(dir)
  const matching = files.filter((file) => parsed.extensions.includes(extname(file)))
  if (matching.length === 0) {
    fail(
      `content glob ${JSON.stringify(pattern)} matches ZERO files under ${dir} ` +
      `(${files.length} files exist there; extensions present: ` +
      `${[...new Set(files.map((f) => extname(f)))].sort().join(', ') || 'none'}). ` +
      'Tailwind would emit no utilities for the app and NOTHING else would fail -- ' +
      'that is the silent-empty-stylesheet bug this script exists to name.'
    )
  }
  console.log(
    `tailwind content: ${pattern} -> ${matching.length} file(s) under ${parsed.dir || '.'}`
  )
}

if (checkedSrcPatterns === 0) {
  fail('no content glob targets frontend/src -- the app stylesheet would be empty')
}
console.log('tailwind content check: OK')
