import { defineConfig } from '@playwright/test'

const baseURL = process.env.BEACON_E2E_BASE_URL || 'http://localhost:5173'

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: {
    timeout: 10_000
  },
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1400, height: 900 }
  },
  reporter: [['list']]
})
