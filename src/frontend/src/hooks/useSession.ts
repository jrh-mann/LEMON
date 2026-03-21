import { useEffect } from 'react'
import { getSessionId, clearSession } from '../api/client'

// Hook to manage session lifecycle.
// Ensures a session ID exists. All real-time communication uses SSE streams
// created per-request (chat send, execution start, resume), so there is
// no persistent connection to manage here.
export function useSession(enabled = true) {
  useEffect(() => {
    if (!enabled) {
      return
    }

    // Ensure session ID exists
    const sessionId = getSessionId()
    console.log('[Session] ID:', sessionId)
  }, [enabled])

  return {
    sessionId: getSessionId(),
    clearSession,
  }
}
