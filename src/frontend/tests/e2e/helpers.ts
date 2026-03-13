/**
 * Shared E2E test helpers — API mocking, localStorage seeding, types.
 *
 * Two modes of testing:
 *
 * 1. **Static rendering tests** — seed localStorage, mock all APIs, verify
 *    that components render the seeded state correctly. Use buildChatStorage()
 *    + seedAndLoad(). No backend needed.
 *
 * 2. **Integration flow tests** — hit the real backend. Register a user,
 *    open a workflow, send messages via the chat input, and verify real
 *    SSE streaming responses arrive and update the UI.
 */
import type { Page } from '@playwright/test'

// ── Types ────────────────────────────────────────────────────────

/** Shape that zustand persist writes under localStorage key "lemon-chat" */
export interface PersistedChatState {
  state: {
    activeWorkflowId: string | null
    pendingQuestions: unknown[]
    conversations: Record<string, {
      messages: MessagePayload[]
      conversationId: string | null
      isStreaming: boolean
      streamingContent: string
      _inThinkingBlock: boolean
      processingStatus: string | null
      currentTaskId: string | null
      contextUsagePct: number
    }>
  }
  version: number
}

export interface MessagePayload {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  tool_calls: ToolCallPayload[]
}

export interface ToolCallPayload {
  tool: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown>
  success?: boolean
}

export interface NodePayload {
  id: string
  type: string
  label: string
  x: number
  y: number
  color: string
  subworkflow_id?: string
  input_mapping?: Record<string, string>
  output_variable?: string
  condition?: Record<string, unknown>
  output_type?: string
  output_template?: string
  output_value?: unknown
}

export interface EdgePayload {
  id?: string
  from: string
  to: string
  label: string
}

export interface VariablePayload {
  id: string
  name: string
  type: string
  source: string  // 'input' | 'subprocess' | 'calculated' | 'constant'
  description?: string
  range?: { min: number; max: number }
  enum_values?: string[]
  source_node_id?: string
  subworkflow_id?: string
  expression?: string
  depends_on?: string[]
  value?: unknown
}

export interface WorkflowSummaryPayload {
  id: string
  name: string
  description: string
  domain?: string
  tags: string[]
  is_validated: boolean
  validation_score: number
  validation_count: number
  confidence: string
  input_names: string[]
  output_values: string[]
  created_at: string
  updated_at: string
  building?: boolean
}

// ── API Mocking ──────────────────────────────────────────────────

export interface MockAPIOverrides {
  /** Workflows list endpoint: GET /api/workflows */
  workflowsList?: WorkflowSummaryPayload[]
  /** Specific workflow detail: GET /api/workflows/:id */
  workflowDetail?: {
    id: string
    name: string
    nodes: NodePayload[]
    edges: EdgePayload[]
    variables: VariablePayload[]
    conversation_id?: string | null
    building?: boolean
    output_type?: string
  }
  /** Conversation history: GET /api/chat/:id */
  chatMessages?: MessagePayload[]
  /** Callback for POST /api/chat/send — receives the parsed body.
   *  Defaults to returning {ok: true}. */
  onChatSend?: (body: Record<string, unknown>) => void
}

/**
 * Set up route interceptions to mock all API calls.
 * Prevents auth redirect and lets the app render without a running backend.
 */
export async function mockAllAPIs(page: Page, overrides?: MockAPIOverrides) {
  // Match real API calls but not Vite module imports like /src/api/client.ts
  await page.route(/(?<!src)\/api\//, (route) => {
    const url = route.request().url()
    const method = route.request().method()

    // Auth endpoint — return a fake user
    if (url.includes('/api/auth/me')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: { id: 'u_test', email: 'test@test.com', name: 'Test' } }),
      })
    }

    // Chat send endpoint: POST /api/chat/send
    // Must come BEFORE the /api/chat/ catch-all.
    if (url.includes('/api/chat/send') && method === 'POST') {
      // Notify the test callback if provided
      if (overrides?.onChatSend) {
        route.request().text().then(body => {
          try { overrides.onChatSend!(JSON.parse(body)) } catch { /* ignore */ }
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      })
    }

    // Workflow list endpoint: GET /api/workflows (no trailing path)
    if (url.match(/\/api\/workflows\/?$/) || url.match(/\/api\/workflows\?/)) {
      const list = overrides?.workflowsList ?? []
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ workflows: list, count: list.length }),
      })
    }

    // Workflow detail: GET /api/workflows/:id
    if (url.match(/\/api\/workflows\/wf_/)) {
      const detail = overrides?.workflowDetail ?? {
        id: 'wf_default', name: 'Test Workflow', nodes: [], edges: [],
        variables: [], analysis: null, conversation_id: null, output_type: 'string',
        metadata: { name: 'Test Workflow', description: '', domain: '', tags: [] },
        outputs: [],
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...detail,
          analysis: null,
          metadata: { name: detail.name, description: '', domain: '', tags: [] },
          outputs: [],
        }),
      })
    }

    // Conversation history: GET /api/chat/:id
    if (url.includes('/api/chat/') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ messages: overrides?.chatMessages ?? [] }),
      })
    }

    // Public workflows endpoint
    if (url.includes('/api/workflows/public')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ workflows: [], count: 0 }),
      })
    }

    // Any other API call — return 200 empty
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    })
  })
}

// ── localStorage Seeding ─────────────────────────────────────────

/** Build the localStorage payload for a workflow with the given messages. */
export function buildChatStorage(
  workflowId: string,
  messages: MessagePayload[],
  conversationId: string | null = 'conv-test-1',
): string {
  const payload: PersistedChatState = {
    state: {
      activeWorkflowId: workflowId,
      pendingQuestions: [],
      conversations: {
        [workflowId]: {
          messages,
          conversationId,
          isStreaming: false,
          streamingContent: '',
          _inThinkingBlock: false,
          processingStatus: null,
          currentTaskId: null,
          contextUsagePct: 0,
        },
      },
    },
    version: 0,
  }
  return JSON.stringify(payload)
}

/** Seed localStorage and navigate to the workflow page. */
export async function seedAndLoad(page: Page, workflowId: string, storageJson: string) {
  await page.goto('/')
  await page.evaluate(
    ({ key, value }) => localStorage.setItem(key, value),
    { key: 'lemon-chat', value: storageJson },
  )
  await page.goto(`/workflow/${workflowId}`)
}

// ── Message & ToolCall Builders ──────────────────────────────────

let msgCounter = 0

/** Create a message payload with auto-incrementing ID. */
export function msg(
  role: 'user' | 'assistant',
  content: string,
  toolCalls: ToolCallPayload[] = [],
): MessagePayload {
  msgCounter++
  return {
    id: `msg_${msgCounter}`,
    role,
    content,
    timestamp: new Date(2024, 0, 1, 0, msgCounter).toISOString(),
    tool_calls: toolCalls,
  }
}

/** Create a tool call payload. */
export function tc(
  tool: string,
  args: Record<string, unknown> = {},
  success?: boolean,
): ToolCallPayload {
  const call: ToolCallPayload = { tool, arguments: args }
  if (success !== undefined) call.success = success
  return call
}

/** Reset the message counter between tests. */
export function resetMsgCounter() {
  msgCounter = 0
}

// ── Chat Interaction Helpers ─────────────────────────────────────

/**
 * Fill the chat input, click Send, and return the task_id that the
 * frontend generated. Uses Playwright's waitForRequest to capture
 * the HTTP POST body so the test can include the correct task_id
 * in subsequent assertions.
 */
export async function sendAndGetTaskId(page: Page, text: string): Promise<string> {
  const postPromise = page.waitForRequest(req =>
    req.url().includes('/api/chat/send') && req.method() === 'POST',
  )

  await page.fill('#chatInput', text)
  await page.click('#sendBtn')

  const request = await postPromise
  const body = JSON.parse(request.postData() || '{}')
  return body.task_id as string
}
