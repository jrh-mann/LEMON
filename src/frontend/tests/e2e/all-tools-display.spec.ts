/**
 * E2E test that verifies ALL 23 LLM tools render correctly in the chat UI.
 *
 * Seeds a realistic multi-turn conversation where the assistant uses every
 * tool in a logical build sequence. Verifies:
 * - Every tool name appears in the chat
 * - Tool calls render with correct CSS classes
 * - Failed tools show the failure badge
 * - Collapsed disclosure works for messages with >3 tools
 * - All tool names survive page refresh
 *
 * Optimal tool sequence (mirrors a real workflow build):
 *   Turn 1: Image analysis & planning
 *   Turn 2: Variables & initial structure
 *   Turn 3: Node building & connections
 *   Turn 4: Subworkflow creation
 *   Turn 5: Output, validation, execution
 *   Turn 6: Library operations & error handling
 */
import { test, expect } from '@playwright/test'
import {
  mockAllAPIs, buildChatStorage, seedAndLoad,
  msg, tc, resetMsgCounter,
} from './helpers'

const WF_ID = 'wf_alltools_000000000000000000000000'

// All 23 tools the LLM can call, grouped into a realistic conversation
const ALL_TOOL_NAMES = [
  'view_image',
  'extract_guidance',
  'update_plan',
  'get_current_workflow',
  'add_workflow_variable',
  'list_workflow_variables',
  'modify_workflow_variable',
  'add_node',
  'modify_node',
  'add_connection',
  'highlight_node',
  'batch_edit_workflow',
  'ask_question',
  'create_subworkflow',
  'update_subworkflow',
  'delete_connection',
  'delete_node',
  'remove_workflow_variable',
  'set_workflow_output',
  'validate_workflow',
  'execute_workflow',
  'save_workflow_to_library',
  'list_workflows_in_library',
]

test.describe('all tools display', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('every tool name renders in the chat and survives refresh', async ({ page }) => {
    const messages = [
      // ── Turn 1: Image analysis & planning ──
      msg('user', 'Here is the flowchart image. Build this workflow.'),
      msg('assistant', 'Let me study the image and extract guidance.', [
        tc('view_image', { index: 0 }),
        tc('extract_guidance', { index: 0 }),
        tc('update_plan', { steps: ['Analyze image', 'Create variables', 'Build nodes'] }),
      ]),

      // ── Turn 2: Variables & read state ──
      msg('user', 'Looks good, proceed.'),
      msg('assistant', 'Setting up input variables.', [
        tc('get_current_workflow'),
        tc('add_workflow_variable', { name: 'patient_age', type: 'number', min: 0, max: 120 }),
        tc('add_workflow_variable', { name: 'is_emergency', type: 'bool' }),
        tc('list_workflow_variables'),
        tc('modify_workflow_variable', { name: 'patient_age', description: 'Patient age in years' }),
      ]),

      // ── Turn 3: Build nodes & connections ──
      msg('assistant', 'Building workflow structure.', [
        tc('add_node', { type: 'start', label: 'Start' }),
        tc('add_node', { type: 'decision', label: 'Age Check' }),
        tc('add_node', { type: 'process', label: 'Adult Path' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
        tc('add_connection', { from: 'n2', to: 'n3', label: 'true' }),
        tc('modify_node', { node_id: 'n2', condition: { input_id: 'var_age', comparator: 'gte', value: 18 } }),
        tc('highlight_node', { node_id: 'n2' }),
        tc('batch_edit_workflow', {
          add_nodes: [{ type: 'process', label: 'Pediatric Path' }],
          add_connections: [{ from: 'n2', to: 'temp_1', label: 'false' }],
        }),
      ]),

      // ── Turn 4: Subworkflow & question ──
      msg('assistant', 'I need to create a subworkflow for the triage protocol.', [
        tc('ask_question', { questions: ['What threshold for emergency triage?'] }),
      ]),
      msg('user', 'Use 65 as the age threshold.'),
      msg('assistant', 'Creating the subworkflow now.', [
        tc('create_subworkflow', { name: 'Triage Protocol', instructions: 'Build triage logic' }),
        tc('update_subworkflow', { workflow_id: 'wf_sub_1', instructions: 'Add emergency path' }),
      ]),

      // ── Turn 5: Cleanup, output, validate, execute ──
      msg('assistant', 'Cleaning up and finalizing.', [
        tc('delete_connection', { from: 'n2', to: 'n3' }),
        tc('delete_node', { node_id: 'n3' }),
        tc('remove_workflow_variable', { name: 'is_emergency' }),
        tc('set_workflow_output', { type: 'string', format: 'Triage result: {result}' }),
        tc('validate_workflow'),
        tc('execute_workflow', { inputs: { patient_age: 72 } }),
      ]),

      // ── Turn 6: Library operations ──
      msg('assistant', 'Saving to library.', [
        tc('save_workflow_to_library'),
        tc('list_workflows_in_library'),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    // Wait for all messages to render
    await expect(page.locator('.message')).toHaveCount(messages.length)

    // Collect all tool names displayed in the chat
    const displayedTools = await page.locator('.tool-name').allTextContents()

    // Every tool should appear at least once
    for (const toolName of ALL_TOOL_NAMES) {
      expect(displayedTools, `Tool "${toolName}" should appear in chat`).toContain(toolName)
    }

    // Verify the total count matches (23 unique tools, some used multiple times)
    const expectedTotal = messages.reduce((sum, m) => sum + m.tool_calls.length, 0)
    expect(displayedTools).toHaveLength(expectedTotal)

    // ── Refresh and verify all tools survive ──
    await page.reload()

    await expect(page.locator('.message')).toHaveCount(messages.length)

    const displayedToolsAfter = await page.locator('.tool-name').allTextContents()
    for (const toolName of ALL_TOOL_NAMES) {
      expect(displayedToolsAfter, `Tool "${toolName}" should survive refresh`).toContain(toolName)
    }
    expect(displayedToolsAfter).toHaveLength(expectedTotal)
  })

  test('messages with >3 tools use disclosure, ≤3 use inline', async ({ page }) => {
    const messages = [
      msg('user', 'test'),
      // 2 tools → inline (no disclosure)
      msg('assistant', 'Two tools.', [
        tc('get_current_workflow'),
        tc('validate_workflow'),
      ]),
      // 5 tools → disclosure (collapsed)
      msg('assistant', 'Five tools.', [
        tc('add_node', { label: 'A' }),
        tc('add_node', { label: 'B' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
        tc('highlight_node', { node_id: 'n1' }),
        tc('update_plan', { steps: ['Done'] }),
      ]),
      // 8 tools → disclosure
      msg('assistant', 'Eight tools.', [
        tc('add_workflow_variable', { name: 'x' }),
        tc('add_node', { label: 'C' }),
        tc('add_node', { label: 'D' }),
        tc('add_connection', { from: 'n3', to: 'n4' }),
        tc('modify_node', { node_id: 'n3' }),
        tc('batch_edit_workflow', {}),
        tc('validate_workflow'),
        tc('save_workflow_to_library'),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    // First assistant message (2 tools) → no disclosure, tools inline
    const firstAssistant = page.locator('.message.assistant').nth(0)
    await expect(firstAssistant.locator('.tool-call-disclosure')).toHaveCount(0)
    await expect(firstAssistant.locator('.tool-call')).toHaveCount(2)

    // Second assistant (5 tools) → disclosure with "Tools (5)"
    const secondAssistant = page.locator('.message.assistant').nth(1)
    await expect(secondAssistant.locator('.tool-call-disclosure')).toHaveCount(1)
    await expect(secondAssistant.locator('.tool-call-summary')).toContainText('Tools (5)')

    // Third assistant (8 tools) → disclosure with "Tools (8)"
    const thirdAssistant = page.locator('.message.assistant').nth(2)
    await expect(thirdAssistant.locator('.tool-call-disclosure')).toHaveCount(1)
    await expect(thirdAssistant.locator('.tool-call-summary')).toContainText('Tools (8)')
  })

  test('mixed success/failure tools display correctly', async ({ page }) => {
    const messages = [
      msg('user', 'build and validate'),
      msg('assistant', 'Built but validation found issues.', [
        tc('add_node', { label: 'Start' }, true),
        tc('add_connection', { from: 'n1', to: 'n2' }, true),
        tc('validate_workflow', {}, false),  // Failed
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    // 2 successful + 1 failed
    await expect(page.locator('.tool-call')).toHaveCount(3)
    await expect(page.locator('.tool-call.failed')).toHaveCount(1)
    await expect(page.locator('.tool-call.failed .tool-name')).toContainText('validate_workflow')

    // Non-failed tools should NOT have the .failed class
    const nonFailed = page.locator('.tool-call:not(.failed)')
    await expect(nonFailed).toHaveCount(2)
  })

  test('tool calls inside disclosure are visible when expanded', async ({ page }) => {
    const messages = [
      msg('user', 'big operation'),
      msg('assistant', 'Did many things.', [
        tc('get_current_workflow'),
        tc('add_node', { label: 'A' }),
        tc('add_node', { label: 'B' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
        tc('validate_workflow'),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    // Disclosure should be collapsed by default — tools hidden inside <details>
    const disclosure = page.locator('.tool-call-disclosure')
    await expect(disclosure).toHaveCount(1)

    // Click to expand the disclosure
    await page.locator('.tool-call-summary').click()

    // Now all 5 tools should be visible
    await expect(page.locator('.tool-call')).toHaveCount(5)
    const names = await page.locator('.tool-name').allTextContents()
    expect(names).toEqual(['get_current_workflow', 'add_node', 'add_node', 'add_connection', 'validate_workflow'])
  })
})
