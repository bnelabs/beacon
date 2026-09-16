#!/usr/bin/env node
/**
 * Fail when a named runtime export of the frontend's data layer has no
 * consumer anywhere in src/.
 *
 * why: the TypeScript migration typed every hook — and typing made visible
 * what the untyped tree had quietly accumulated: twelve hooks with zero
 * callers (five country hooks, five notification hooks, two analytics
 * hooks), plus dead helpers in the data modules and a compat re-export
 * "so existing imports keep working" that no import used. Dead exports are
 * not harmless: they are unmaintained contracts (they drift from the API
 * with nothing exercising them), they widen the surface a reader must
 * understand, and — as the coverage audit keeps proving — an endpoint only
 * a dead hook calls still shows up in drift reports.
 *
 * This is the frontend sibling of backend/tests/test_reachability.py: same
 * doctrine (nothing ships that nothing calls), different language.
 *
 * Scope, deliberately: named *value* exports (`export function` / `export
 * const`, sync or async) of src/hooks, src/utils, src/data and src/store.
 * Type-only exports are skipped (the contract test polices those against
 * the OpenAPI schema), default exports are skipped (pages/components are
 * consumed through `import()` and JSX, which a name-grep would misjudge),
 * and components/ui are skipped for the same reason. Every symbol in scope
 * is consumed strictly by name, so "no other file mentions the name" is
 * exactly "unreachable".
 *
 * Runs in frontend-ci.yml (the sub-minute gate): a directory walk and a
 * regex per export, no dependencies, milliseconds.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'frontend', 'src')
const SCOPED_DIRS = ['hooks', 'utils', 'data', 'store']

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      walk(full, out)
    } else if (['.ts', '.tsx'].includes(extname(full)) && !full.endsWith('.d.ts')) {
      out.push(full)
    }
  }
  return out
}

const allFiles = walk(SRC)
const scopedFiles = allFiles.filter((file) =>
  SCOPED_DIRS.some((dir) => file.startsWith(join(SRC, dir)))
)

if (scopedFiles.length === 0) {
  console.error('reachability check FAILED: no scoped source files found — did src/ move?')
  process.exit(1)
}

const contents = new Map(allFiles.map((file) => [file, readFileSync(file, 'utf8')]))

/** Named runtime exports: `export (async) function x` / `export const x`.
 *  Type-only forms (`export type`, `export interface`, `export type {..}`)
 *  and `export default` are out of scope by design. */
const EXPORT_RE = /^export\s+(?:async\s+)?(?:function|const)\s+([A-Za-z0-9_$]+)/gm

const dead = []
let checked = 0
for (const file of scopedFiles) {
  const text = contents.get(file)
  for (const match of text.matchAll(EXPORT_RE)) {
    const name = match[1]
    checked += 1
    const nameRe = new RegExp(`\\b${name.replace(/\$/g, '\\$')}\\b`)
    const usedElsewhere = allFiles.some(
      (other) => other !== file && nameRe.test(contents.get(other))
    )
    if (!usedElsewhere) {
      dead.push(`${name}  (frontend/src/${file.slice(SRC.length + 1)})`)
    }
  }
}

if (dead.length > 0) {
  console.error(
    '\nfrontend reachability check FAILED: exported but referenced nowhere else in src/:\n' +
    dead.map((entry) => `  - ${entry}`).join('\n') +
    '\n\nDelete it, or wire it to the screen that needs it. A dead export is an' +
    '\nunmaintained contract: it drifts from the API with nothing exercising it.' +
    '\n(See backend/tests/test_reachability.py for the backend sibling.)\n'
  )
  process.exit(1)
}

console.log(`frontend reachability: ${checked} named export(s) in scope, all referenced. OK`)
