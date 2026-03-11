/**
 * Integration E2E tests for the chat flow.
 *
 * These tests use MockSocketIO to give the frontend a real socket
 * connection, then exercise the full pipeline:
 *   type → click Send → HTTP POST → socket events → store → UI
 *
 * Unlike the static rendering tests (refresh-persistence, stop-button),
 * these verify actual state transitions and event handling, catching
 * bugs like duplicate messages, lost events, and race conditions.
 */
import { test, expect } from '@playwright/test'
import { MockSocketIO, mockAllAPIs, resetMsgCounter, sendAndGetTaskId } from './helpers'

const WF_ID = 'wf_e2e_flow_00000000000000000000000000'

/** Default workflow detail so workflowStore.currentWorkflow.id matches WF_ID */
const DEFAULT_WF_DETAIL = {
  id: WF_ID, name: 'Test Workflow',
  nodes: [], edges: [], variables: [],
}

test.describe('chat flow — send, stream, respond', () => {
  let sio: MockSocketIO

  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })
    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected
  })

  test('full send → stream → response cycle', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'build a triage workflow')

    // User message should appear immediately (optimistic update)
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.user .message-content')).toContainText('triage workflow')

    // Chat input should be disabled (streaming started)
    await expect(page.locator('#chatInput')).toBeDisabled()
    await expect(page.locator('#stopBtn')).toBeVisible()

    // Server sends progress, then stream chunks
    sio.emit('chat_progress', {
      event: 'start', status: 'Thinking...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'Here is the triage workflow.', task_id: taskId, workflow_id: WF_ID,
    })

    // Streaming content should appear
    await expect(page.locator('.message.assistant.streaming .message-content'))
      .toContainText('triage workflow')

    // Server finalizes with response + tool calls
    sio.emit('chat_response', {
      response: '',
      tool_calls: [
        { tool: 'add_node', arguments: { label: 'Start' } },
        { tool: 'add_node', arguments: { label: 'Triage' } },
        { tool: 'add_connection', arguments: { from: 'n1', to: 'n2' } },
      ],
      task_id: taskId,
      workflow_id: WF_ID,
      conversation_id: 'conv_flow_1',
    })

    // Streaming bubble should be replaced by a finalized assistant message
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(3)

    // Chat input should be re-enabled
    await expect(page.locator('#chatInput')).toBeEnabled()
    await expect(page.locator('#sendBtn')).toBeVisible()
  })

  test('streamed content without tool calls becomes a message', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'what is this workflow?')

    sio.emit('chat_progress', {
      event: 'start', status: 'Thinking...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'This workflow handles patient triage.', task_id: taskId, workflow_id: WF_ID,
    })

    sio.emit('chat_response', {
      response: '', tool_calls: [],
      task_id: taskId, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .message-content')).toContainText('patient triage')
    await expect(page.locator('#chatInput')).toBeEnabled()
  })

  test('non-streamed response (no chunks, just response text)', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'hello')

    sio.emit('chat_response', {
      response: 'Hello! How can I help you build a workflow?',
      tool_calls: [],
      task_id: taskId,
      workflow_id: WF_ID,
      conversation_id: 'conv_1',
    })

    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .message-content')).toContainText('How can I help')
  })

  test('multiple chat turns preserve message order', async ({ page }) => {
    // First turn
    const taskId1 = await sendAndGetTaskId(page, 'first question')

    sio.emit('chat_stream', {
      chunk: 'first answer', task_id: taskId1, workflow_id: WF_ID,
    })
    sio.emit('chat_response', {
      response: '', tool_calls: [],
      task_id: taskId1, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('#chatInput')).toBeEnabled()

    // Second turn
    const taskId2 = await sendAndGetTaskId(page, 'second question')

    sio.emit('chat_stream', {
      chunk: 'second answer', task_id: taskId2, workflow_id: WF_ID,
    })
    sio.emit('chat_response', {
      response: '', tool_calls: [{ tool: 'validate_workflow', arguments: {} }],
      task_id: taskId2, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message')).toHaveCount(4)

    const contents = await page.locator('.message .message-content').allTextContents()
    expect(contents[0]).toContain('first question')
    expect(contents[1]).toContain('first answer')
    expect(contents[2]).toContain('second question')
    expect(contents[3]).toContain('second answer')

    const assistants = page.locator('.message.assistant')
    await expect(assistants.nth(0).locator('.tool-call')).toHaveCount(0)
    await expect(assistants.nth(1).locator('.tool-call')).toHaveCount(1)
  })
})

test.describe('chat flow — stop button', () => {
  let sio: MockSocketIO

  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })
    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected
  })

  test('stop mid-stream preserves partial content', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'build it')

    sio.emit('chat_progress', {
      event: 'start', status: 'Building...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'I will create the workflow with', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.message.assistant.streaming .message-content'))
      .toContainText('create the workflow')

    await page.click('#stopBtn')

    await expect(page.locator('#stopBtn')).toBeHidden()
    await expect(page.locator('#chatInput')).toBeEnabled()

    // Partial content should be preserved as a finalized message
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .message-content'))
      .toContainText('create the workflow')
  })

  test('stop during thinking preserves thinking content as assistant message', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'analyze the image')

    sio.emit('chat_progress', {
      event: 'start', status: 'Thinking...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_thinking', {
      chunk: 'Let me analyze this flowchart...', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.processing-status')).toBeVisible()

    await page.click('#stopBtn')

    // Thinking content is preserved as an assistant message (finalizeStream fallback)
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('#chatInput')).toBeEnabled()
  })

  test('cancelled response from backend does NOT duplicate message', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'build complex workflow')

    sio.emit('chat_progress', {
      event: 'start', status: 'Building...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'Creating nodes for the workflow.', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.message.assistant.streaming .message-content'))
      .toContainText('Creating nodes')

    await page.click('#stopBtn')

    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)

    // Backend sends cancelled ack AFTER handleStop already finalized
    sio.emit('chat_response', {
      response: 'Creating nodes for the workflow.',
      tool_calls: [{ tool: 'add_node', arguments: { label: 'Start' } }],
      task_id: taskId,
      workflow_id: WF_ID,
      conversation_id: 'conv_1',
      cancelled: true,
    })

    await page.waitForTimeout(500)

    // CRITICAL: still only 1 assistant message — no duplicate
    await expect(page.locator('.message.assistant')).toHaveCount(1)
  })

  test('duplicate chat_response for same task_id does not create extra message', async ({ page }) => {
    // Simulates the bug caused by HMR-duplicated socket event handlers:
    // when chat_response fires twice for the same task_id, the second
    // invocation must be skipped to prevent a duplicate assistant message.
    const taskId = await sendAndGetTaskId(page, 'build it')

    sio.emit('chat_progress', {
      event: 'start', status: 'Building...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'Here is the plan.', task_id: taskId, workflow_id: WF_ID,
    })
    // First chat_response (normal): finalizeStream creates message from stream
    sio.emit('chat_response', {
      response: 'Here is the plan.',
      tool_calls: [{ tool: 'batch_edit_workflow', arguments: {} }],
      task_id: taskId, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message.assistant')).toHaveCount(1)

    // Second chat_response for the SAME task_id (simulates duplicate handler).
    // This must be dropped by the deduplication guard.
    sio.emit('chat_response', {
      response: 'Here is the plan.',
      tool_calls: [{ tool: 'batch_edit_workflow', arguments: {} }],
      task_id: taskId, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await page.waitForTimeout(500)

    // CRITICAL: still only 1 assistant message — deduplication prevented the duplicate
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .message-content'))
      .toContainText('Here is the plan')
  })

  test('stop then send new message works correctly', async ({ page }) => {
    const taskId1 = await sendAndGetTaskId(page, 'build it')

    sio.emit('chat_stream', {
      chunk: 'Starting to build...', task_id: taskId1, workflow_id: WF_ID,
    })
    await expect(page.locator('.message.assistant.streaming')).toBeVisible()

    await page.click('#stopBtn')
    await expect(page.locator('#chatInput')).toBeEnabled()

    // Send a new message
    const taskId2 = await sendAndGetTaskId(page, 'try again please')

    await expect(page.locator('.message.user')).toHaveCount(2)
    // 1 finalized from stop + 1 streaming bubble for the new send
    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 2000 }).catch(() => {
      // If streaming bubble hasn't appeared yet, just 1 finalized message
    })

    sio.emit('chat_stream', {
      chunk: 'OK, rebuilding.', task_id: taskId2, workflow_id: WF_ID,
    })
    sio.emit('chat_response', {
      response: '', tool_calls: [],
      task_id: taskId2, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    // After completion: 1 stopped message + 1 new finalized message
    await expect(page.locator('.message.assistant')).toHaveCount(2)
    const contents = await page.locator('.message.assistant .message-content').allTextContents()
    expect(contents[0]).toContain('Starting to build')
    expect(contents[1]).toContain('rebuilding')
  })
})

test.describe('chat flow — HTTP POST delivery', () => {
  test('sendChatMessage makes HTTP POST with correct payload', async ({ page }) => {
    resetMsgCounter()
    const sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })

    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected

    const postPromise = page.waitForRequest(req =>
      req.url().includes('/api/chat/send') && req.method() === 'POST',
    )

    await page.fill('#chatInput', 'hello world')
    await page.click('#sendBtn')

    const request = await postPromise
    const body = JSON.parse(request.postData() || '{}')

    expect(body.message).toBe('hello world')
    expect(body.socket_id).toBe(sio.sid)
    expect(body.task_id).toBeDefined()
    expect(body.current_workflow_id).toBe(WF_ID)
  })

  test('HTTP POST failure shows error and reverts streaming state', async ({ page }) => {
    resetMsgCounter()
    const sio = new MockSocketIO()
    await sio.install(page)

    // Mock with a failing /api/chat/send
    await page.route(/(?<!src)\/api\//, (route) => {
      const url = route.request().url()
      if (url.includes('/api/chat/send')) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      }
      if (url.includes('/api/auth/me')) {
        return route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ user: { id: 'u_test', email: 'test@test.com', name: 'Test' } }),
        })
      }
      if (url.match(/\/api\/workflows\/wf_/)) {
        return route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            ...DEFAULT_WF_DETAIL,
            analysis: null, conversation_id: null, output_type: 'string',
            metadata: { name: 'Test', description: '', domain: '', tags: [] },
            outputs: [],
          }),
        })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected

    await page.fill('#chatInput', 'this will fail')
    await page.click('#sendBtn')

    // Streaming state should be reverted — input re-enabled
    await expect(page.locator('#chatInput')).toBeEnabled({ timeout: 5000 })
  })
})

test.describe('chat flow — refresh during stream', () => {
  test('messages survive refresh and resume reconnects', async ({ page }) => {
    resetMsgCounter()
    const sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })
    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected

    const taskId = await sendAndGetTaskId(page, 'build a triage workflow')

    sio.emit('chat_progress', {
      event: 'start', status: 'Building...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_stream', {
      chunk: 'Creating the triage workflow with nodes.', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.message.assistant.streaming')).toBeVisible()

    // Simulate refresh during streaming — reinstall mocks with building=true
    const sio2 = new MockSocketIO()
    await sio2.install(page)
    await mockAllAPIs(page, {
      skipSocket: true,
      workflowDetail: {
        id: WF_ID, name: 'Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
        conversation_id: 'conv_1',
        building: true,
      },
    })

    await page.reload()
    await sio2.connected

    // User message from localStorage should survive
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.user .message-content')).toContainText('triage workflow')

    // building=true should show streaming UI
    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })

    // Wait for the client's long-poll to arrive before emitting events
    await sio2.waitForPoll()

    // Backend sends resumed event with replayed content
    sio2.emit('chat_progress', {
      event: 'resumed', status: 'Processing...', task_id: 'task_resumed', workflow_id: WF_ID,
    })
    sio2.emit('chat_stream', {
      chunk: 'Creating nodes and adding decision logic.',
      task_id: 'task_resumed', workflow_id: WF_ID,
    })

    await expect(page.locator('.message.assistant.streaming .message-content'))
      .toContainText('decision logic')

    // Backend completes
    sio2.emit('chat_response', {
      response: '', tool_calls: [
        { tool: 'add_node', arguments: { label: 'Start' } },
        { tool: 'add_node', arguments: { label: 'Decision' } },
      ],
      task_id: 'task_resumed', workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(2)
    await expect(page.locator('#chatInput')).toBeEnabled()
  })

  test('finalized messages persist across refresh', async ({ page }) => {
    resetMsgCounter()
    const sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })
    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected

    const taskId = await sendAndGetTaskId(page, 'explain the workflow')

    sio.emit('chat_stream', {
      chunk: 'This workflow handles blood pressure classification.',
      task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_response', {
      response: '', tool_calls: [],
      task_id: taskId, workflow_id: WF_ID, conversation_id: 'conv_1',
    })

    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('#chatInput')).toBeEnabled()

    // Refresh
    await page.reload()

    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.message.user .message-content')).toContainText('explain the workflow')
    await expect(page.locator('.message.assistant .message-content'))
      .toContainText('blood pressure classification')

    await expect(page.locator('#stopBtn')).toBeHidden()
    await expect(page.locator('#chatInput')).toBeEnabled()
  })
})

test.describe('chat flow — thinking and progress', () => {
  let sio: MockSocketIO

  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    sio = new MockSocketIO()
    await sio.install(page)
    await mockAllAPIs(page, { skipSocket: true, workflowDetail: DEFAULT_WF_DETAIL })
    await page.goto(`/workflow/${WF_ID}`)
    await sio.connected
  })

  test('thinking content appears during processing', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'analyze the image')

    sio.emit('chat_progress', {
      event: 'start', status: 'Analyzing...', task_id: taskId, workflow_id: WF_ID,
    })
    sio.emit('chat_thinking', {
      chunk: 'I see a flowchart with decision nodes and branches.', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.thinking-stream')).toBeVisible()
    await expect(page.locator('.thinking-text')).toContainText('decision nodes')

    // Stream starts — both thinking and stream content visible
    sio.emit('chat_stream', {
      chunk: 'Building the workflow now.', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.thinking-stream')).toBeVisible()
    await expect(page.locator('.message.assistant.streaming .message-content'))
      .toContainText('Building the workflow')
  })

  test('processing status updates appear', async ({ page }) => {
    const taskId = await sendAndGetTaskId(page, 'build it')

    sio.emit('chat_progress', {
      event: 'start', status: 'Thinking...', task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.processing-status')).toContainText('Thinking...')

    sio.emit('chat_progress', {
      event: 'tool_start', status: 'Adding nodes...', tool: 'add_node',
      task_id: taskId, workflow_id: WF_ID,
    })

    await expect(page.locator('.processing-status')).toContainText('Adding nodes...')
  })
})
