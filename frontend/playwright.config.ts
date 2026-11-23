import { defineConfig, devices } from '@playwright/test'

// UI end-to-end tests drive the real browser against a running stack.
// The three services (web :5173, platform :8084, ai :8000) must already be up,
// e.g. via './start.sh' (or 'make compose'). See .github/workflows/ci.yml.
const webUrl = process.env.AGENTFLOW_WEB_URL || 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: webUrl,
    headless: true,
    trace: 'on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
