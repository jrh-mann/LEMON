/**
 * SSE (Server-Sent Events) client for chat and execution streaming.
 *
 * Uses fetch() + ReadableStream instead of EventSource because:
 * - EventSource is GET-only (we need POST with JSON body)
 * - EventSource doesn't support custom headers
 * - fetch gives us AbortController for cancellation
 *
 * Standard SSE format:
 *   event: chat_stream
 *   data: {"chunk": "hello", "task_id": "abc"}
 *   \n
 */

export interface SSEStream {
  /** Abort the SSE stream and underlying fetch connection */
  abort: () => void
}

type SSEHandlers = Record<string, (data: unknown) => void>

/**
 * POST to an endpoint and parse the response as an SSE stream.
 *
 * Events are dispatched to the handlers map by event name.
 * Returns an SSEStream handle with an abort() method for cancellation.
 */
export function createSSEStream(
  url: string,
  body: unknown,
  handlers: SSEHandlers,
  options?: { signal?: AbortSignal },
): SSEStream {
  const controller = new AbortController()

  // Combine external signal with our internal controller
  const signal = options?.signal
    ? AbortSignal.any([options.signal, controller.signal])
    : controller.signal

  // Fire-and-forget the async read loop
  _readSSEStream(url, body, handlers, signal).catch((err) => {
    if (err.name === 'AbortError') return // Expected on cancel
    console.error('[SSE] Stream error:', err)
    handlers['error']?.({ error: err.message || 'SSE connection failed' })
  })

  return { abort: () => controller.abort() }
}

/**
 * Internal: fetch + read the SSE stream line by line.
 */
async function _readSSEStream(
  url: string,
  body: unknown,
  handlers: SSEHandlers,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include', // Send session cookie
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    // Non-2xx response — try to parse error JSON
    let errorMessage = `HTTP ${response.status}`
    try {
      const errBody = await response.json()
      errorMessage = errBody.detail || errBody.error || errorMessage
    } catch { /* ignore parse failure */ }
    handlers['error']?.({ error: errorMessage })
    return
  }

  if (!response.body) {
    handlers['error']?.({ error: 'No response body' })
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let currentData = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Process complete lines from the buffer
      while (true) {
        const newlineIdx = buffer.indexOf('\n')
        if (newlineIdx === -1) break

        const line = buffer.slice(0, newlineIdx)
        buffer = buffer.slice(newlineIdx + 1)

        if (line === '') {
          // Empty line = end of event block — dispatch if we have data
          if (currentData) {
            _dispatchEvent(currentEvent || 'message', currentData, handlers)
          }
          currentEvent = ''
          currentData = ''
        } else if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          // Append data (SSE spec allows multi-line data)
          const dataLine = line.slice(5).trim()
          currentData = currentData ? `${currentData}\n${dataLine}` : dataLine
        }
        // Lines starting with ':' are SSE comments (keepalive from backend).
        // Dispatch to 'keepalive' handler so heartbeat watchdogs stay alive.
        else if (line.startsWith(':')) {
          handlers['keepalive']?.({})
        }
      }
    }

    // Flush any remaining event
    if (currentData) {
      _dispatchEvent(currentEvent || 'message', currentData, handlers)
    }
  } finally {
    reader.releaseLock()
    // Signal stream end
    handlers['done']?.({})
  }
}

/**
 * Parse SSE data string as JSON and dispatch to the matching handler.
 */
function _dispatchEvent(event: string, data: string, handlers: SSEHandlers): void {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    console.warn('[SSE] Failed to parse event data:', event, data)
    return
  }
  const handler = handlers[event]
  if (handler) {
    handler(parsed)
  } else {
    console.log('[SSE] Unhandled event:', event, parsed)
  }
}
