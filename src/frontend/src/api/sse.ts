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

// Debug logging — tracks stream lifecycle, keepalives, and disconnects.
// Prefix all logs with [SSE:id] where id is a short stream identifier.
let _streamCounter = 0

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
  const streamId = ++_streamCounter

  // Combine external signal with our internal controller
  const signal = options?.signal
    ? AbortSignal.any([options.signal, controller.signal])
    : controller.signal

  console.log(`[SSE:${streamId}] Creating stream → ${url}`)

  // Fire-and-forget the async read loop
  _readSSEStream(url, body, handlers, signal, streamId).catch((err) => {
    if (err.name === 'AbortError') {
      console.log(`[SSE:${streamId}] Stream aborted (expected — cancel or navigation)`)
      return
    }
    console.error(`[SSE:${streamId}] Stream error:`, err.name, err.message)
    handlers['error']?.({ error: err.message || 'SSE connection failed' })
  })

  return {
    abort: () => {
      console.log(`[SSE:${streamId}] abort() called`)
      controller.abort()
    },
  }
}

/**
 * Internal: fetch + read the SSE stream line by line.
 */
async function _readSSEStream(
  url: string,
  body: unknown,
  handlers: SSEHandlers,
  signal: AbortSignal,
  streamId: number,
): Promise<void> {
  const startTime = Date.now()
  let eventCount = 0
  let keepaliveCount = 0
  let lastEventTime = startTime
  let lastKeepaliveTime = startTime

  console.log(`[SSE:${streamId}] fetch() starting...`)

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include', // Send session cookie
    body: JSON.stringify(body),
    signal,
  })

  const fetchElapsed = Date.now() - startTime
  console.log(`[SSE:${streamId}] fetch() responded: HTTP ${response.status} (${fetchElapsed}ms)`)

  if (!response.ok) {
    // Non-2xx response — try to parse error JSON
    let errorMessage = `HTTP ${response.status}`
    try {
      const errBody = await response.json()
      errorMessage = errBody.detail || errBody.error || errorMessage
    } catch { /* ignore parse failure */ }
    console.error(`[SSE:${streamId}] HTTP error: ${errorMessage}`)
    handlers['error']?.({ error: errorMessage })
    return
  }

  if (!response.body) {
    console.error(`[SSE:${streamId}] No response body`)
    handlers['error']?.({ error: 'No response body' })
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let currentData = ''
  let chunkCount = 0

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        const totalElapsed = ((Date.now() - startTime) / 1000).toFixed(1)
        console.log(`[SSE:${streamId}] Stream ended (done=true) after ${totalElapsed}s — ${eventCount} events, ${keepaliveCount} keepalives, ${chunkCount} chunks`)
        break
      }

      chunkCount++
      const decoded = decoder.decode(value, { stream: true })
      buffer += decoded

      // Process complete lines from the buffer
      while (true) {
        const newlineIdx = buffer.indexOf('\n')
        if (newlineIdx === -1) break

        const line = buffer.slice(0, newlineIdx)
        buffer = buffer.slice(newlineIdx + 1)

        if (line === '') {
          // Empty line = end of event block — dispatch if we have data
          if (currentData) {
            eventCount++
            lastEventTime = Date.now()
            _dispatchEvent(currentEvent || 'message', currentData, handlers, streamId)
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
          keepaliveCount++
          lastKeepaliveTime = Date.now()
          const sinceLastEvent = ((lastKeepaliveTime - lastEventTime) / 1000).toFixed(1)
          if (keepaliveCount <= 3 || keepaliveCount % 10 === 0) {
            // Log first few keepalives and then every 10th to avoid spam
            console.log(`[SSE:${streamId}] keepalive #${keepaliveCount} (${sinceLastEvent}s since last event)`)
          }
          handlers['keepalive']?.({})
        }
      }
    }

    // Flush any remaining event
    if (currentData) {
      _dispatchEvent(currentEvent || 'message', currentData, handlers, streamId)
    }
  } catch (err) {
    const totalElapsed = ((Date.now() - startTime) / 1000).toFixed(1)
    const sinceLastEvent = ((Date.now() - lastEventTime) / 1000).toFixed(1)
    const sinceLastKeepalive = ((Date.now() - lastKeepaliveTime) / 1000).toFixed(1)
    const errObj = err as Error
    console.error(
      `[SSE:${streamId}] Reader error after ${totalElapsed}s:`,
      errObj.name, errObj.message,
      `| events=${eventCount} keepalives=${keepaliveCount} chunks=${chunkCount}`,
      `| sinceLastEvent=${sinceLastEvent}s sinceLastKeepalive=${sinceLastKeepalive}s`,
    )
    throw err
  } finally {
    reader.releaseLock()
    const totalElapsed = ((Date.now() - startTime) / 1000).toFixed(1)
    console.log(`[SSE:${streamId}] Stream cleanup — total ${totalElapsed}s, ${eventCount} events, ${keepaliveCount} keepalives`)
    // Signal stream end
    handlers['done']?.({})
  }
}

/**
 * Parse SSE data string as JSON and dispatch to the matching handler.
 */
function _dispatchEvent(event: string, data: string, handlers: SSEHandlers, streamId: number): void {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    console.warn(`[SSE:${streamId}] Failed to parse event data:`, event, data.slice(0, 200))
    return
  }
  const handler = handlers[event]
  if (handler) {
    handler(parsed)
  } else {
    console.log(`[SSE:${streamId}] Unhandled event:`, event)
  }
}
