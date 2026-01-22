import { useEffect } from 'react'
import { getSessionId, clearSession } from '../api/client'
import { connectSocket, disconnectSocket } from '../api/socket'

// Hook to manage session lifecycle
export function useSession(enabled = true) {
  useEffect(() => {
    if (!enabled) {
      return
    }

    // Ensure session ID exists
    const sessionId = getSessionId()
    console.log('[Session] ID:', sessionId)

    // Connect socket on mount
    connectSocket()

    // Cleanup on unmount
    return () => {
      disconnectSocket()
    }
  }, [enabled])

  return {
    sessionId: getSessionId(),
    clearSession,
  }
}
