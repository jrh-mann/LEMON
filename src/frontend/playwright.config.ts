import { defineConfig } from '@playwright/test'

/**
 * Playwright E2E config for LEMON frontend.
 *
 * Tests run against the Vite dev server on :5173.
 * Start it beforehand with `npm run dev` (or `./dev.sh`).
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    // Chromium only — no need for Firefox/WebKit
    browserName: 'chromium',
  },
  // Don't auto-start the dev server — assumes it's already running
  webServer: undefined,
})
