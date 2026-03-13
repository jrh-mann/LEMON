/**
 * E2E tests for cross-page navigation and subworkflow display.
 *
 * Verifies that:
 * - Chat messages persist when navigating to Library and back
 * - Library page renders workflow cards from API
 * - Clicking a library card navigates to the workflow page
 * - Subprocess nodes render with the double-border visual
 * - Subworkflow "Building..." badge shows on library cards
 * - Messages persist across workflow-to-workflow navigation
 */
import { test, expect } from '@playwright/test'
import {
  mockAllAPIs, buildChatStorage, seedAndLoad,
  msg, tc, resetMsgCounter,
  type WorkflowSummaryPayload, type NodePayload, type EdgePayload,
} from './helpers'

const WF_MAIN = 'wf_main_00000000000000000000000000'
const WF_SUB  = 'wf_sub_000000000000000000000000000'

// A workflow with a subprocess node pointing to WF_SUB
const MAIN_NODES: NodePayload[] = [
  { id: 'n1', type: 'start', label: 'Start', x: 100, y: 200, color: 'green' },
  { id: 'n2', type: 'process', label: 'Check Input', x: 300, y: 200, color: 'teal' },
  { id: 'n3', type: 'subprocess', label: 'Run Triage', x: 500, y: 200, color: 'rose',
    subworkflow_id: WF_SUB, input_mapping: { age: 'patient_age' }, output_variable: 'triage_result' },
  { id: 'n4', type: 'end', label: 'Output', x: 700, y: 200, color: 'amber' },
]
const MAIN_EDGES: EdgePayload[] = [
  { from: 'n1', to: 'n2', label: '' },
  { from: 'n2', to: 'n3', label: '' },
  { from: 'n3', to: 'n4', label: '' },
]

// Library entries
const LIBRARY_WORKFLOWS: WorkflowSummaryPayload[] = [
  {
    id: WF_MAIN, name: 'Patient Triage', description: 'Main triage workflow',
    domain: 'Healthcare', tags: ['triage', 'emergency'], is_validated: true,
    validation_score: 95, validation_count: 3, confidence: 'high',
    input_names: ['patient_age'], output_values: ['triage_result'],
    created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T12:00:00Z',
  },
  {
    id: WF_SUB, name: 'Triage Sub-Protocol', description: 'Sub-workflow for triage logic',
    domain: 'Healthcare', tags: ['triage'], is_validated: false,
    validation_score: 0, validation_count: 0, confidence: 'low',
    input_names: ['age'], output_values: ['priority'],
    created_at: '2024-01-02T00:00:00Z', updated_at: '2024-01-02T06:00:00Z',
    building: true,  // Currently being built by background builder
  },
]

test.describe('navigation & subworkflows', () => {
  test.beforeEach(async () => {
    resetMsgCounter()
  })

  test('chat messages persist after navigating to Library and back', async ({ page }) => {
    // Seed chat with messages for the main workflow
    const messages = [
      msg('user', 'build a triage workflow'),
      msg('assistant', 'Done! Created Patient Triage.', [
        tc('add_node', { label: 'Start' }),
        tc('add_node', { label: 'Check Input' }),
        tc('create_subworkflow', { name: 'Triage Sub-Protocol' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
      ]),
    ]

    await mockAllAPIs(page, {
      workflowsList: LIBRARY_WORKFLOWS,
      workflowDetail: {
        id: WF_MAIN, name: 'Patient Triage',
        nodes: MAIN_NODES, edges: MAIN_EDGES, variables: [],
      },
    })
    await seedAndLoad(page, WF_MAIN, buildChatStorage(WF_MAIN, messages))

    // Verify messages are rendered
    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.tool-call-summary')).toContainText('Tools (4)')

    // Navigate to Library — use the header button specifically (not the home chip)
    await page.locator('.header-actions >> text=Browse Library').click()
    await expect(page).toHaveURL(/\/library/)
    await expect(page.locator('.library-page')).toBeVisible()

    // Navigate back to the workflow
    await page.locator('.library-back-btn').click()
    // Wait for workflow page to load — the chat should still be there
    await page.goto(`/workflow/${WF_MAIN}`)

    // Messages should survive the navigation round-trip
    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.tool-call-summary')).toContainText('Tools (4)')
    const toolNames = await page.locator('.tool-name').allTextContents()
    expect(toolNames).toContain('create_subworkflow')
  })

  test('library page renders workflow cards from API', async () => {
    await mockAllAPIs(page, { workflowsList: LIBRARY_WORKFLOWS })
    await page.goto('/library')

    // Should show the "My Workflows" tab active by default
    await expect(page.locator('.library-tab.active')).toContainText('My Workflows')

    // Should render both workflow cards
    await expect(page.locator('.library-card')).toHaveCount(2)

    // Check card names (note: "Building..." badge is inside the <h3>)
    const cardNames = await page.locator('.library-card-name').allTextContents()
    expect(cardNames.some(n => n.includes('Patient Triage'))).toBe(true)
    expect(cardNames.some(n => n.includes('Triage Sub-Protocol'))).toBe(true)
  })

  test('subworkflow building badge shows on library card', async ({ page }) => {
    await mockAllAPIs(page, { workflowsList: LIBRARY_WORKFLOWS })
    await page.goto('/library')

    // The sub-workflow card should show "Building..." badge
    await expect(page.locator('.library-card-building')).toHaveCount(1)
    await expect(page.locator('.library-card-building')).toContainText('Building')
  })

  test('validated badge shows on validated workflow card', async ({ page }) => {
    await mockAllAPIs(page, { workflowsList: LIBRARY_WORKFLOWS })
    await page.goto('/library')

    // The main workflow is validated — should show the validated indicator
    await expect(page.locator('.library-card-validated')).toHaveCount(1)
  })

  test('library search filters workflow cards', async ({ page }) => {
    await mockAllAPIs(page, { workflowsList: LIBRARY_WORKFLOWS })
    await page.goto('/library')

    await expect(page.locator('.library-card')).toHaveCount(2)

    // Type a search term that matches only one workflow
    await page.locator('.library-search input').fill('Sub-Protocol')
    await expect(page.locator('.library-card')).toHaveCount(1)
    await expect(page.locator('.library-card-name')).toContainText('Triage Sub-Protocol')

    // Clear search — both cards should reappear
    await page.locator('.library-search input').fill('')
    await expect(page.locator('.library-card')).toHaveCount(2)
  })

  test('clicking library card navigates to workflow page', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowsList: LIBRARY_WORKFLOWS,
      workflowDetail: {
        id: WF_MAIN, name: 'Patient Triage',
        nodes: MAIN_NODES, edges: MAIN_EDGES, variables: [],
      },
    })
    await page.goto('/library')

    // Click the "Patient Triage" card
    await page.locator('.library-card-name', { hasText: 'Patient Triage' }).click()

    // Should navigate to the workflow page
    await expect(page).toHaveURL(new RegExp(`/workflow/${WF_MAIN}`))
  })

  test('subprocess node renders with double border on canvas', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_MAIN, name: 'Patient Triage',
        nodes: MAIN_NODES, edges: MAIN_EDGES, variables: [],
      },
    })
    await page.goto(`/workflow/${WF_MAIN}`)

    // Wait for the SVG canvas to render nodes
    await expect(page.locator('#flowchartCanvas')).toBeVisible()
    await expect(page.locator('#nodeLayer')).toBeVisible()

    // Should have 4 nodes in the node layer
    await expect(page.locator('.flow-node')).toHaveCount(4)

    // Exactly one subprocess node
    await expect(page.locator('.flow-node.subprocess')).toHaveCount(1)

    // The subprocess node should have a label "Run Triage"
    const subprocText = await page.locator('.flow-node.subprocess text').textContent()
    expect(subprocText).toContain('Run Triage')
  })

  test('canvas renders edges between nodes', async ({ page }) => {
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_MAIN, name: 'Patient Triage',
        nodes: MAIN_NODES, edges: MAIN_EDGES, variables: [],
      },
    })
    await page.goto(`/workflow/${WF_MAIN}`)

    await expect(page.locator('#flowchartCanvas')).toBeVisible()

    // Should have 3 edges (n1→n2, n2→n3, n3→n4)
    await expect(page.locator('.flow-edge')).toHaveCount(3)
  })

  test('messages for different workflows are isolated', async ({ page }) => {
    // Seed chat messages for TWO different workflows
    const mainMessages = [
      msg('user', 'main workflow message'),
      msg('assistant', 'main response', [tc('add_node', { label: 'Main Node' })]),
    ]
    const subMessages = [
      msg('user', 'sub workflow message'),
      msg('assistant', 'sub response', [tc('add_node', { label: 'Sub Node' })]),
    ]

    // Build localStorage with both conversations
    const payload = {
      state: {
        activeWorkflowId: WF_MAIN,
        pendingQuestions: [],
        conversations: {
          [WF_MAIN]: {
            messages: mainMessages, conversationId: 'conv-main',
            isStreaming: false, streamingContent: '', _inThinkingBlock: false,
            processingStatus: null, currentTaskId: null, contextUsagePct: 0,
          },
          [WF_SUB]: {
            messages: subMessages, conversationId: 'conv-sub',
            isStreaming: false, streamingContent: '', _inThinkingBlock: false,
            processingStatus: null, currentTaskId: null, contextUsagePct: 0,
          },
        },
      },
      version: 0,
    }

    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_MAIN, name: 'Patient Triage',
        nodes: MAIN_NODES, edges: MAIN_EDGES, variables: [],
      },
    })
    await seedAndLoad(page, WF_MAIN, JSON.stringify(payload))

    // Main workflow should show its own messages
    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.message.user .message-content')).toContainText('main workflow message')

    // Navigate to the sub-workflow
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_SUB, name: 'Triage Sub-Protocol',
        nodes: [], edges: [], variables: [],
      },
    })
    await page.goto(`/workflow/${WF_SUB}`)

    // Sub-workflow should show its own messages, not main's
    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.message.user .message-content')).toContainText('sub workflow message')
  })
})
