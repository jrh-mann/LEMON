/**
 * E2E tests for URL routing, header elements, home/landing state,
 * and page transitions.
 */
import { test, expect } from '@playwright/test'
import { mockAllAPIs, resetMsgCounter } from './helpers'

const WF_ID = 'wf_routing_0000000000000000000000000'

test.describe('routing', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('root URL redirects to /workflow', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/workflow/)
  })

  test('unknown path redirects to /workflow', async ({ page }) => {
    await page.goto('/some/random/path')
    await expect(page).toHaveURL(/\/workflow/)
  })

  test('/workflow without ID shows home landing state', async ({ page }) => {
    await page.goto('/workflow')

    // Home floating view should be visible
    await expect(page.locator('.home-floating')).toBeVisible()
    await expect(page.locator('.home-greeting')).toBeVisible()

    // Greeting text
    await expect(page.locator('.greeting-title')).toContainText('Where should we start')
    await expect(page.locator('.greeting-subtitle')).toContainText('Hi there')
  })

  test('home page has chat input bar', async ({ page }) => {
    await page.goto('/workflow')

    await expect(page.locator('.home-chat-input')).toBeVisible()
    await expect(page.locator('.home-chat-input')).toHaveAttribute('placeholder', /Describe a workflow/)
  })

  test('home page has action chips', async ({ page }) => {
    await page.goto('/workflow')

    await expect(page.locator('.home-chip')).toHaveCount(3)

    const chipTexts = await page.locator('.home-chip').allTextContents()
    expect(chipTexts.some(t => t.includes('Browse Library'))).toBe(true)
  })

  test('/workflow/:id shows workspace with canvas', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Test Workflow',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
      },
    })
    await page.goto(`/workflow/${WF_ID}`)

    // Workspace should be visible — use .app-layout.workspace-revealed to avoid
    // matching the chat-dock which also gets this class
    await expect(page.locator('.app-layout.workspace-revealed')).toBeVisible()
    await expect(page.locator('#flowchartCanvas')).toBeVisible()
  })

  test('/library renders library page', async ({ page }) => {
    await page.goto('/library')

    await expect(page.locator('.library-page')).toBeVisible()
    await expect(page.locator('.library-tab')).toHaveCount(3)
  })
})

test.describe('header', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Header Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
      },
    })
  })

  test('header shows LEMON logo', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    await expect(page.locator('.app-header')).toBeVisible()
    await expect(page.locator('.logo-mark')).toContainText('L')
    await expect(page.locator('.logo-text')).toContainText('LEMON')
  })

  test('header has all action buttons', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    const actions = page.locator('.header-actions')
    await expect(actions.locator('text=Browse Library')).toBeVisible()
    await expect(actions.locator('text=Save')).toBeVisible()
    await expect(actions.locator('text=Export')).toBeVisible()
    await expect(actions.locator('text=Sign out')).toBeVisible()
  })

  test('Browse Library button navigates to /library', async ({ page }) => {
    await page.goto(`/workflow/${WF_ID}`)

    await page.locator('.header-actions >> text=Browse Library').click()
    await expect(page).toHaveURL(/\/library/)
  })

  test('header is present on library page', async ({ page }) => {
    await page.goto('/library')

    // Library page has its own header, not the app-header
    await expect(page.locator('.library-header')).toBeVisible()
  })

  test('library back button navigates to workflow', async ({ page }) => {
    await page.goto('/library')

    await page.locator('.library-back-btn').click()
    await expect(page).toHaveURL(/\/workflow/)
  })
})

test.describe('error display', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('error toast shows when workflow load fails', async ({ page }) => {
    // Override API to return 404 for workflow detail
    await page.route(/(?<!src)\/api\/workflows\/wf_/, (route) =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Workflow not found' }),
      }),
    )
    await page.goto(`/workflow/${WF_ID}`)

    // Error toast should appear
    await expect(page.locator('.error-toast')).toBeVisible({ timeout: 5000 })
  })
})
