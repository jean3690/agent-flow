import { defineConfig } from '@playwright/test'

// Reuse the existing runner; these tests need neither a browser nor a server.
export default defineConfig({
  testDir: './tests/unit',
  outputDir: './test-results/unit',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: 'list'
})
