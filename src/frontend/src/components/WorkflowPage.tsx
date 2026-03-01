import { useEffect, useRef, useState, useCallback } from 'react'
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
    const [authReady, setAuthReady] = useState(false)
    const { error, clearError, chatHeight, setError, workspaceRevealed, revealWorkspace } = useUIStore()
    const { setCurrentWorkflow, setFlowchart, setAnalysis, setPendingImage } = useWorkflowStore()
    const { sendUserMessage } = useChatStore()
    const loadedWorkflowIdRef = useRef<string | null>(null)

    // Home chatbox state
    const [homeChatInput, setHomeChatInput] = useState('')
    const [isHomeSending, setIsHomeSending] = useState(false)
    const homeFileInputRef = useRef<HTMLInputElement>(null)

    // Track transition state for animations
    const [isTransitioning, setIsTransitioning] = useState(false)

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
        return () => { isActive = false }
    }, [setError])

    // Load workflow from URL params
    useEffect(() => {
        if (!authReady) return
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '')
        const workflowId = params.get('id')
        if (!workflowId) return
        if (loadedWorkflowIdRef.current === workflowId) return

        // If loading a specific workflow, reveal workspace immediately
        if (!workspaceRevealed) {
            revealWorkspace()
        }

        let isActive = true
        const loadWorkflow = async () => {
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

                const fc = transformFlowchartFromBackend({
                    nodes: workflowData.nodes || [],
                    edges: workflowData.edges || [],
                })
                setFlowchart(fc)

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
                setError(`Failed to load workflow (${workflowId}): ${msg}`)
            }
        }
        loadWorkflow()
        return () => { isActive = false }
    }, [authReady, setAnalysis, setCurrentWorkflow, setError, setFlowchart, workspaceRevealed, revealWorkspace])

    // Error toast auto-dismiss
    useEffect(() => {
        if (error) {
            const timer = setTimeout(clearError, 5000)
            return () => clearTimeout(timer)
        }
    }, [error, clearError])

    // Trigger reveal with transition tracking
    const triggerReveal = useCallback(() => {
        setIsTransitioning(true)
        revealWorkspace()
        // Clear transition state after animation completes
        setTimeout(() => setIsTransitioning(false), 500)
    }, [revealWorkspace])

    // Home chatbox: send message and trigger transition
    const handleHomeSend = useCallback(async () => {
        const text = homeChatInput.trim()
        if (!text || isHomeSending) return

        setIsHomeSending(true)

        // Add user message to store locally so it appears in chat history right away
        sendUserMessage(text)

        triggerReveal()

        // Small delay to let transition begin and socket initialize
        setTimeout(() => {
            sendChatMessage(text)
            setIsHomeSending(false)
        }, 300)
    }, [homeChatInput, isHomeSending, triggerReveal, sendUserMessage])

    // Home chatbox: key handler
    const handleHomeKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleHomeSend()
        }
    }, [handleHomeSend])

    // Home chatbox: image upload
    const handleHomeImageUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        const reader = new FileReader()
        reader.onload = async () => {
            try {
                const original = reader.result as string
                const { dataUrl, didChange, bytes } = await compressDataUrl(original, {
                    maxBytes: MAX_IMAGE_BYTES,
                    maxDimension: MAX_IMAGE_DIMENSION,
                })

                if (bytes > MAX_IMAGE_BYTES) {
                    setError(
                        `Image is too large (${(bytes / (1024 * 1024)).toFixed(1)}MB). Try a smaller image.`
                    )
                    return
                }

                setPendingImage(dataUrl, file.name)

                const note = didChange
                    ? ` (resized to ${(bytes / (1024 * 1024)).toFixed(1)}MB)`
                    : ''

                addAssistantMessage(
                    `Image "${file.name}" uploaded${note}. You can now ask me to analyse it.`
                )

                triggerReveal()
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to process image')
            }
        }
        reader.readAsDataURL(file)

        if (homeFileInputRef.current) {
            homeFileInputRef.current.value = ''
        }
    }, [setPendingImage, setError, triggerReveal])

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
            <div className={`home-floating ${workspaceRevealed ? 'home-floating-exit' : ''}`}>
                <div className="home-content">
                    <div className="home-greeting">
                        <span className="greeting-sparkle">✦</span>
                        <h2 className="greeting-subtitle">Hi there</h2>
                        <h1 className="greeting-title">Where should we start?</h1>
                    </div>

                    <div className="home-chat-bar">
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

                    <div className="home-chips">
                        <button className="home-chip" onClick={() => { window.location.hash = '#/library' }}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
                                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
                            </svg>
                            Browse Library
                        </button>

                        <label className="home-chip" htmlFor="homeImageUpload">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                            Upload Image
                        </label>
                        <input
                            ref={homeFileInputRef}
                            type="file"
                            id="homeImageUpload"
                            accept="image/*"
                            style={{ display: 'none' }}
                            onChange={handleHomeImageUpload}
                        />

                        <button className="home-chip" onClick={() => { triggerReveal() }}>
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
