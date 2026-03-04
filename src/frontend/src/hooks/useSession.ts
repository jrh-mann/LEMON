import { useEffect } from 'react'
import { getSessionId, clearSession } from '../api/client'
import { connectSocket } from '../api/socket'

// Hook to manage session lifecycle.
// The socket is a persistent singleton — it connects once and stays
// connected across React Router navigations. Disconnecting on unmount
// would kill the event channel for in-flight orchestrator tasks,
// causing responses to be lost when the user navigates away and back.
export function useSession(enabled = true) {
  useEffect(() => {
    if (!enabled) {
      return
    }

    // Ensure session ID exists
    const sessionId = getSessionId()
    console.log('[Session] ID:', sessionId)

    // Connect socket (idempotent — returns existing if already connected)
    connectSocket()

    // No cleanup: socket persists across page navigations.
    // It is only torn down on full page reload / tab close.
  }, [enabled])

  return {
    sessionId: getSessionId(),
    clearSession,
  }
}
