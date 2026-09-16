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

test('dashboard loads and handles job creation', async ({ page }) => {
  await page.goto('/')

  // Dashboard interactions
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  
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
})

test('risk map renders and handles network/heatmap toggles', async ({ page }) => {
  await page.goto('/')

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
  
  await page.getByRole('button', { name: 'Estimate from marginals' }).click()
  await page.getByRole('button', { name: 'Estimate', exact: true }).click()
  await expect(page.getByText('a prior over bilateral structure')).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()

  const heatmapToggle = page.getByRole('button', { name: /Show Heatmap|Hide Heatmap/ })
  if (await heatmapToggle.isVisible()) {
    await heatmapToggle.click()
    await expect(page.getByRole('button', { name: 'Show Heatmap' })).toBeVisible()
  }
})

test('jobs list filters and shows job details', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Jobs' }).click()
  await expect(page.getByRole('heading', { name: 'Jobs' })).toBeVisible()
  
  for (const label of ['Active', 'Completed', 'Failed', 'All']) {
    await page.getByRole('button', { name: new RegExp(label) }).click()
  }
  
  await page.getByText('ID: 101').first().click()
  await expect(page.getByRole('heading', { name: 'Job Details' })).toBeVisible()
  
  const trainWithData = page.getByRole('button', { name: 'Train with this data' })
  if (await trainWithData.isVisible()) {
    await expect(trainWithData).toBeEnabled()
  }

  // A failed job shows the reason a human can act on
  await page.getByText('ID: 103').first().click()
  await expect(
    page.getByText('The provider stopped answering mid-download. Nothing was written; retrying is safe.')
  ).toBeVisible()
  await page.getByRole('button', { name: 'Retry job' }).click()
  await expect(page.getByRole('button', { name: 'Retry job' })).toBeVisible()
})
