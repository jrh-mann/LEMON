import { useEffect, useRef, useState } from 'react'
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
import { getWorkflow } from './api/workflows'
import { useSession } from './hooks/useSession'
import { useUIStore } from './stores/uiStore'
import { useWorkflowStore } from './stores/workflowStore'
import { transformFlowchartFromBackend } from './utils/canvas'
import type { WorkflowAnalysis, Workflow } from './types'

const isAuthHash = () => window.location.hash === '#/auth' || window.location.hash === '#auth'

function WorkspaceApp() {
  const [authReady, setAuthReady] = useState(false)
  const { error, clearError, chatHeight, setError } = useUIStore()
  const { setCurrentWorkflow, setFlowchart, setAnalysis } = useWorkflowStore()
  const loadedWorkflowIdRef = useRef<string | null>(null)

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

  // Optional deep-link: /?workflow_id=<id>
  // Loads a saved workflow directly onto canvas after auth.
  useEffect(() => {
    if (!authReady) return
    const workflowId = new URLSearchParams(window.location.search).get('workflow_id')
    if (!workflowId) return
    if (loadedWorkflowIdRef.current === workflowId) return

    let isActive = true
    const loadWorkflowFromUrl = async () => {
      try {
        const workflowData: any = await getWorkflow(workflowId)
        if (!isActive) return

        const workflow: Workflow = {
          id: workflowData.id,
          metadata: workflowData.metadata,
          blocks: [],
          connections: [],
        }
        setCurrentWorkflow(workflow)

        const flowchart = transformFlowchartFromBackend({
          nodes: workflowData.nodes || [],
          edges: workflowData.edges || [],
        })
        setFlowchart(flowchart)

        const analysis: WorkflowAnalysis = {
          variables: workflowData.inputs || [],
          outputs: workflowData.outputs || [],
          tree: workflowData.tree || {},
          doubts: workflowData.doubts || [],
        }
        setAnalysis(analysis)
        loadedWorkflowIdRef.current = workflowId
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error'
        setError(`Failed to load workflow from URL (${workflowId}): ${msg}`)
      }
    }

    loadWorkflowFromUrl()
    return () => {
      isActive = false
    }
  }, [authReady, setAnalysis, setCurrentWorkflow, setError, setFlowchart])

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

  useEffect(() => {
    const handleHashChange = () => setIsAuthRoute(isAuthHash())
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  return (
    <>
      <div className="backdrop"></div>
      {isAuthRoute ? <AuthPage /> : <WorkspaceApp />}
    </>
  )
}

export default App
