/**
 * E2E tests for the stop button — real backend, no mocks.
 *
 * Requires both servers running with LEMON_ALLOW_REGISTRATION=true:
 *   LEMON_ALLOW_REGISTRATION=true bash scripts/dev.sh start
 *
 * Verifies:
 * - Stop cancels the backend task and re-enables input
 * - Partial content is preserved
 * - Agent retains conversation context after stop
 */
import { test, expect, type Page } from '@playwright/test'

test.setTimeout(120_000)
test.use({ viewport: { width: 1280, height: 900 } })

// ── Helpers ──────────────────────────────────────────────────────

async function registerUser(page: Page) {
  const email = `e2e_stop_${Date.now()}_${Math.random().toString(36).slice(2, 6)}@test.local`
  const res = await page.request.post('http://localhost:5173/api/auth/register', {
    data: { email, name: 'E2E Stop', password: 'TestPassword123!', remember: false },
  })
  if (!res.ok()) throw new Error(`Registration failed (${res.status()})`)
}

async function openNewWorkflow(page: Page) {
  await page.goto('/workflow')
  await page.waitForLoadState('networkidle')
  const newBtn = page.locator('.home-content button, .home-content a')
    .filter({ hasText: /new|build|start/i }).first()
  await newBtn.waitFor({ timeout: 15_000 })
  await newBtn.click()
  await page.waitForFunction(
    () => !!document.querySelector('.workspace-revealed'),
    { timeout: 15_000 },
  )
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#chatInput') as HTMLTextAreaElement | null
      return el && !el.disabled
    },
    { timeout: 15_000 },
  )
}

async function sendMessage(page: Page, text: string) {
  const postPromise = page.waitForRequest(
    req => req.url().includes('/api/chat/send') && req.method() === 'POST',
  )
  await page.fill('#chatInput', text)
  await page.click('#sendBtn')
  await postPromise
}

/** Poll zustand store for streaming content or finalized messages. */
async function waitForStreamingContent(page: Page, timeout = 60_000): Promise<boolean> {
  return page.waitForFunction(
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
    { timeout },
  ).then(() => true).catch(() => false)
}

// ── Tests ────────────────────────────────────────────────────────

test.describe('stop button — live backend', () => {
  test.beforeEach(async ({ page }) => {
    await test.step('register user', () => registerUser(page))
    await test.step('open new workflow', () => openNewWorkflow(page))
  })

  test('stop cancels task, preserves content, re-enables input', async ({ page }) => {
    await test.step('send message', () =>
      sendMessage(page, 'Add a start node labeled "Input" to the workflow. Do not explain, just do it.'),
    )

    await test.step('wait for streaming', () => waitForStreamingContent(page))

    const stopBtn = page.locator('#stopBtn')
    if (await stopBtn.isVisible()) {
      await test.step('click stop', async () => {
        const cancelPromise = page.waitForRequest(
          req => req.url().includes('/api/chat/cancel') && req.method() === 'POST',
          { timeout: 5_000 },
        ).catch(() => null)
        await stopBtn.click()
        const cancelReq = await cancelPromise
        expect(cancelReq).not.toBeNull()
        await expect(stopBtn).toBeHidden({ timeout: 10_000 })
      })
    }

    await test.step('verify UI state', async () => {
      await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 30_000 })
      await expect(page.locator('.message.user')).toHaveCount(1)
      const assistant = page.locator('.message.assistant')
      await expect(assistant).toHaveCount(1, { timeout: 5_000 })
      const content = await assistant.first().locator('.message-content').textContent()
      expect(content?.length).toBeGreaterThan(0)
    })
  })

  test('agent retains context after stop', async ({ page }) => {
    await test.step('send GFR message', () =>
      // Short, direct instruction — minimal thinking needed
      sendMessage(page, 'Add a start node labeled "GFR Creatinine". Just add the node, nothing else.'),
    )

    await test.step('wait for streaming', () => waitForStreamingContent(page))

    await test.step('click stop', async () => {
      const stopBtn = page.locator('#stopBtn')
      if (await stopBtn.isVisible()) {
        await stopBtn.click()
        await expect(stopBtn).toBeHidden({ timeout: 10_000 })
      }
    })

    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 30_000 })

    await test.step('send follow-up', () =>
      // Ask what the first message was about — one word answer to minimize LLM time
      sendMessage(page, 'What keyword was in the node label I asked for? Reply with just that one word.'),
    )

    await test.step('check agent remembers', async () => {
      // Poll streaming + finalized content for the keyword — don't wait for full response
      const remembered = await page.waitForFunction(
        () => {
          const raw = localStorage.getItem('lemon-chat')
          if (!raw) return false
          try {
            const parsed = JSON.parse(raw)
            const wfId = parsed?.state?.activeWorkflowId
            const conv = parsed?.state?.conversations?.[wfId]
            if (!conv) return false
            const streaming = (conv.streamingContent ?? '').toLowerCase()
            const lastMsg = conv.messages?.[conv.messages.length - 1]
            const lastContent = (lastMsg?.role === 'assistant' ? lastMsg.content : '').toLowerCase()
            const text = streaming + ' ' + lastContent
            return /gfr|creatinine/.test(text)
          } catch { return false }
        },
        { timeout: 60_000 },
      ).then(() => true).catch(() => false)

      expect(remembered).toBe(true)
    })
  })

  test('stop during thinking does not leave empty message', async ({ page }) => {
    await test.step('send message', () =>
      sendMessage(page, 'Add a start node. Do not explain.'),
    )

    await test.step('wait for streaming indicator', async () => {
      await expect(
        page.locator('.message.assistant.streaming, .processing-status, .typing-indicator').first(),
      ).toBeVisible({ timeout: 30_000 })
    })

    await test.step('click stop immediately', async () => {
      const stopBtn = page.locator('#stopBtn')
      if (await stopBtn.isVisible()) await stopBtn.click()
    })

    await test.step('verify no empty bubble', async () => {
      await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 30_000 })
      const assistant = page.locator('.message.assistant')
      const count = await assistant.count()
      if (count > 0) {
        const content = await assistant.first().locator('.message-content').textContent()
        expect((content ?? '').trim().length).toBeGreaterThan(0)
      }
    })
  })
})
