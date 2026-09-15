import { test, expect } from '@playwright/test'
import { registerApiMocks } from './apiMocks.js'

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
          : reason?.message || 'Unhandled rejection without message'
      console.error('unhandled-rejection:', message)
    })
  })

  page.on('console', (message) => {
    if (message.type() === 'error') {
      throw new Error(`Console error: ${message.text()}`)
    }
  })

  await registerApiMocks(page)
})

test('navigates the application and exercises primary interactions', async ({ page }) => {
  await page.goto('/')

  // Dashboard interactions
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  // The state-driven checklist replaced the guided tour: in this mocked
  // deployment sources exist, have fetched and are scheduled, so the only
  // step left is the missing exposure matrix -- and dismissing it sticks.
  const checklistStep = page.getByText('Upload or estimate interbank exposures')
  await expect(checklistStep).toBeVisible()
  await page.getByRole('button', { name: 'dismiss' }).first().click()
  await expect(checklistStep).not.toBeVisible()
  const dashboardNewJobButton = page.getByRole('main').getByRole('button', { name: 'New Job', exact: true })
  await expect(dashboardNewJobButton).toBeVisible()
  await dashboardNewJobButton.click()
  const dashboardJobForm = page.locator('#job-create-form')
  await expect(dashboardJobForm).toBeVisible()
  await expect(dashboardJobForm.getByLabel('Job Type')).toHaveValue('data_collection')
  await dashboardJobForm.getByLabel('Job Name').fill('Liquidity Health Check')
  await dashboardJobForm
    .getByLabel('Description')
    .fill('Ensure dataset selection and date ranges submit without errors.')
  await dashboardJobForm.getByLabel('Region').selectOption('europe')
  await dashboardJobForm.getByLabel('Countries').fill('Germany, France')
  await dashboardJobForm.getByLabel('Start Date').fill('2023-01-01')
  await dashboardJobForm.getByLabel('End Date').fill('2023-12-31')
  await expect(dashboardJobForm.getByText('Selected Datasets (0)')).toBeVisible()
  await dashboardJobForm.getByPlaceholder('Filter by name, code, category, or region').fill('Liquidity')
  await dashboardJobForm.getByRole('checkbox').first().check()
  await expect(dashboardJobForm.getByText('Selected Datasets (1)')).toBeVisible()
  const createJobButton = page.getByRole('button', { name: 'Create Job', exact: true })
  await expect(createJobButton).toBeEnabled()
  await createJobButton.click()
  await expect(dashboardJobForm).not.toBeVisible()
  await page.getByRole('button', { name: 'View All' }).click()
  const searchButton = page.getByRole('button', { name: 'Search' })
  if (await searchButton.isVisible()) {
    await searchButton.click()
    const searchInput = page.getByPlaceholder('Search pages, jobs, models, countries...')
    await expect(searchInput).toBeVisible()
    await searchInput.fill('Models')
    await page.keyboard.press('Escape')
    await expect(searchInput).not.toBeVisible()
  }

  // Risk Map interactions
  await page.getByRole('button', { name: 'Risk Map', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Risk Map' })).toBeVisible()
  await expect(page.getByTestId('risk-map')).toBeVisible()
  await expect(page.getByTestId('risk-map').locator('canvas')).toBeVisible()
  await expect(page.getByTestId('map-legend')).toBeVisible()
  await expect(page.getByTestId('map-attribution')).toContainText('Natural Earth')

  const networkToggle = page.getByRole('button', { name: /Show Network|Hide Network/ })
  if (await networkToggle.isVisible()) {
    await networkToggle.click()
    await expect(page.getByRole('button', { name: 'Hide Network' })).toBeVisible()
  }
  // The network layer's intake path: with no exposure matrix in this mocked
  // deployment the strip offers the two ways to get one, and the estimate
  // modal carries its caveat verbatim from the API response.
  await page.getByRole('button', { name: 'Estimate from marginals' }).click()
  await page.getByRole('button', { name: 'Estimate', exact: true }).click()
  await expect(page.getByText('a prior over bilateral structure')).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()

  const heatmapToggle = page.getByRole('button', { name: /Show Heatmap|Hide Heatmap/ })
  if (await heatmapToggle.isVisible()) {
    await heatmapToggle.click()
    await expect(page.getByRole('button', { name: 'Show Heatmap' })).toBeVisible()
    await heatmapToggle.click()
  }
  await page.getByRole('button', { name: 'Reset View' }).click()

  // Region selection updates the detail panel and the bank list
  await page.getByRole('button', { name: 'United Kingdom', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Region Details' })).toBeVisible()
  await expect(page.getByText('FDIC Liquidity Coverage')).toBeVisible()
  await page.getByRole('button', { name: /FDIC/i }).click()

  // Models interactions
  await page.getByRole('button', { name: 'Models' }).click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  await page.getByRole('button', { name: 'New Model' }).click()
  await expect(page.getByText('Create New Model')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()
  for (const label of ['Ready', 'Training', 'Draft', 'All']) {
    await page.getByRole('button', { name: new RegExp(`^${label}`) }).click()
  }
  const trainButton = page.getByRole('button', { name: 'Train Model' }).first()
  await trainButton.click()
  await expect(page.getByText(/Train Model ·/)).toBeVisible()
  await page.locator('div:has-text("Train Model ·")').locator('button:has-text("Cancel")').click()
  await expect(page.getByText(/Train Model ·/)).not.toBeVisible()
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
  const modelsRunScenarioButton = modelsScenarioBuilder.getByRole('button', { name: 'Run Scenario' }).first()
  await modelsRunScenarioButton.click()
  await expect(page.getByText('Custom Scenario')).toBeVisible()
  await page.getByRole('button', { name: 'Launch Explainability' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Custom Scenario' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Scenario Predictions' })).toBeVisible()
  const resultsScenarioCard = page.getByRole('heading', { name: 'Scenario Builder' }).locator('..').locator('..')
  await expect(resultsScenarioCard).toBeVisible()
  const resultsScenarioSlider = resultsScenarioCard.locator('input[type="range"]').first()
  await expect(resultsScenarioSlider).toBeVisible()
  await resultsScenarioSlider.focus()
  for (let step = 0; step < 15; step += 1) {
    await resultsScenarioSlider.press('ArrowLeft')
  }
  await expect(resultsScenarioSlider).toHaveAttribute('value', /^-/)
  const resultsRunScenarioButton = resultsScenarioCard.getByRole('button', { name: 'Run Scenario' }).first()
  await resultsRunScenarioButton.click()
  await expect(page.getByText('Scenario executed with mocked response.')).toBeVisible()
  await page.getByRole('button', { name: 'Back to Models' }).click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  // The details drawer survives the round trip to Results. Wait for its Close
  // button rather than sampling it: a isVisible() race once skipped the click,
  // and the drawer's backdrop then intercepted every later navigation click.
  const closeDrawerButton = page.getByRole('button', { name: 'Close' }).first()
  await expect(closeDrawerButton).toBeVisible()
  await closeDrawerButton.click()
  await expect(closeDrawerButton).toHaveCount(0)

  // Jobs interactions
  await page.getByRole('button', { name: 'Jobs' }).click()
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible()
  await page.getByRole('button', { name: 'Batch Operations' }).click()
  await page.getByRole('button', { name: 'Exit Batch Mode' }).click()
  for (const label of ['Active', 'Completed', 'Failed', 'All']) {
    await page.getByRole('button', { name: new RegExp(label) }).click()
  }
  await page.getByText('ID: 101').first().click()
  await expect(page.getByRole('heading', { name: 'Job Details' })).toBeVisible()
  const trainWithData = page.getByRole('button', { name: 'Train with this data' })
  if (await trainWithData.isVisible()) {
    await expect(trainWithData).toBeEnabled()
    // The training flow depends on asynchronous background mutations that
    // are outside the scope of the mocked API responses in this test suite.
    // We simply assert that the control is interactable so the remainder of
    // the navigation path remains stable.
  }

  // A failed job shows the reason a human can act on, and retries as a new
  // job with the same parameters instead of asking for the form again.
  await page.getByText('ID: 103').first().click()
  await expect(
    page.getByText('The provider stopped answering mid-download. Nothing was written; retrying is safe.')
  ).toBeVisible()
  await page.getByRole('button', { name: 'Retry job' }).click()
  await expect(page.getByRole('button', { name: 'Retry job' })).toBeVisible()

  // Data Sources interactions
  await page.getByRole('button', { name: 'Data Sources' }).click()
  await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible()
  await page.getByRole('button', { name: 'Add Source' }).click()
  const dataSourceForm = page.locator('#data-source-form')
  await expect(page.getByRole('heading', { name: 'Add Data Source' })).toBeVisible()
  await expect(dataSourceForm).toBeVisible()
  await dataSourceForm.getByLabel('Name').fill('Playwright Synthetic Source')
  await dataSourceForm.getByLabel('Plugin Type').selectOption('fdic')
  await dataSourceForm
    .getByLabel('Description', { exact: true })
    .fill('End-to-end validation source configured through tests.')
  const enabledCheckbox = dataSourceForm.getByLabel('Enabled')
  await enabledCheckbox.uncheck()
  await enabledCheckbox.check()
  await dataSourceForm.getByLabel('Registration required').check()
  await dataSourceForm.getByLabel('Registration URL').fill('https://example.com/register')
  await dataSourceForm.getByLabel('Free Tier Limits').fill('1,000 calls per day')
  await dataSourceForm
    .getByLabel('Coverage Description')
    .fill('Covers major liquidity and capital datasets.')
  await dataSourceForm
    .getByLabel('Configuration (JSON)')
    .fill(`{
  "api_key": "demo"
}`)
  await expect(page.getByRole('button', { name: 'Create Source' })).toBeEnabled()
  await page.getByRole('button', { name: 'Create Source' }).click()
  await expect(dataSourceForm).not.toBeVisible()
  await page.getByRole('button', { name: 'Sync Now' }).first().click()
  await page.getByRole('button', { name: 'Configure' }).first().click()
  await expect(page.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible()
  await expect(dataSourceForm).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save Changes' })).toBeEnabled()
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(dataSourceForm).not.toBeVisible()
  await page.getByRole('button', { name: 'View Data' }).first().click()
  const dataSourceDetailsHeading = page.getByRole('heading', { name: /Data Source ·/ })
  await expect(dataSourceDetailsHeading).toBeVisible()
  await page.getByRole('button', { name: 'Close' }).last().click()

  // Control room: the schedule selector, the scheduler's health view and the
  // live probe. The overdue feed (ECB, two consecutive failures) must show its
  // backoff rather than silently looking idle, and the manual feed must not
  // claim to be overdue.
  await expect(page.getByLabel('Collection schedule for FDIC Call Reports')).toBeVisible()
  await page.getByLabel('Collection schedule for FDIC Call Reports').selectOption('60')
  await expect(page.getByText('overdue · retry ×4')).toBeVisible()
  await page.getByRole('button', { name: 'Test connection' }).first().click()
  await expect(page.getByText('Reachable: provider answered 200')).toBeVisible()

  // Country Profiles interactions
  await page.getByRole('button', { name: 'Country Profiles' }).click()
  await expect(page.getByRole('heading', { name: 'Country Profiles' })).toBeVisible()
  const exportButton = page.getByRole('button', { name: 'Export' })
  await expect(exportButton).toBeEnabled()
  await exportButton.click()
  await page.getByRole('button', { name: 'Export as CSV' }).click()
  await exportButton.click()
  await page.getByRole('button', { name: 'Export as JSON' }).click()
  await page.getByRole('button', { name: 'Refresh' }).click()
  await page.getByRole('button', { name: 'Sync from World Bank' }).click()
  await page.getByRole('button', { name: 'Clear Filters' }).click()
  await page.getByRole('button', { name: 'View Details & Run Analysis' }).first().click()

  // Model Performance interactions
  await page.getByRole('button', { name: 'Performance' }).click()
  await expect(page.getByRole('heading', { name: 'Model Performance Dashboard' })).toBeVisible()
  const r2ColumnHeader = page.locator('th').filter({ hasText: 'R² Score' }).first()
  await expect(r2ColumnHeader).toBeVisible()
  await r2ColumnHeader.click()
  await r2ColumnHeader.click()
  await expect(r2ColumnHeader).toBeVisible()
  await page.getByRole('button', { name: 'Refresh' }).click()
  await page.getByRole('button', { name: 'New Model' }).click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  await page.getByRole('button', { name: 'Performance' }).click()
  await expect(page.getByRole('heading', { name: 'Model Performance Dashboard' })).toBeVisible()

  // Data Quality interactions
  await page.getByRole('button', { name: 'Data Quality' }).click()
  await expect(page.getByRole('heading', { name: 'Data Quality Monitoring' })).toBeVisible()
  await expect(page.getByText('Overall Health')).toBeVisible()
  await expect(page.getByText('Data Source Details')).toBeVisible()
  // The cadence panel states the scheduler's promise versus reality; the
  // backing-off feed says so, and the manual-only feed shows no false alarm.
  await expect(page.getByRole('heading', { name: 'Refresh Cadence' })).toBeVisible()
  await expect(page.getByText('backing off ×4')).toBeVisible()
  // Scoped to the details table: the Refresh Cadence panel above also
  // names the feed, and both are correct.
  await expect(page.getByRole('table').getByText('FDIC Call Reports')).toBeVisible()

  // Analytics interactions
  await page.getByRole('button', { name: 'Analytics' }).click()
  await expect(page.getByRole('heading', { name: 'Advanced Analytics' })).toBeVisible()
  await page.getByRole('button', { name: '14d' }).click()
  const trendsCard = page
    .locator('div')
    .filter({ has: page.getByRole('heading', { name: 'Trends Over Time' }) })
    .first()
  await trendsCard.getByRole('button', { name: 'Data Quality' }).last().click()
  await trendsCard.getByRole('button', { name: 'Job Success' }).last().click()
  await expect(page.getByText('Job Type Distribution')).toBeVisible()

  // Settings interactions
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await page.getByRole('button', { name: /Daily email alerts/ }).click()
  await page.getByRole('button', { name: 'Mute all' }).click()
  await page.getByRole('button', { name: 'Restore defaults' }).click()
  await page.getByRole('button', { name: 'Connect' }).first().click()
  // The guided tour and the Help page were removed while the platform is still
  // maturing; guided help lands again when the system does. Until then the
  // suite asserts they stay gone, in the same style as the dispositions census:
  // a removal is a decision, and a decision gets a test.
  await expect(page.getByRole('button', { name: /Start Tour|Restart Tour/ })).toHaveCount(0)

  // Help interactions: the page is gone, and its marketing-era content with it.
  await expect(page.getByRole('button', { name: 'Help', exact: true })).toHaveCount(0)
  await expect(page.getByText('Ask Beacon Support')).toHaveCount(0)
  await expect(page.getByText('Popular walkthroughs')).toHaveCount(0)
})

// Regression guard for the global search palette. The previous version read
// `.jobs` / `.models` / `.items` off endpoints that return bare arrays, and
// fetched /api/v1/data-catalogue, which does not exist — so three of its four
// live categories silently returned nothing. The old test opened the palette and
// pressed Escape without ever asserting that a result appeared, which is why the
// breakage was invisible in CI.
test('global search finds jobs, models and catalogue items', async ({ page }) => {
  await page.goto('/')

  const openSearch = async () => {
    // The palette's key handler registers when the header mounts. The welcome
    // banner's dismissal used to give the app this beat for free; with the
    // banner gone the first keypress raced React and lost, so wait for the
    // chrome instead of guessing.
    await expect(page.getByRole('button', { name: 'Search' })).toBeVisible()
    await page.keyboard.press('Control+k')
    const input = page.getByPlaceholder('Search pages, jobs, models, countries...')
    await expect(input).toBeVisible()
    return input
  }

  const input = await openSearch()

  // A job, from the bare array that /api/v1/jobs returns.
  await input.fill('data_collection')
  await expect(page.getByText('Job #101 - data_collection')).toBeVisible()

  // A model, from the bare array that /api/models returns. Read from
  // `model_id`/`name`, which is what ModelSummary actually declares.
  await input.fill('Liquidity Forecaster')
  await expect(page.getByText('Liquidity Forecaster').first()).toBeVisible()

  // A catalogue item, from /api/v1/catalogue — the URL that previously 404'd.
  await input.fill('FDIC Liquidity Coverage')
  await expect(page.getByText('FDIC Liquidity Coverage')).toBeVisible()

  // A query that matches nothing must say so rather than render a blank panel.
  await input.fill('zzzz-no-such-thing')
  await expect(page.getByText(/No results found/)).toBeVisible()
})
