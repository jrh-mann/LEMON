/**
 * Real E2E tests against the live backend (no mocks).
 *
 * These tests require both servers running with LEMON_ALLOW_REGISTRATION=true:
 *   LEMON_ALLOW_REGISTRATION=true bash scripts/dev.sh start
 *
 * Tests cover:
 * 1. Refresh mid-stream — streaming resumes after page reload
 * 2. Stop button — partial content preserved, input re-enabled
 * 3. Workflow building — model creates nodes on the canvas via tool calls
 *
 * Each test registers a fresh user to avoid cross-test contamination.
 */
import { test, expect, type Page } from '@playwright/test'

// Increase timeout — real LLM responses + tool calls can take minutes
test.setTimeout(180_000)

// Use a tall viewport so the chat dock + send button are in view
test.use({ viewport: { width: 1280, height: 900 } })

// ── Helpers ──────────────────────────────────────────────────────

/** Register a fresh test user. Sets the auth cookie on the page context. */
async function registerUser(page: Page) {
  const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.local`

  // Register via the Vite proxy so the auth cookie is set on the right domain.
  const res = await page.request.post('http://localhost:5173/api/auth/register', {
    data: {
      email,
      name: 'E2E Live Test',
      password: 'TestPassword123!',
      remember: false,
    },
  })

  if (!res.ok()) {
    const body = await res.text()
    throw new Error(`Registration failed (${res.status()}): ${body}`)
  }
}

/** Navigate to /workflow, click "Build" to reveal workspace, wait for chat. */
async function openNewWorkflow(page: Page) {
  await page.goto('/workflow')
  await page.waitForLoadState('networkidle')

  // Click the header "Build" nav link to reveal the workspace
  const buildLink = page.locator('header a, header button, .home-content button, .home-content a').filter({ hasText: /build|new|start/i }).first()
  await buildLink.waitFor({ timeout: 15_000 })
  await buildLink.click()

  // Wait for the workspace to reveal (canvas + chat dock visible)
  await page.waitForFunction(
    () => !!document.querySelector('.workspace-revealed'),
    { timeout: 15_000 },
  )

  // Wait for Socket.IO to connect and chat input to become enabled
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#chatInput') as HTMLTextAreaElement | null
      return el && !el.disabled
    },
    { timeout: 15_000 },
  )
}

/** Type a message and click Send. Returns after the HTTP POST fires. */
async function sendMessage(page: Page, text: string) {
  const postPromise = page.waitForRequest(
    req => req.url().includes('/api/chat/send') && req.method() === 'POST',
  )
  await page.fill('#chatInput', text)
  await page.click('#sendBtn')
  await postPromise
}

/** Wait for streaming to start (assistant bubble or status indicator). */
async function waitForStreamStart(page: Page) {
  await expect(
    page.locator('.message.assistant.streaming, .processing-status, .typing-indicator').first(),
  ).toBeVisible({ timeout: 30_000 })
}

/** Wait for the response to complete (input re-enabled, no streaming). */
async function waitForResponseComplete(page: Page, timeout = 150_000) {
  await expect(page.locator('#chatInput')).toBeEnabled({ timeout })
  await expect(page.locator('.message.assistant.streaming')).toHaveCount(0, { timeout: 5_000 })
}

// ── Tests ────────────────────────────────────────────────────────

test.describe('live backend — refresh mid-stream', () => {
  test('streaming resumes after page reload', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // Send a message that triggers a long streaming response with tool calls.
    // Tool calls force multi-round LLM interaction, keeping the task alive long enough to refresh.
    await sendMessage(page, 'Build a workflow with 5 nodes: a start node, three sequential action nodes for patient intake, vitals check, and triage decision, and an end node. Connect them all in order. Then describe what you built.')

    // Wait for streaming to begin, then give the task time to process
    await waitForStreamStart(page)
    await page.waitForTimeout(3_000)

    // Refresh the page mid-stream
    await page.reload()
    await page.waitForLoadState('networkidle')

    // After reload, the user message should survive from localStorage
    await expect(page.locator('.message.user')).toHaveCount(1, { timeout: 10_000 })

    // Wait for the response to resume streaming or finish via polling.
    // The frontend reconnects via resume_task or polls building=false.
    await waitForResponseComplete(page)

    // Wait for the assistant message to appear (streaming resume or history merge)
    await page.waitForFunction(
      () => document.querySelectorAll('.message.assistant').length > 0,
      { timeout: 30_000 },
    )

    // Verify the assistant message has real content
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages.first()).toBeVisible({ timeout: 10_000 })

    const finalContent = await assistantMessages.first()
      .locator('.message-content').textContent()
    expect(finalContent?.length).toBeGreaterThan(10)
  })
})

test.describe('live backend — stop button', () => {
  test('stop preserves partial content and re-enables input', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'Write a very long and detailed essay about workflow automation. Make it at least 2000 words.')

    // Wait for visible content in the streaming bubble (thinking or actual response).
    // The finalizeStream fix ensures stopping during thinking mode also preserves content.
    await waitForStreamStart(page)
    await page.waitForFunction(
      () => {
        const streamEl = document.querySelector('.message.assistant.streaming .message-content')
        if (!streamEl) return false
        return (streamEl.textContent ?? '').length > 30
      },
      { timeout: 90_000 },
    )

    // Click Stop
    const stopBtn = page.locator('#stopBtn')
    await expect(stopBtn).toBeVisible({ timeout: 5_000 })
    await stopBtn.click()

    // Chat input should be re-enabled, stop button hidden
    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 10_000 })
    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 5_000 })

    // The partial content should be preserved in an assistant message
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages).toHaveCount(1, { timeout: 5_000 })

    const finalContent = await assistantMessages.first()
      .locator('.message-content').textContent()
    expect(finalContent?.length).toBeGreaterThan(10)

    // Should be able to send a new message after stopping
    await sendMessage(page, 'Thanks, that was enough.')
    await waitForStreamStart(page)
    await waitForResponseComplete(page)

    // Should now have 4 messages: user, assistant (stopped), user, assistant
    const allMessages = page.locator('.message')
    const finalCount = await allMessages.count()
    expect(finalCount).toBeGreaterThanOrEqual(4)
  })
})

test.describe('live backend — conversation persistence', () => {
  test('second message demonstrates awareness of first message', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // First turn: ask to add a start node
    await sendMessage(page, 'Add a start node to the workflow.')
    await waitForResponseComplete(page, 150_000)

    // Canvas should have at least one node
    const canvasNodes = page.locator('.flow-node')
    await expect(canvasNodes.first()).toBeVisible({ timeout: 10_000 })

    // Second turn: ask about what was just done (proves conversation memory)
    await sendMessage(page, 'What did you just add to the workflow? Answer briefly.')
    await waitForResponseComplete(page, 150_000)

    // The second assistant response should reference the start node
    const assistantMessages = page.locator('.message.assistant')
    const secondResponse = assistantMessages.last()
    const content = await secondResponse.locator('.message-content').textContent()
    expect(content?.toLowerCase()).toMatch(/start/)
  })
})

test.describe('live backend — workflow building', () => {
  test('model creates nodes on the canvas via tool calls', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // Ask the model to add a single node — minimal tool call to keep it fast
    await sendMessage(page, 'Add one start node to the workflow.')

    // Wait for the full response to complete
    await waitForResponseComplete(page, 150_000)

    // The assistant should have responded
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages.first()).toBeVisible({ timeout: 10_000 })

    // Check that at least one node appeared on the canvas (custom SVG canvas uses .flow-node)
    const canvasNodes = page.locator('.flow-node')
    const nodeCount = await canvasNodes.count()
    expect(nodeCount).toBeGreaterThanOrEqual(1)

    const assistantContent = await assistantMessages.first()
      .locator('.message-content').textContent()
    expect(assistantContent?.length).toBeGreaterThan(0)
  })
})
