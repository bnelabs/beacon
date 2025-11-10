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
  const maybeLaterButton = page.getByRole('button', { name: 'Maybe Later' })
  if (await maybeLaterButton.isVisible()) {
    await maybeLaterButton.click()
    await expect(page.getByRole('heading', { name: 'Welcome to BEACON! 👋' })).not.toBeVisible()
  }
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

  // Globe View interactions
  await page.getByRole('button', { name: 'Globe View' }).click()
  await expect(page.getByRole('heading', { name: 'Globe View' })).toBeVisible()
  const networkToggle = page.getByRole('button', { name: /Show Network|Hide Network/ })
  if (await networkToggle.isVisible()) {
    await networkToggle.click()
  }
  const rotationToggle = page.getByRole('button', { name: /Auto Rotate|Stop Rotation/ })
  if (await rotationToggle.isVisible()) {
    await rotationToggle.click()
  }
  await page.getByRole('button', { name: 'Reset View' }).click()
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
  const closeDrawerButton = page.getByRole('button', { name: 'Close' }).first()
  if (await closeDrawerButton.isVisible()) {
    await closeDrawerButton.click()
  }

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
  await expect(page.getByText('FDIC Call Reports')).toBeVisible()

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
  await expect(page.getByRole('button', { name: /Start Tour|Restart Tour/ })).toBeVisible()

  // Help interactions
  await page.getByRole('button', { name: 'Help' }).click()
  await expect(page.getByRole('heading', { name: 'Help Center' })).toBeVisible()
  await expect(page.getByText('Popular walkthroughs')).toBeVisible()
  await expect(page.getByText('Ask Beacon Support')).toBeVisible()
})
