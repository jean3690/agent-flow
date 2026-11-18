import { defineConfig, devices } from '@playwright/test'

// Isolated frontend regressions: all API requests are mocked in the tests.
export default defineConfig({
  testDir: './tests/browser',
  outputDir: './test-results/frontend',
  fullyParallel: true,
  workers: 2,
  forbidOnly: !!process.env.CI,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:5175',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5175 --strictPort',
    url: 'http://127.0.0.1:5175',
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: '/api' }
  }
})
