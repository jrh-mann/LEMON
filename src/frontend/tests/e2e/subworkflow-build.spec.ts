/**
 * Real E2E test: subworkflow building visible from library navigation.
 *
 * Requires both servers running with LEMON_ALLOW_REGISTRATION=true:
 *   LEMON_ALLOW_REGISTRATION=true bash scripts/dev.sh start
 *
 * Flow:
 * 1. Open a new parent workflow, ask the orchestrator to create a subworkflow
 * 2. Wait for the subworkflow to appear in the library with "Building..." badge
 * 3. Navigate to the building subworkflow
 * 4. Verify that messages, streaming content, or build_history appear in the chat
 * 5. Wait for the build to complete and verify final state
 */
import { test, expect, type Page } from '@playwright/test'

// Subworkflow builds involve multiple LLM rounds — generous timeout
test.setTimeout(300_000)

test.use({ viewport: { width: 1280, height: 900 } })

// ── Helpers ──────────────────────────────────────────────────────

/** Register a fresh test user. */
async function registerUser(page: Page) {
  const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.local`
  const res = await page.request.post('http://localhost:5173/api/auth/register', {
    data: {
      email,
      name: 'E2E Subworkflow Test',
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
  const buildLink = page
    .locator('header a, header button, .home-content button, .home-content a')
    .filter({ hasText: /build|new|start/i })
    .first()
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

/** Type a message and click Send. */
async function sendMessage(page: Page, text: string) {
  const postPromise = page.waitForRequest(
    req => req.url().includes('/api/chat/send') && req.method() === 'POST',
  )
  await page.fill('#chatInput', text)
  await page.click('#sendBtn')
  await postPromise
}

/** Wait for the response to complete (input re-enabled, no streaming). */
async function waitForResponseComplete(page: Page, timeout = 150_000) {
  await expect(page.locator('#chatInput')).toBeEnabled({ timeout })
  await expect(page.locator('.message.assistant.streaming')).toHaveCount(0, { timeout: 5_000 })
}

// ── Tests ────────────────────────────────────────────────────────

test.describe('live backend — subworkflow build from library', () => {
  test('navigating to a building subworkflow shows live messages', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // Ask the orchestrator to create a simple subworkflow.
    // The orchestrator calls create_subworkflow which spawns a background builder.
    await sendMessage(
      page,
      'Create a subworkflow called "Vitals Check" that has a start node, a node to measure blood pressure, and an end node. Connect them in order.',
    )

    // Wait for the parent workflow's response to complete — the orchestrator
    // should respond with confirmation that the subworkflow was created.
    await waitForResponseComplete(page, 180_000)

    // Navigate to the library
    await page.goto('/library')
    await page.waitForLoadState('networkidle')

    // Wait for the library to load and find the subworkflow.
    // It should appear as a card — possibly with "Building..." badge if still in progress.
    const subworkflowCard = page.locator('.library-card').filter({ hasText: /vitals/i })
    await expect(subworkflowCard).toBeVisible({ timeout: 30_000 })

    // Click the subworkflow card to navigate to it
    await subworkflowCard.click()

    // Wait for the WorkflowPage to load for the subworkflow
    await page.waitForFunction(
      () => !!document.querySelector('.workspace-revealed'),
      { timeout: 15_000 },
    )

    // The subworkflow should have chat content quickly — builder events have been
    // flowing into chatStore while the user was on the parent workflow (SPA nav
    // keeps the socket connected). Content should appear within seconds, not minutes.
    // Timeout is 15s to catch regressions where the page gets stuck on "Processing...".
    await page.waitForFunction(
      () => {
        const messages = document.querySelectorAll('.message.user, .message.assistant')
        const streaming = document.querySelector('.message.assistant.streaming')
        return messages.length > 0 || streaming !== null
      },
      { timeout: 15_000 },
    )

    // Verify we have meaningful chat content — at least one message with text
    const hasContent = await page.evaluate(() => {
      // Check finalized messages
      const msgs = document.querySelectorAll('.message .message-content')
      for (const m of msgs) {
        if ((m.textContent ?? '').length > 5) return true
      }
      // Check streaming bubble
      const streaming = document.querySelector('.message.assistant.streaming .message-content')
      if (streaming && (streaming.textContent ?? '').length > 5) return true
      // Check processing status (indicates active building)
      const status = document.querySelector('.processing-status')
      if (status) return true
      return false
    })
    expect(hasContent).toBe(true)

    // Wait for the build to fully complete — input should be re-enabled
    // and no streaming bubble should remain
    await waitForResponseComplete(page, 180_000)

    // After build completes, verify final state:
    // 1. At least one assistant message exists with real content
    const assistantMessages = page.locator('.message.assistant')
    const assistantCount = await assistantMessages.count()
    expect(assistantCount).toBeGreaterThanOrEqual(1)

    const assistantContent = await assistantMessages.first()
      .locator('.message-content').textContent()
    expect(assistantContent?.length).toBeGreaterThan(10)

    // 2. Canvas should have nodes from the subworkflow build
    const canvasNodes = page.locator('.flow-node')
    const nodeCount = await canvasNodes.count()
    expect(nodeCount).toBeGreaterThanOrEqual(1)
  })

  test('subworkflow chat shows the initial brief as a user message', async ({ page }) => {
    await registerUser(page)
    await openNewWorkflow(page)

    // Create a subworkflow — the orchestrator sends a brief to the builder
    await sendMessage(
      page,
      'Create a subworkflow called "BMI Calc" that calculates body mass index from weight and height inputs.',
    )
    await waitForResponseComplete(page, 180_000)

    // Navigate to library → find and open the subworkflow
    await page.goto('/library')
    await page.waitForLoadState('networkidle')
    const card = page.locator('.library-card').filter({ hasText: /bmi/i })
    await expect(card).toBeVisible({ timeout: 30_000 })
    await card.click()

    // Wait for workspace
    await page.waitForFunction(
      () => !!document.querySelector('.workspace-revealed'),
      { timeout: 15_000 },
    )

    // The first message in the chat should be a user message (the brief).
    // This verifies that build_user_message wasn't lost during SPA navigation
    // and that build_history recovery works for completed builds.
    const userMessages = page.locator('.message.user')
    await expect(userMessages.first()).toBeVisible({ timeout: 15_000 })

    const briefContent = await userMessages.first().locator('.message-content').textContent()
    // The brief should contain something about BMI (from the orchestrator's prompt)
    expect(briefContent?.toLowerCase()).toMatch(/bmi|body mass|weight|height/)
  })
})
