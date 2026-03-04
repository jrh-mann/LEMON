# Tech Debt

## Backend Event Buffering for Socket Reconnection

**Status:** Not started
**Priority:** Medium
**Area:** Backend (socket events), Frontend (reconnection)

### Problem

The socket connection between frontend and backend is currently persistent — it stays alive across React Router navigations. This works, but if the connection drops (network blip, server restart, laptop sleep), events emitted during the disconnection window are lost. The backend orchestrator keeps running and emitting `chat_stream`, `chat_thinking`, `chat_progress`, and `chat_response` events to a dead SID. When the frontend reconnects, it gets a new SID and misses everything that happened in between.

Socket.IO's built-in reconnection reuses the same SID when possible, which helps for brief drops. But if the server restarts or the disconnect lasts longer than the ping timeout, the SID is invalidated and events are permanently lost.

### Current State

- Socket is a persistent singleton (`src/frontend/src/api/socket.ts`) — no disconnect on navigation
- `useSession` hook connects once, never disconnects (`src/frontend/src/hooks/useSession.ts`)
- Backend emits events with `to=sid` — fire-and-forget, no buffering
- Background builder events are buffered on the frontend in `workflowStore.buildBuffers` keyed by `workflow_id`, but only AFTER they arrive — if they never arrive, they're gone

### Proposed Solution

Backend-side event buffer per socket session with catch-up on reconnect:

1. **Event buffer in backend:** When emitting events tagged with `task_id` or `workflow_id`, also store them in a short-lived in-memory buffer keyed by `(sid, task_id|workflow_id)`. Buffer has a TTL (e.g. 5 minutes) and max size.

2. **Sequence numbers:** Each event gets a monotonically increasing sequence number per task/workflow. Frontend tracks the last received sequence number.

3. **Catch-up on reconnect:** When a socket reconnects (same `session_id` but new `sid`), the frontend sends its last known sequence numbers. Backend replays any buffered events with sequence > last_received.

4. **Cleanup:** Buffers are cleared when:
   - `chat_response` is emitted (task complete)
   - TTL expires (stale task)
   - Client explicitly acknowledges receipt

### Files Involved

- `src/backend/api/socket_chat.py` — SocketChatTask event emission
- `src/backend/api/builder_callbacks.py` — BackgroundBuilderCallbacks event emission
- `src/backend/api/socket_handlers.py` — Socket connect/disconnect lifecycle
- `src/frontend/src/api/socket.ts` — Reconnection logic, catch-up request
- `src/frontend/src/api/socket-handlers/chatHandlers.ts` — Sequence tracking

### Why Not Now

- Current persistent socket approach works for the common case (navigation)
- Socket.IO reconnection handles brief network blips
- Server restarts during active tasks are rare in development
- The buffering system adds complexity (sequence numbers, replay logic, buffer lifecycle)
- No production users yet — can revisit when reliability requirements increase
