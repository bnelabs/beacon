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

// Regression guard for the global search palette
test('global search finds jobs, models and catalogue items', async ({ page }) => {
  await page.goto('/')

  const openSearch = async () => {
    await expect(page.getByRole('button', { name: 'Search' })).toBeVisible()
    await page.keyboard.press('Control+k')
    const input = page.getByPlaceholder('Search pages, jobs, models, countries...')
    await expect(input).toBeVisible()
    return input
  }

  const input = await openSearch()

  // A job, from the bare array that /api/v1/jobs returns
  await input.fill('data_collection')
  await expect(page.getByText('Job #101 - data_collection')).toBeVisible()

  // A model, from the bare array that /api/models returns
  await input.fill('TEMPORAL_ATTENTION')
  await expect(page.getByText('TEMPORAL_ATTENTION').first()).toBeVisible()

  // A catalogue item, from /api/v1/catalogue
  await input.fill('FDIC Liquidity Coverage')
  await expect(page.getByText('FDIC Liquidity Coverage')).toBeVisible()

  // A query that matches nothing must say so
  await input.fill('zzzz-no-such-thing')
  await expect(page.getByText(/No results found/)).toBeVisible()
})
