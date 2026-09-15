/**
 * Recapture the README screens: docs/images/{dashboard,risk-map,models,results}.png
 *
 * why: the previous captures were taken against a stubbed basemap, so the
 * risk-map screenshot showed a blank paper rectangle where the map should be,
 * and a reviewer called the set unprofessional. These are captured from the
 * shipped UI against the e2e mocks (frontend/tests/apiMocks.js) so no screen
 * ever shows invented data. The basemap needs no mock and no network: it is
 * the bundled Natural Earth layer. The one deliberate real-network exception
 * is the Google Fonts stylesheet, because a screenshot without its typography
 * is not a screenshot of the shipped UI; no assertion depends on it.
 *
 * usage: node frontend/scripts/capture-docs-screens.mjs
 * Requires a reachable dev server; the script starts one if port 8173 is free.
 */
import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createConnection } from 'node:net'
import { chromium } from '@playwright/test'
import { registerApiMocks } from '../tests/apiMocks.js'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url))) // frontend/
const OUT = join(ROOT, '..', 'docs', 'images')
const URL = 'http://127.0.0.1:8173'

function portOpen(port) {
  return new Promise((resolve) => {
    const socket = createConnection({ port, host: '127.0.0.1' })
    socket.once('connect', () => { socket.destroy(); resolve(true) })
    socket.once('error', () => resolve(false))
  })
}

let devServer = null
if (!(await portOpen(8173))) {
  devServer = spawn('npm', ['run', 'dev'], { cwd: ROOT, stdio: 'ignore', detached: true })
  for (let i = 0; i < 60 && !(await portOpen(8173)); i++) await sleep(500)
  if (!(await portOpen(8173))) throw new Error('dev server did not come up on 8173')
}

const browser = await chromium.launch({
  args: [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--use-gl=angle',
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader'
  ]
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', (message) => {
  if (message.type() === 'error') console.log('[console.error]', message.text())
})

await registerApiMocks(page)
// One deliberate real-network exception: the Google Fonts stylesheet, because
// a screenshot without its typography is not a screenshot of the shipped UI.
// The basemap needs no exception any more -- it is bundled.
await page.unroute(/fonts\.(googleapis|gstatic)\.com/)

const shot = async (name) => {
  await page.waitForTimeout(1200)
  await page.screenshot({ path: join(OUT, `${name}.png`) })
  console.log('captured', name)
}

await page.goto(URL)
await page.getByRole('heading', { name: 'Dashboard' }).waitFor()
await page.waitForLoadState('networkidle').catch(() => {})
await shot('dashboard')

await page.getByRole('button', { name: 'Risk Map', exact: true }).click()
await page.getByTestId('risk-map').locator('canvas').waitFor()
await page.waitForLoadState('networkidle').catch(() => {})
await sleep(2500) // let the tile pyramid fill in
await shot('risk-map')

await page.getByRole('button', { name: 'Models' }).click()
await page.getByRole('heading', { name: 'Models' }).waitFor()
await shot('models')

// Results needs a selected model AND a run scenario; the only path there is the
// details drawer, and launching without a scenario renders an error card and an
// "undefined" title -- which is what an earlier capture set shipped.
await page.getByRole('button', { name: 'View Details' }).first().click()
const builder = page
  .locator('section')
  .filter({ has: page.getByRole('heading', { name: 'Scenario Builder' }) })
  .first()
// The mocked simulate endpoint names every scenario 'Custom Scenario', so
// typing that keeps the input, the result card and the Results title agreed.
await builder.getByPlaceholder('e.g., Volatility +20%').fill('Custom Scenario')
// runScenario refuses a scenario with no adjustments ("Adjust at least one
// data source"), so move a slider before running, exactly as the e2e spec does.
const slider = builder.locator('input[type="range"]').first()
await slider.focus()
for (let step = 0; step < 5; step += 1) await slider.press('ArrowRight')
await builder.getByRole('button', { name: 'Run Scenario' }).first().click()
await page.getByText('Avg risk score').first().waitFor()
await page.getByRole('button', { name: 'Launch Explainability' }).click()
await page.getByRole('button', { name: 'Run Scenario' }).waitFor({ timeout: 20000 })
await shot('results')

await browser.close()
if (devServer) {
  try { process.kill(-devServer.pid, 'SIGKILL') } catch { /* already gone */ }
}
