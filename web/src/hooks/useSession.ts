import { useEffect } from 'react'
import { getSessionId, clearSession } from '../api/client'
import { connectSocket, disconnectSocket } from '../api/socket'

// Hook to manage session lifecycle
export function useSession() {
  useEffect(() => {
    // Ensure session ID exists
    const sessionId = getSessionId()
    console.log('[Session] ID:', sessionId)

    // Connect socket on mount
    connectSocket()

    // Cleanup on unmount
    return () => {
      disconnectSocket()
    }
  }, [])

  return {
    sessionId: getSessionId(),
    clearSession,
  }
}
