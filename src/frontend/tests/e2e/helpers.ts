/**
 * Shared E2E test helpers — API mocking, mock Socket.IO, types.
 *
 * Two modes of testing:
 *
 * 1. **Static rendering tests** — seed localStorage, mock all APIs, verify
 *    that components render the seeded state correctly. Use buildChatStorage()
 *    + seedAndLoad(). Socket.IO is dead (default mockAllAPIs behavior).
 *
 * 2. **Integration flow tests** — use MockSocketIO to give the frontend a
 *    real socket connection. Type in the chat input, click send, inject
 *    socket events from the "server", and verify the full state management
 *    pipeline: handleSend → HTTP POST → socket events → store → UI.
 */
import type { Page, Route } from '@playwright/test'

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
      thinkingContent: string
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

// ── Mock Socket.IO Server ───────────────────────────────────────
//
// Speaks the real engine.io v4 / socket.io v4 polling protocol so
// the frontend's socket.io-client actually connects. Tests call
// sio.emit() to inject events; the frontend processes them through
// the same chatHandlers / agentHandlers code that runs in production.

export class MockSocketIO {
  /** Session ID used for the engine.io and namespace connection. */
  readonly sid: string
  /** Resolves when the client has completed the socket handshake. */
  readonly connected: Promise<void>

  private _connectedResolve: (() => void) | null = null
  private _handshakeComplete = false
  private _packets: string[] = []
  /** Pending long-poll: route + resolver to unblock the handler. */
  private _pendingPoll: { route: Route; resolve: () => void } | null = null

  constructor() {
    this.sid = `test_${Math.random().toString(36).slice(2, 10)}`
    this.connected = new Promise(resolve => { this._connectedResolve = resolve })
  }

  /**
   * Install the mock Socket.IO polling transport on the page.
   * Must be called BEFORE page.goto() and BEFORE mockAllAPIs().
   * Pass `skipSocket: true` to mockAllAPIs so it doesn't clobber this.
   *
   * Long-poll handling: When no packets are queued, the route handler
   * returns a Promise that stays pending until emit() pushes data.
   * This keeps Playwright's route handler "alive" so we can call
   * route.fulfill() later without it being considered already handled.
   */
  async install(page: Page) {
    await page.route(/\/socket\.io\//, (route) => {
      const url = route.request().url()
      const method = route.request().method()
      const hasSid = url.includes('sid=')
      // Check if the sid in the URL belongs to this mock instance.
      // After page.reload(), stale requests from the old connection may
      // arrive with a different sid — pass those to the next handler.
      const isOurSid = hasSid && url.includes(`sid=${this.sid}`)
      if (hasSid && !isOurSid) {
        return route.fallback()
      }

      // Engine.IO open handshake (first GET, no sid)
      if (method === 'GET' && !hasSid) {
        return route.fulfill({
          status: 200,
          contentType: 'text/plain',
          body: `0${JSON.stringify({
            sid: this.sid,
            upgrades: [],
            pingInterval: 25000,
            pingTimeout: 60000,
            maxPayload: 1000000,
          })}`,
        })
      }

      // Client POST (sends namespace CONNECT packet, pong, etc.)
      if (method === 'POST') {
        return route.fulfill({ status: 200, contentType: 'text/plain', body: 'ok' })
      }

      // Client GET with sid — polling for data
      if (method === 'GET' && hasSid) {
        if (!this._handshakeComplete) {
          // First poll after open: return Socket.IO namespace connect ack.
          // This makes socket.connected=true and socket.id=sid.
          this._handshakeComplete = true
          this._connectedResolve?.()
          return route.fulfill({
            status: 200,
            contentType: 'text/plain',
            body: `40{"sid":"${this.sid}"}`,
          })
        }

        // Subsequent polls: flush queued packets or hold for long-polling.
        if (this._packets.length > 0) {
          return this._flush(route)
        }

        // No data yet — return a Promise that keeps the handler alive.
        // emit() will resolve it when data is available, triggering the flush.
        return new Promise<void>((resolve) => {
          this._pendingPoll = { route, resolve }
        })
      }

      // Fallback
      route.fulfill({ status: 200, contentType: 'text/plain', body: '' })
    })
  }

  /**
   * Wait until a long-poll GET is waiting (i.e. the client is ready
   * to receive events). Useful after page reload / socket reconnect.
   */
  async waitForPoll(timeoutMs = 5000): Promise<void> {
    if (this._pendingPoll) return
    const start = Date.now()
    while (!this._pendingPoll && Date.now() - start < timeoutMs) {
      await new Promise(r => setTimeout(r, 50))
    }
    if (!this._pendingPoll) throw new Error('MockSocketIO: no poll arrived within timeout')
  }

  /**
   * Emit a Socket.IO event to the connected client.
   * Uses microtask batching so multiple synchronous emit() calls
   * are delivered together in a single poll response.
   */
  emit(event: string, data: unknown) {
    // Socket.IO packet: 4 = engine.io MESSAGE, 2 = socket.io EVENT
    this._packets.push(`42${JSON.stringify([event, data])}`)
    this._scheduleFlush()
  }

  private _flushScheduled = false

  /** Schedule a microtask to flush all queued packets to the pending poll. */
  private _scheduleFlush() {
    if (this._flushScheduled) return
    if (!this._pendingPoll) return // No poll waiting — packets queue until next poll arrives
    this._flushScheduled = true
    Promise.resolve().then(async () => {
      this._flushScheduled = false
      if (this._pendingPoll && this._packets.length > 0) {
        const { route, resolve } = this._pendingPoll
        this._pendingPoll = null
        await this._flush(route) // Wait for Playwright to deliver the response
        resolve() // Then unblock the route handler
      }
    })
  }

  private _flush(route: Route): Promise<void> {
    // engine.io v4 separates multiple packets with \x1e (record separator)
    const body = this._packets.splice(0).join('\x1e')
    return route.fulfill({ status: 200, contentType: 'text/plain', body })
  }
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
  /** When true, don't install a dead Socket.IO mock.
   *  Use this with MockSocketIO for integration tests. */
  skipSocket?: boolean
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

  // Socket.IO polling — dead by default unless skipSocket is set
  if (!overrides?.skipSocket) {
    await page.route(/\/socket\.io\//, (route) =>
      route.fulfill({ status: 200, contentType: 'text/plain', body: '' }),
    )
  }
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
          thinkingContent: '',
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
 * in subsequent socket events.
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
