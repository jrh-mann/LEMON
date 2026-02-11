import { useEffect, useState } from 'react'
import './styles.css'
import Header from './components/Header'
import TabBar from './components/TabBar'
import Palette from './components/Palette'
import Canvas from './components/Canvas'
import RightSidebar from './components/RightSidebar'
import Chat from './components/Chat'
import Modals from './components/Modals'
import SubflowExecutionModal from './components/SubflowExecutionModal'
import ToolInspectorModal from './components/ToolInspectorModal'
import { ExecutionLogModal } from './components/ExecutionLogModal'
import AuthPage from './components/AuthPage'
import { ApiError } from './api/client'
import { getCurrentUser } from './api/auth'
import { useSession } from './hooks/useSession'
import { useUIStore } from './stores/uiStore'

const isAuthHash = () => window.location.hash === '#/auth' || window.location.hash === '#auth'
const isMiroCallback = () => window.location.hash.startsWith('#/miro-callback')

function WorkspaceApp() {
  const [authReady, setAuthReady] = useState(false)
  const { error, clearError, chatHeight, setError } = useUIStore()

  // Initialize session and socket connection
  useSession(authReady)

  useEffect(() => {
    let isActive = true
    const checkAuth = async () => {
      try {
        await getCurrentUser()
        if (!isActive) return
        setAuthReady(true)
      } catch (err) {
        if (!isActive) return
        if (err instanceof ApiError && err.status === 401) {
          window.location.hash = '#/auth'
          return
        }
        setError('Unable to verify your session. Please try again.')
      }
    }
    checkAuth()
    return () => {
      isActive = false
    }
  }, [setError])

  // Show error toast
  useEffect(() => {
    if (error) {
      const timer = setTimeout(clearError, 5000)
      return () => clearTimeout(timer)
    }
  }, [error, clearError])

  return (
    <>
      <div className="app-layout" style={{ '--chat-height': `${chatHeight}px` } as React.CSSProperties}>
        <Header />
        <TabBar />

        <main className="workspace">
          <Palette />
          <Canvas />
          <RightSidebar />
        </main>
      </div>

      <Chat />
      <Modals />
      <SubflowExecutionModal />
      <ToolInspectorModal />
      <ExecutionLogModal />

      {/* Error toast */}
      {error && (
        <div className="error-toast" onClick={clearError}>
          <span>{error}</span>
          <button className="toast-close">Ã—</button>
        </div>
      )}
    </>
  )
}

function App() {
  const [isAuthRoute, setIsAuthRoute] = useState(() => isAuthHash())
  const { openModal, setError } = useUIStore()

  useEffect(() => {
    const handleHashChange = () => setIsAuthRoute(isAuthHash())
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  // Handle Miro OAuth callback
  useEffect(() => {
    if (isMiroCallback()) {
      const hash = window.location.hash
      const params = new URLSearchParams(hash.split('?')[1] || '')
      const success = params.get('success')
      const error = params.get('error')

      // Clear the callback hash
      window.location.hash = ''

      if (success === 'true') {
        // Successfully connected - open the import modal
        setTimeout(() => {
          openModal('miro-import')
        }, 100)
      } else if (error) {
        // Show error
        setError(`Miro connection failed: ${decodeURIComponent(error)}`)
      }
    }
  }, [openModal, setError])

  return (
    <>
      <div className="backdrop"></div>
      {isAuthRoute ? <AuthPage /> : <WorkspaceApp />}
    </>
  )
}

export default App
