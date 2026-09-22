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

test('data sources CRUD operations', async ({ page }) => {
  await page.goto('/')

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
    .fill(`{\n  "api_key": "demo"\n}`)
  
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
})

test('control room schedule and health checks', async ({ page }) => {
  await page.goto('/')

  // The schedule selector, health view and live probe live on the Data
  // Sources page -- the monolith this spec was split from reached them after
  // the CRUD section; each split test starts from a fresh page and must
  // navigate there itself.
  await page.getByRole('button', { name: 'Data Sources' }).click()
  await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible()

  await expect(page.getByLabel('Collection schedule for FDIC Call Reports')).toBeVisible()
  await page.getByLabel('Collection schedule for FDIC Call Reports').selectOption('60')
  await expect(page.getByText('overdue · retry ×4')).toBeVisible()
  await page.getByRole('button', { name: 'Test connection' }).first().click()
  await expect(page.getByText('Reachable: provider answered 200')).toBeVisible()
})

test('country profiles interactions', async ({ page }) => {
  await page.goto('/')

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
})

test('model performance dashboard', async ({ page }) => {
  await page.goto('/')

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
})

test('data quality monitoring', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Data Quality' }).click()
  await expect(page.getByRole('heading', { name: 'Data Quality Monitoring' })).toBeVisible()
  await expect(page.getByText('Overall Health')).toBeVisible()
  await expect(page.getByText('Data Source Details')).toBeVisible()
  
  await expect(page.getByRole('heading', { name: 'Refresh Cadence' })).toBeVisible()
  await expect(page.getByText('backing off ×4')).toBeVisible()
  await expect(page.getByRole('table').getByText('FDIC Call Reports')).toBeVisible()

  // The unit, actually measured. The gate writes 0-100 percentages and every
  // quality endpoint returns them unscaled, but this page multiplied
  // avg_quality_score by 100 a second time -- 76 printed as 7600.0% and every
  // assertion above still passed. A spec that only checks labels cannot see a
  // wrong scale, so it checks the numbers the mock is known to produce
  // (avg_quality_score 76, avg_completeness 92, FDIC row 88) and refuses any
  // percentage whose integer part has four or more digits.
  await expect(page.getByText('76.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('92.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('88.0%', { exact: true })).toBeVisible()
  await expect(page.getByText(/\d{4,}\.\d%/)).toHaveCount(0)
})

test('analytics dashboard', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Analytics' }).click()
  await expect(page.getByRole('heading', { name: 'Advanced Analytics' })).toBeVisible()

  // Same contract on the other consumer of the gate's scores:
  // /v1/analytics/overview publishes avg_quality_score 82 and
  // avg_completeness 90 on the same 0-100 scale, and this card rendered both
  // as a 0-1 fraction (0.8200, then 9000.0%).
  await expect(page.getByText('82.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('90.0%', { exact: true })).toBeVisible()
  await expect(page.getByText(/\d{4,}\.\d%/)).toHaveCount(0)
  
  await page.getByRole('button', { name: '14d' }).click()
  const trendsCard = page
    .locator('div')
    .filter({ has: page.getByRole('heading', { name: 'Trends Over Time' }) })
    .first()
  await trendsCard.getByRole('button', { name: 'Data Quality' }).last().click()
  await trendsCard.getByRole('button', { name: 'Job Success' }).last().click()
  await expect(page.getByText('Job Type Distribution')).toBeVisible()
})

test('settings page', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  
  await page.getByRole('button', { name: /Daily email alerts/ }).click()
  await page.getByRole('button', { name: 'Mute all' }).click()
  await page.getByRole('button', { name: 'Restore defaults' }).click()
  
  await expect(page.getByRole('button', { name: 'Connect', exact: true })).toHaveCount(0)
  await expect(page.getByText('Linked data feeds')).toBeVisible()
  await page.getByRole('button', { name: 'Add in Data Sources' }).first().click()
  await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible()
  await expect(page.getByText('No data sources configured')).toHaveCount(0)
  
  // Guided tour and Help page are removed
  await expect(page.getByRole('button', { name: /Start Tour|Restart Tour/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Help', exact: true })).toHaveCount(0)
  await expect(page.getByText('Ask Beacon Support')).toHaveCount(0)
  await expect(page.getByText('Popular walkthroughs')).toHaveCount(0)
})
