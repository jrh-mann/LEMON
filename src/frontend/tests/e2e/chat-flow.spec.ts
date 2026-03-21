/**
 * Integration E2E tests for the chat flow — real backend, no mocks.
 *
 * These tests hit the live backend via SSE streaming, exercising the
 * full pipeline: type → click Send → HTTP POST → SSE events → store → UI.
 *
 * Requires both servers running with LEMON_ALLOW_REGISTRATION=true:
 *   LEMON_ALLOW_REGISTRATION=true bash scripts/dev.sh start
 *
 * Each test registers a fresh user to avoid cross-test contamination.
 */
import { test, expect, type Page } from '@playwright/test'

// Real LLM responses can take minutes
test.setTimeout(180_000)

// Use a tall viewport so the chat dock + send button are in view
test.use({ viewport: { width: 1280, height: 900 } })

// ── Helpers ──────────────────────────────────────────────────────

/** Register a fresh test user. Sets the auth cookie on the page context. */
async function registerUser(page: Page) {
  const email = `e2e_flow_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.local`

  const res = await page.request.post('http://localhost:5173/api/auth/register', {
    data: {
      email,
      name: 'E2E Chat Flow Test',
      password: 'TestPassword123!',
      remember: false,
    },
  })

  if (!res.ok()) {
    const body = await res.text()
    throw new Error(`Registration failed (${res.status()}): ${body}`)
  }
}

/** Navigate to /workflow, click "Build" to reveal workspace, wait for chat input. */
async function openNewWorkflow(page: Page) {
  await page.goto('/workflow')
  await page.waitForLoadState('networkidle')

  // Click the header "Build" nav link to reveal the workspace
  const buildLink = page.locator('header a, header button, .home-content button, .home-content a')
    .filter({ hasText: /build|new|start/i }).first()
  await buildLink.waitFor({ timeout: 15_000 })
  await buildLink.click()

  // Wait for the workspace to reveal (canvas + chat dock visible)
  await page.waitForFunction(
    () => !!document.querySelector('.workspace-revealed'),
    { timeout: 15_000 },
  )

  // Wait for chat input to become enabled
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

test.describe('chat flow — send, stream, respond', () => {
  test('full send → stream → response cycle', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'Add a start node to the workflow. Reply briefly.')

    // User message should appear immediately (optimistic update)
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.user .message-content')).toContainText('start node')

    // Wait for the full response to arrive
    await waitForResponseComplete(page)

    // Assistant message should have real content
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages).toHaveCount(1, { timeout: 10_000 })
    const content = await assistantMessages.first().locator('.message-content').textContent()
    expect(content?.length).toBeGreaterThan(0)

    // Chat input should be re-enabled
    await expect(page.locator('#chatInput')).toBeEnabled()
    await expect(page.locator('#sendBtn')).toBeVisible()
  })

  test('multiple chat turns preserve message order', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // First turn
    await sendMessage(page, 'Add a start node. Reply with just "Done."')
    await waitForResponseComplete(page)

    await expect(page.locator('.message')).toHaveCount(2, { timeout: 10_000 })

    // Second turn
    await sendMessage(page, 'Now add an end node. Reply with just "Done."')
    await waitForResponseComplete(page)

    // Should have 4 messages: user, assistant, user, assistant
    const messageCount = await page.locator('.message').count()
    expect(messageCount).toBeGreaterThanOrEqual(4)

    // Verify order: first user, then assistant, then second user, then assistant
    const roles = await page.locator('.message').evaluateAll(
      els => els.map(el => el.classList.contains('user') ? 'user' : 'assistant'),
    )
    expect(roles[0]).toBe('user')
    expect(roles[1]).toBe('assistant')
    expect(roles[2]).toBe('user')
    expect(roles[3]).toBe('assistant')
  })
})

test.describe('chat flow — stop button', () => {
  test('stop mid-stream or early completion re-enables input', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'Write a very long and detailed essay about workflow automation. Make it at least 2000 words.')

    // Wait for actual response text to start streaming (not just thinking).
    // With adaptive thinking the model can think for 10-30s before text appears.
    // Poll the zustand store to detect when streamingContent is non-empty,
    // OR when the response has already completed (messages.length > 1).
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('lemon-chat')
        if (!raw) return false
        try {
          const parsed = JSON.parse(raw)
          const wfId = parsed?.state?.activeWorkflowId
          const conv = parsed?.state?.conversations?.[wfId]
          if (!conv) return false
          return (conv.streamingContent ?? '').length > 0 || conv.messages.length > 1
        } catch { return false }
      },
      { timeout: 90_000 },
    )

    // Try to click Stop if the response is still in progress
    const stopVisible = await page.locator('#stopBtn').isVisible()
    if (stopVisible) {
      await page.locator('#stopBtn').click()
    }

    // Either way: input should be re-enabled and an assistant message should exist
    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 30_000 })

    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages).toHaveCount(1, { timeout: 5_000 })

    const finalContent = await assistantMessages.first()
      .locator('.message-content').textContent()
    expect(finalContent?.length).toBeGreaterThan(0)
  })

  test('stop then send new message works correctly', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'Write a very long essay about medical triage systems. Make it 3000 words.')

    // Wait for streaming to start
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('lemon-chat')
        if (!raw) return false
        try {
          const parsed = JSON.parse(raw)
          const wfId = parsed?.state?.activeWorkflowId
          const conv = parsed?.state?.conversations?.[wfId]
          if (!conv) return false
          return (conv.streamingContent ?? '').length > 0 || conv.messages.length > 1
        } catch { return false }
      },
      { timeout: 90_000 },
    )

    // Click Stop if still streaming
    const stopVisible = await page.locator('#stopBtn').isVisible()
    if (stopVisible) {
      await page.locator('#stopBtn').click()
    }

    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 30_000 })

    // Send a new message — should work after stop
    await sendMessage(page, 'Thanks, that was enough. Reply with just "OK".')
    await waitForResponseComplete(page)

    // Should have messages from both turns
    const allMessages = page.locator('.message')
    const finalCount = await allMessages.count()
    expect(finalCount).toBeGreaterThanOrEqual(4)
  })
})

test.describe('chat flow — thinking and streaming', () => {
  test('thinking content appears during processing', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'What is a workflow? Explain briefly.')

    // Wait for some indication of processing (thinking indicator, processing status, or streaming)
    await waitForStreamStart(page)

    // Eventually the full response should arrive
    await waitForResponseComplete(page)

    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages.first()).toBeVisible({ timeout: 10_000 })
    const content = await assistantMessages.first().locator('.message-content').textContent()
    expect(content?.length).toBeGreaterThan(10)
  })
})

test.describe('chat flow — refresh during stream', () => {
  test('messages survive refresh and resume reconnects', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // Send a message that triggers a long streaming response with tool calls
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
    // The frontend reconnects via resumeTask or polls building=false.
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

  test('finalized messages persist across refresh', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    await sendMessage(page, 'Add a start node. Reply with just "Done."')
    await waitForResponseComplete(page)

    await expect(page.locator('.message')).toHaveCount(2, { timeout: 10_000 })

    // Refresh the page
    await page.reload()
    await page.waitForLoadState('networkidle')

    // Messages should survive from localStorage
    await expect(page.locator('.message')).toHaveCount(2, { timeout: 10_000 })
    await expect(page.locator('.message.user .message-content')).toContainText('start node')

    // Input should be re-enabled (not stuck in streaming state)
    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 10_000 })
    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 10_000 })
  })
})

test.describe('chat flow — HTTP POST delivery', () => {
  test('sendChatMessage makes HTTP POST with correct payload', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    const postPromise = page.waitForRequest(req =>
      req.url().includes('/api/chat/send') && req.method() === 'POST',
    )

    await page.fill('#chatInput', 'hello world')
    await page.click('#sendBtn')

    const request = await postPromise
    const body = JSON.parse(request.postData() || '{}')

    expect(body.message).toBe('hello world')
    expect(body.task_id).toBeDefined()
    expect(body.current_workflow_id).toBeDefined()
    // No socket_id — SSE replaced Socket.IO
    expect(body.socket_id).toBeUndefined()
  })
})
