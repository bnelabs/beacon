import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', timeout: 120000, expect: { timeout: 30000 }, retries: 0,
  use: { baseURL: 'http://127.0.0.1:8173', headless: true, viewport: { width: 1440, height: 900 },
    launchOptions: { args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] } },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:8173', reuseExistingServer: true, timeout: 120000 },
  reporter: [['list']]
})
