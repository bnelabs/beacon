import { test, expect } from '@playwright/test'
import { registerApiMocks } from './apiMocks.js'

// Restored coverage: the pre-split monolith walked Models -> Scenario Builder
// -> Launch Explainability -> Results -> predictive-validity report card. The
// three-way spec split dropped all of it -- no split spec mentioned Results --
// so the platform's headline output screen (README: "Results -- one job's
// output") had no e2e guard at all. These tests restore that walk and add the
// uncertainty rendering contract shipped with the deep-ensemble wiring: a
// refused prediction is absence on screen (dashes + reason), never a number.

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('error', (event) => {
      const message = event?.error?.message || event.message || 'Unknown window error'
      console.error('window-error:', message)
    })

    window.addEventListener('unhandledrejection', (event) => {
      const reason = event?.reason
      const message =
        typeof reason === 'string'
          ? reason
          : `Unhandled rejection without message`
      console.error('unhandled-rejection:', message, reason)
    })
  })

  page.on('console', (message) => {
    if (message.type() === 'error') {
      throw new Error(`Console error: ${message.text()}`)
    }
  })

  await registerApiMocks(page)
})

test('models interactions and the results scenario round trip', async ({ page }) => {
  await page.goto('/')

  // Models page: dialog, filters, train-model round trip (as the monolith had it)
  await page.getByRole('button', { name: 'Models' }).click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  await page.getByRole('button', { name: 'New Model' }).click()
  await expect(page.getByText('Create New Model')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()
  // Only Ready/All remain: the Training/Draft filters were removed in the
  // honest-UI round (the catalogue endpoint returns completed training jobs
  // only, so those filters could never fill). The monolith's four-label loop
  // predates that removal -- and because no e2e run happened between the
  // removal and the split that dropped this whole walk, nothing caught the
  // drift. Restored coverage pins the UI as it ships.
  for (const label of ['Ready', 'All']) {
    await page.getByRole('button', { name: new RegExp(`^${label}`) }).click()
  }
  const trainButton = page.getByRole('button', { name: 'Train Model' }).first()
  await trainButton.click()
  await expect(page.getByText(/Train Model ·/)).toBeVisible()
  await page.locator('div:has-text("Train Model ·")').locator('button:has-text("Cancel")').click()
  await expect(page.getByText(/Train Model ·/)).not.toBeVisible()

  // Details drawer -> Scenario Builder -> run a named scenario
  await page.getByRole('button', { name: 'View Details' }).first().click()
  const modelsScenarioBuilder = page.locator('section').filter({
    has: page.getByRole('heading', { name: 'Scenario Builder' })
  })
  await expect(modelsScenarioBuilder).toBeVisible()
  await modelsScenarioBuilder.getByPlaceholder('e.g., Volatility +20%').fill('Custom Scenario')
  const modelsScenarioSlider = modelsScenarioBuilder.locator('input[type="range"]').first()
  await expect(modelsScenarioSlider).toBeVisible()
  await modelsScenarioSlider.focus()
  for (let step = 0; step < 5; step += 1) {
    await modelsScenarioSlider.press('ArrowRight')
  }
  await expect(modelsScenarioSlider).toHaveAttribute('value', '5')
  await modelsScenarioBuilder.getByRole('button', { name: 'Run Scenario' }).first().click()
  await expect(page.getByText('Custom Scenario')).toBeVisible()

  // Launch Explainability -> Results page with the scenario predictions
  await page.getByRole('button', { name: 'Launch Explainability' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Custom Scenario' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Scenario Predictions' })).toBeVisible()

  // Results scenario card: drive the slider negative and re-run
  const resultsScenarioCard = page.getByRole('heading', { name: 'Scenario Builder' }).locator('..').locator('..')
  await expect(resultsScenarioCard).toBeVisible()
  const resultsScenarioSlider = resultsScenarioCard.locator('input[type="range"]').first()
  await expect(resultsScenarioSlider).toBeVisible()
  await resultsScenarioSlider.focus()
  for (let step = 0; step < 15; step += 1) {
    await resultsScenarioSlider.press('ArrowLeft')
  }
  await expect(resultsScenarioSlider).toHaveAttribute('value', /^-/)
  await resultsScenarioCard.getByRole('button', { name: 'Run Scenario' }).first().click()
  await expect(page.getByText('Scenario executed with mocked response.')).toBeVisible()

  // Back to Models; the details drawer survives the round trip -- wait for
  // its Close button rather than sampling it (the monolith recorded why: a
  // isVisible() race once let the drawer backdrop swallow later clicks).
  await page.getByRole('button', { name: 'Back to Models' }).click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  const closeDrawerButton = page.getByRole('button', { name: 'Close' }).first()
  await expect(closeDrawerButton).toBeVisible()
  await closeDrawerButton.click()
  await expect(closeDrawerButton).toHaveCount(0)
})

test('predictive validity report card on Results', async ({ page }) => {
  await page.goto('/')

  // Served by GET /api/v2/reports/validation/{job_id}; the endpoint answers
  // `validated` only for backtest jobs, so the deep link names the backtest
  // fixture (104) -- via the same hash route a shared report would use.
  await page.evaluate(() => { window.location.hash = '#/results?modelId=201&jobId=104' })
  await expect(
    page.getByRole('heading', { name: 'Predictive validity — job #104' })
  ).toBeVisible()
  await expect(page.getByText('insufficient stress events in window')).toBeVisible()
})

test('a refused prediction renders as absence, never as a number', async ({ page }) => {
  await page.goto('/')

  // The baseline scenario fixture (201:301) carries one assessed source, one
  // not-measurable source and one refused source -- the three states the
  // deep-ensemble wiring can put a row in.
  await page.evaluate(() => { window.location.hash = '#/results?modelId=201&scenarioId=301' })
  await expect(page.getByRole('heading', { name: 'Scenario Predictions' })).toBeVisible()

  const refusedRow = page.locator('tr', { hasText: 'FX Swap Basis' })
  await expect(refusedRow).toBeVisible()
  // The score columns are dashes: absence, not 0.0000.
  await expect(refusedRow.locator('td').nth(1)).toHaveText('—')
  await expect(refusedRow.locator('td').nth(2)).toHaveText('—')
  await expect(refusedRow.locator('td').nth(3)).toHaveText('—')
  // And the row says why, in the risk palette's refusal colour.
  await expect(refusedRow.getByText('Refused')).toBeVisible()
  await expect(refusedRow.getByText(/extrapolating/)).toBeVisible()

  // The assessed source shows its measured split; the single-checkpoint
  // source states the split is not measurable rather than showing a fake 0%.
  const assessedRow = page.locator('tr', { hasText: 'Liquidity Buffer' })
  await expect(assessedRow.getByText('epistemic 11%')).toBeVisible()
  const notMeasurableRow = page.locator('tr', { hasText: 'Cash Burn Rate' })
  await expect(notMeasurableRow.getByText('not measurable')).toBeVisible()
})
