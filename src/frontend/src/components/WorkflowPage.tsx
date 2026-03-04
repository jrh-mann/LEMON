import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Palette from './Palette'
import Canvas from './Canvas'
import RightSidebar from './RightSidebar'
import Chat from './Chat'
import Modals from './Modals'
import SubflowExecutionModal from './SubflowExecutionModal'
import ToolInspectorModal from './ToolInspectorModal'
import { ExecutionLogModal } from './ExecutionLogModal'
import { ApiError } from '../api/client'
import { getCurrentUser } from '../api/auth'
import { getWorkflow } from '../api/workflows'
import { useSession } from '../hooks/useSession'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { transformFlowchartFromBackend } from '../utils/canvas'
import { sendChatMessage } from '../api/socket'
import { useChatStore, addAssistantMessage } from '../stores/chatStore'
import { compressDataUrl, MAX_IMAGE_BYTES, MAX_IMAGE_DIMENSION } from '../utils/imageUtils'
import type { WorkflowAnalysis, Workflow } from '../types'
import '../styles/HomePage.css'

export default function WorkflowPage() {
    const { id: workflowId } = useParams<{ id: string }>()
    const navigate = useNavigate()
    const [authReady, setAuthReady] = useState(false)

    // UI Store state
    const workspaceRevealed = useUIStore(s => s.workspaceRevealed)
    const homeExited = useUIStore(s => s.homeExited)
    const isTransitioning = useUIStore(s => s.isTransitioning)
    const chatHeight = useUIStore(s => s.chatHeight)
    const error = useUIStore(s => s.error)

    // UI Store actions
    const revealWorkspace = useUIStore(s => s.revealWorkspace)
    const setHomeExited = useUIStore(s => s.setHomeExited)
    const setIsTransitioning = useUIStore(s => s.setIsTransitioning)
    const setError = useUIStore(s => s.setError)
    const clearError = useUIStore(s => s.clearError)

    // Workflow Store
    const { setCurrentWorkflow, setCurrentWorkflowId, setFlowchart, setAnalysis, addPendingFile } = useWorkflowStore()
    const { sendUserMessage } = useChatStore()
    const loadedWorkflowIdRef = useRef<string | null>(null)

    // Trigger reveal with transition tracking
    const triggerReveal = useCallback(() => {
        setIsTransitioning(true)
        revealWorkspace()
        // Clear transition state after animation completes
        setTimeout(() => setIsTransitioning(false), 500)
    }, [revealWorkspace, setIsTransitioning])

    /**
     * Generate a canonical workflow ID: wf_{32_hex_chars}.
     * This is the single ID format used by frontend, backend, and DB.
     */
    const generateWorkflowId = () => `wf_${crypto.randomUUID().replace(/-/g, '')}`

    /**
     * Orchestrates the transition from Home to Workspace:
     * 1. Trigger Home Exit animation
     * 2. Wait for animation to finish
     * 3. Navigate to route with ID (generate canonical wf_ ID if needed)
     * 4. Trigger Workspace Reveal animation
     */
    const startWorkflowSession = useCallback(async (existingId?: string) => {
        const id = existingId || generateWorkflowId()

        // Mark new (unsaved) IDs as "already loaded" so the useEffect
        // that fetches workflow data from the API doesn't fire a 404.
        // Existing IDs (from library) are left unmarked so they get fetched.
        if (!existingId) {
            loadedWorkflowIdRef.current = id
        }

        // 1. Play Home Exit animation
        setHomeExited(true)

        // 2. Wait for exit animation (opacity/slide up) to finish
        await new Promise(resolve => setTimeout(resolve, 400))

        // 3. Navigate to route with ID
        navigate(`/workflow/${id}`)

        // 4. Trigger Workspace Reveal (sidebars slide in)
        triggerReveal()
    }, [navigate, setHomeExited, triggerReveal])

    // Home chatbox state
    const [homeChatInput, setHomeChatInput] = useState('')
    const [isHomeSending, setIsHomeSending] = useState(false)
    const homeFileInputRef = useRef<HTMLInputElement>(null)

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
                    navigate('/auth')
                    return
                }
                setError('Unable to verify your session. Please try again.')
            }
        }
        checkAuth()
        return () => { isActive = false }
    }, [setError, navigate])

    // Load workflow from URL params, or sync URL ID to store for new workflows
    useEffect(() => {
        if (!authReady || !workflowId) {
            return
        }

        if (loadedWorkflowIdRef.current === workflowId) return

        let isActive = true
        const loadWorkflow = async () => {
            try {
                const workflowData = await getWorkflow(workflowId)
                if (!isActive) return

                const workflow: Workflow = {
                    id: workflowData.id,
                    metadata: workflowData.metadata,
                    blocks: [],
                    connections: [],
                }
                setCurrentWorkflow(workflow)

                const fc = transformFlowchartFromBackend({
                    nodes: workflowData.nodes || [],
                    edges: workflowData.edges || [],
                })
                setFlowchart(fc)

                const analysis: WorkflowAnalysis = {
                    variables: workflowData.variables || [],
                    outputs: workflowData.outputs || [],
                    tree: workflowData.tree || {},
                    doubts: workflowData.doubts || [],
                }
                setAnalysis(analysis)
                loadedWorkflowIdRef.current = workflowId

                // After state is set, trigger the staggered reveal if we are still hidden
                // and NOT currently in a card-zoom transition
                const state = useUIStore.getState()
                if (!state.workspaceRevealed && !state.zoomingCard) {
                    // Mark home as exited for direct loads
                    setHomeExited(true)
                    // Small delay to ensure React has rendered the nodes
                    setTimeout(triggerReveal, 50)
                }
            } catch (err) {
                if (!isActive) return

                // 404 = new workflow (not in DB yet) — sync URL ID to store
                if (err instanceof ApiError && err.status === 404) {
                    setCurrentWorkflowId(workflowId)
                    loadedWorkflowIdRef.current = workflowId
                    return
                }

                const msg = err instanceof Error ? err.message : 'Unknown error'
                setError(`Failed to load workflow (${workflowId}): ${msg}`)
            }
        }
        loadWorkflow()
        return () => { isActive = false }
    }, [authReady, workflowId, setAnalysis, setCurrentWorkflow, setCurrentWorkflowId, setError, setFlowchart, triggerReveal, setHomeExited])

    // Error toast auto-dismiss
    useEffect(() => {
        if (error) {
            const timer = setTimeout(clearError, 5000)
            return () => clearTimeout(timer)
        }
    }, [error, clearError])

    // Home chatbox: send message and trigger transition
    const handleHomeSend = useCallback(async () => {
        const text = homeChatInput.trim()
        if (!text || isHomeSending) return

        setIsHomeSending(true)

        // Add user message to store locally so it appears in chat history right away
        sendUserMessage(text)

        // Orchestrate exit sequence
        await startWorkflowSession()

        // Small delay to let transition begin and socket initialize
        setTimeout(() => {
            sendChatMessage(text)
            setIsHomeSending(false)
        }, 300)
    }, [homeChatInput, isHomeSending, sendUserMessage, startWorkflowSession])

    // Home chatbox: key handler
    const handleHomeKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleHomeSend()
        }
    }, [handleHomeSend])

    // Home chatbox: file upload (images and PDFs, supports multiple)
    const handleHomeFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const fileList = e.target.files
        if (!fileList || fileList.length === 0) return

        const names: string[] = []
        for (const file of Array.from(fileList)) {
            try {
                const isPdf = file.type === 'application/pdf'
                const reader = new FileReader()
                const dataUrl = await new Promise<string>((resolve, reject) => {
                    reader.onload = () => resolve(reader.result as string)
                    reader.onerror = () => reject(new Error('Failed to read file'))
                    reader.readAsDataURL(file)
                })

                let finalDataUrl = dataUrl
                if (!isPdf) {
                    // Compress images to stay under Anthropic's size limit
                    const { dataUrl: compressed, didChange, bytes } = await compressDataUrl(dataUrl, {
                        maxBytes: MAX_IMAGE_BYTES,
                        maxDimension: MAX_IMAGE_DIMENSION,
                    })
                    if (bytes > MAX_IMAGE_BYTES) {
                        setError(`"${file.name}" is too large (${(bytes / (1024 * 1024)).toFixed(1)}MB). Skipped.`)
                        continue
                    }
                    finalDataUrl = compressed
                    if (didChange) {
                        names.push(`${file.name} (resized)`)
                    } else {
                        names.push(file.name)
                    }
                } else {
                    names.push(file.name)
                }

                addPendingFile({
                    id: `${Date.now()}_${file.name}`,
                    name: file.name,
                    dataUrl: finalDataUrl,
                    type: isPdf ? 'pdf' : 'image',
                    purpose: 'unclassified',
                })
            } catch (err) {
                setError(err instanceof Error ? err.message : `Failed to process ${file.name}`)
            }
        }

        if (names.length > 0) {
            const msg = names.length === 1
                ? `File "${names[0]}" uploaded. You can now ask me to analyse it.`
                : `Uploaded ${names.length} files: ${names.join(', ')}.`
            addAssistantMessage(msg)

            // Orchestrate exit sequence
            startWorkflowSession()
        }

        if (homeFileInputRef.current) {
            homeFileInputRef.current.value = ''
        }
    }, [addPendingFile, setError, startWorkflowSession])

    const revealedClass = workspaceRevealed ? 'workspace-revealed' : 'workspace-hidden'

    return (
        <>
            {/* Full workspace layout - always rendered */}
            <div className={`app-layout ${revealedClass} ${isTransitioning ? 'transitioning' : ''}`} style={{ '--chat-height': `${chatHeight}px` } as React.CSSProperties}>
                <main className="workspace">
                    <Palette />
                    <Canvas />
                    <RightSidebar />
                </main>
            </div>

            {/* Home content - floating on top of canvas when not revealed */}
            <div className={`home-floating ${homeExited ? 'home-floating-exit' : ''}`}>
                <div className="home-content">
                    <div className="home-greeting animate-slide-down-2">
                        <span className="greeting-sparkle">✦</span>
                        <h2 className="greeting-subtitle">Hi there</h2>
                        <h1 className="greeting-title">Where should we start?</h1>
                    </div>

                    <div className="home-chat-bar animate-slide-down-3">
                        <textarea
                            className="home-chat-input"
                            placeholder="Describe a workflow to build..."
                            value={homeChatInput}
                            onChange={(e) => setHomeChatInput(e.target.value)}
                            onKeyDown={handleHomeKeyDown}
                            rows={1}
                            disabled={isHomeSending}
                            autoFocus
                        />
                        <div className="home-chat-actions">
                            <button
                                className="home-send-btn"
                                onClick={handleHomeSend}
                                disabled={!homeChatInput.trim() || isHomeSending}
                                title="Send message"
                            >
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path d="M22 2L11 13" />
                                    <path d="M22 2l-7 20-4-9-9-4 20-7z" />
                                </svg>
                            </button>
                        </div>
                    </div>

                    <div className="home-chips animate-slide-down-4">
                        <button className="home-chip" onClick={() => navigate('/library')}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
                                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
                            </svg>
                            Browse Library
                        </button>

                        <label className="home-chip" htmlFor="homeFileUpload">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                            Upload Files
                        </label>
                        <input
                            ref={homeFileInputRef}
                            type="file"
                            id="homeFileUpload"
                            accept="image/*,application/pdf"
                            multiple
                            style={{ display: 'none' }}
                            onChange={handleHomeFileUpload}
                        />

                        <button className="home-chip" onClick={() => { startWorkflowSession() }}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M12 5v14M5 12h14" />
                            </svg>
                            New Workflow
                        </button>
                    </div>
                </div>
            </div>

            <Chat revealedClass={revealedClass} />
            <Modals />
            <SubflowExecutionModal />
            <ToolInspectorModal />
            <ExecutionLogModal />

            {/* Error toast */}
            {error && (
                <div className="error-toast" onClick={clearError}>
                    <span>{error}</span>
                    <button className="toast-close">×</button>
                </div>
            )}
        </>
    )
}
