/**
 * E2E test: chat round-trip against live backend.
 *
 * Verifies the full pipeline: HTTP POST → backend thread → LLM call →
 * socket streaming → chat_response → UI update.
 *
 * Requires both servers running:
 *   LEMON_ALLOW_REGISTRATION=true bash scripts/dev.sh start
 */
import { test, expect, type Page } from '@playwright/test'

// LLM responses on Azure Foundry take 5-45s; tool calls add more
test.setTimeout(120_000)
test.use({ viewport: { width: 1280, height: 900 } })

// ── Helpers ──────────────────────────────────────────────────────

/** Register a fresh test user. */
async function registerUser(page: Page) {
  const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.local`
  const res = await page.request.post('http://localhost:5173/api/auth/register', {
    data: { email, name: 'E2E Chat Test', password: 'TestPassword123!', remember: false },
  })
  if (!res.ok()) throw new Error(`Registration failed (${res.status()}): ${await res.text()}`)
}

/** Navigate to /workflow, reveal workspace, wait for chat input. */
async function openNewWorkflow(page: Page) {
  await page.goto('/workflow')
  await page.waitForLoadState('networkidle')

  const buildLink = page.locator('header a, header button, .home-content button, .home-content a')
    .filter({ hasText: /build|new|start/i }).first()
  await buildLink.waitFor({ timeout: 15_000 })
  await buildLink.click()

  await page.waitForFunction(() => !!document.querySelector('.workspace-revealed'), { timeout: 15_000 })
  await page.waitForFunction(() => {
    const el = document.querySelector('#chatInput') as HTMLTextAreaElement | null
    return el && !el.disabled
  }, { timeout: 15_000 })
}

/** Type a message, click Send, wait for the HTTP POST to fire. */
async function sendMessage(page: Page, text: string) {
  await page.waitForRequest(
    async req => {
      if (!req.url().includes('/api/chat/send') || req.method() !== 'POST') return false
      // Only start waiting once our message is sent
      return true
    },
    { timeout: 10_000 },
  ).catch(() => {})  // waitForRequest fires in parallel below

  const postPromise = page.waitForRequest(
    req => req.url().includes('/api/chat/send') && req.method() === 'POST',
  )
  await page.fill('#chatInput', text)
  await page.click('#sendBtn')
  await postPromise
}

/** Wait for the full response to complete (input re-enabled, no streaming). */
async function waitForResponseComplete(page: Page, timeout = 90_000) {
  await expect(page.locator('#chatInput')).toBeEnabled({ timeout })
  await expect(page.locator('.message.assistant.streaming')).toHaveCount(0, { timeout: 5_000 })
}

// ── Tests ────────────────────────────────────────────────────────

test.describe('chat E2E — live backend', () => {
  test('simple text response arrives via streaming', async ({ page }) => {
    // Capture socket events for diagnostics
    const sioLogs: string[] = []
    page.on('console', msg => {
      if (msg.text().includes('[SIO]')) sioLogs.push(msg.text())
    })

    await registerUser(page)
    await openNewWorkflow(page)
    await sendMessage(page, 'Say hello. Reply with just one sentence.')

    // User message should appear immediately
    await expect(page.locator('.message.user')).toHaveCount(1, { timeout: 5_000 })

    // Wait for the full response cycle
    await waitForResponseComplete(page)

    // Assistant message should exist with real content (not just "Thinking...")
    const assistant = page.locator('.message.assistant')
    await expect(assistant.first()).toBeVisible({ timeout: 5_000 })
    const content = await assistant.first().locator('.message-content').textContent()
    expect(content?.length, 'assistant message should have content').toBeGreaterThan(0)
    expect(content, 'content should not be a processing status').not.toBe('Thinking...')

    // Socket events should include chat_progress and chat_response
    const hasProgress = sioLogs.some(l => l.includes('chat_progress'))
    const hasResponse = sioLogs.some(l => l.includes('chat_response'))
    expect(hasProgress, 'should have received chat_progress event').toBe(true)
    expect(hasResponse, 'should have received chat_response event').toBe(true)
  })
})
