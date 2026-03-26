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
import { ApiError, API_BASE, getSessionId } from '../api/client'
import { getCurrentUser } from '../api/auth'
import { getWorkflow, importWorkflowBundle, importWorkflowJson, type ValidationError, type WorkflowImportError } from '../api/workflows'
import { syncConversationMessages } from '../utils/conversationSync'
import { useSession } from '../hooks/useSession'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { transformFlowchartFromBackend } from '../utils/canvas'
import { hydrateWorkflowDetail } from '../utils/workflowHydration'
import { sendChatMessage } from '../api/streamActions'
import { useChatStore, addAssistantMessage } from '../stores/chatStore'
import { compressDataUrl, MAX_IMAGE_BYTES, MAX_IMAGE_DIMENSION } from '../utils/imageUtils'

import '../styles/WorkflowLanding.css'


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
    const { setCurrentWorkflow, setCurrentWorkflowId, setFlowchart, setAnalysis, addPendingFile, clearPendingFiles, markSavedSnapshot } = useWorkflowStore()
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

        // Set activeWorkflowId early so sendUserMessage routes to the right conversation.
        // Also sync workflowStore so sendChatMessage picks up the correct workflow ID
        // (it reads workflowStore.currentWorkflow?.id before chatStore.activeWorkflowId).
        useChatStore.getState().setActiveWorkflowId(id)
        setCurrentWorkflowId(id)

        // 1. Play Home Exit animation
        setHomeExited(true)

        // 2. Wait for exit animation (opacity/slide up) to finish
        await new Promise(resolve => setTimeout(resolve, 400))

        // 3. Navigate to route with ID
        navigate(`/workflow/${id}`)

        // 4. Trigger Workspace Reveal (sidebars slide in)
        triggerReveal()
    }, [navigate, setCurrentWorkflowId, setHomeExited, triggerReveal])

    // Home chatbox state
    const [homeChatInput, setHomeChatInput] = useState('')
    const [isHomeSending, setIsHomeSending] = useState(false)
    const homeFileInputRef = useRef<HTMLInputElement>(null)
    const homeImportInputRef = useRef<HTMLInputElement>(null)
    const [showImportModal, setShowImportModal] = useState(false)
    const [importJsonText, setImportJsonText] = useState('')
    const [importError, setImportError] = useState<string | null>(null)
    const [importValidationErrors, setImportValidationErrors] = useState<ValidationError[] | null>(null)
    const pendingImportActionRef = useRef<(() => Promise<void>) | null>(null)

    // Initialize session and streaming session state
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
        if (!authReady) {
            return
        }

        if (!workflowId) {
            loadedWorkflowIdRef.current = null
            useChatStore.getState().setActiveWorkflowId(null)
            clearPendingFiles()
            setCurrentWorkflow(null)
            setFlowchart({ nodes: [], edges: [] })
            setAnalysis(null)
            return
        }

        if (loadedWorkflowIdRef.current === workflowId) return

        let isActive = true

        const loadWorkflow = async () => {
            // Eagerly set the workflow ID so SSE event guards reject
            // events from the previous workflow during the async fetch.
            setCurrentWorkflowId(workflowId)

            try {
                const workflowData = await getWorkflow(workflowId)
                if (!isActive) return

                const { workflow, flowchart, analysis } = hydrateWorkflowDetail(workflowData)
                setCurrentWorkflow(workflow)
                setFlowchart(flowchart)
                setAnalysis(analysis)
                markSavedSnapshot()
                loadedWorkflowIdRef.current = workflowId

                // Set active workflow in chatStore so Chat.tsx reads this workflow's conversation.
                // All events (normal chat and builder) route to conversations[workflowId].
                const cs = useChatStore.getState()
                cs.setActiveWorkflowId(workflowId)

                // Restore conversation_id so new messages continue the same thread
                if (workflowData.conversation_id) {
                    cs.setConversationId(workflowId, workflowData.conversation_id)
                }

                // If a backend task is still running, set up streaming and polling.
                // Detect SPA navigation vs page refresh: after SPA nav, builder
                // events have already been flowing into chatStore (isStreaming/
                // streamingContent are set). After refresh, persist middleware
                // resets them to false/''. Only fire resumeTask on refresh.
                if (workflowData.building) {
                    const conv = cs.conversations?.[workflowId]
                    const needsResume = !conv?.isStreaming && !conv?.streamingContent

                    if (needsResume) {
                        // Page refresh — reconnect to the running task's SSE stream.
                        // resumeTask uses fetch/SSE, so no connection wait needed.
                        cs.setStreaming(workflowId, true)
                        cs.setProcessingStatus(workflowId, 'Reconnecting...')
                        import('../api/streamActions').then(({ resumeTask }) => {
                            if (isActive) resumeTask(workflowId)
                        })
                    }
                    // else: SPA navigation — events are already flowing, no resume needed
                }

                // Fetch conversation history (runs in parallel with resume above).
                // Merges any backend messages that arrived while the page was closed.
                const localMessages = cs.conversations?.[workflowId]?.messages ?? []
                if (workflowData.conversation_id) {
                    await syncConversationMessages(workflowId, workflowData.conversation_id)
                } else if (!localMessages.length && workflowData.building && workflowData.metadata?.description) {
                    // Building in progress, but the build_user_message stream event was
                    // missed (page refresh / late navigation). Recover the brief from
                    // the workflow description so the chat isn't empty.
                    cs.addMessage(workflowId, {
                        id: `brief_${Date.now()}`,
                        role: 'user',
                        content: workflowData.metadata.description,
                        timestamp: new Date().toISOString(),
                        tool_calls: [],
                    })
                }

                // Clear previous workflow's pending files before restoring new ones.
                // Without this, switching workflows accumulates images from all visited workflows.
                clearPendingFiles()

                // Restore uploaded files (images/PDFs) so they reappear after refresh.
                // Fetches each file from the backend uploads endpoint and converts
                // to a data URL for the image viewer.
                if (workflowData.uploaded_files?.length) {
                    for (const uf of workflowData.uploaded_files) {
                        try {
                            const resp = await fetch(`${API_BASE}/api/uploads/${uf.rel_path}`, {
                                credentials: 'include',
                                headers: { 'X-Session-Id': getSessionId() },
                            })
                            if (!resp.ok) continue
                            const blob = await resp.blob()
                            const dataUrl = await new Promise<string>((resolve) => {
                                const reader = new FileReader()
                                reader.onloadend = () => resolve(reader.result as string)
                                reader.readAsDataURL(blob)
                            })
                            addPendingFile({
                                id: `restored_${uf.rel_path}`,
                                name: uf.name,
                                dataUrl,
                                type: uf.file_type === 'pdf' ? 'pdf' : 'image',
                                purpose: (uf.purpose as 'flowchart' | 'guidance' | 'mixed' | 'unclassified') || 'unclassified',
                            })
                        } catch {
                            // Non-critical — skip files that can't be restored
                        }
                    }
                }

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
                    clearPendingFiles()
                    setCurrentWorkflowId(workflowId)
                    useChatStore.getState().setActiveWorkflowId(workflowId)
                    loadedWorkflowIdRef.current = workflowId
                    return
                }

                const msg = err instanceof Error ? err.message : 'Unknown error'
                setError(`Failed to load workflow (${workflowId}): ${msg}`)
            }
        }
        // Listen for task-finished from resumeTask — fires when resume discovers
        // the task already completed. Re-fetches final state from DB.
        const handleTaskFinished = async (e: Event) => {
            const detail = (e as CustomEvent).detail
            if (detail?.workflowId !== workflowId || !isActive) return
            try {
                const fresh = await getWorkflow(workflowId)
                const hydrated = hydrateWorkflowDetail(fresh)
                setFlowchart(hydrated.flowchart)
                setAnalysis(hydrated.analysis)
            } catch {
                // Best-effort — next page load will catch up from DB
            }
        }
        window.addEventListener('task-finished', handleTaskFinished)

        loadWorkflow()
        return () => {
            isActive = false
            window.removeEventListener('task-finished', handleTaskFinished)
        }
    }, [authReady, workflowId, setAnalysis, setCurrentWorkflow, setCurrentWorkflowId, setError, setFlowchart, triggerReveal, setHomeExited, addPendingFile, clearPendingFiles, markSavedSnapshot])

    // Re-fetch workflow when a background subworkflow build completes.
    // Loads final nodes/edges and merges conversation history (with tool calls).
    useEffect(() => {
        if (!workflowId) return

        const handleBuildComplete = async (e: Event) => {
            const detail = (e as CustomEvent).detail
            if (detail.workflowId !== workflowId) return

            try {
                const workflowData = await getWorkflow(workflowId)

                // Update flowchart with final state
                const fc = transformFlowchartFromBackend({
                    nodes: workflowData.nodes || [],
                    edges: workflowData.edges || [],
                })
                setFlowchart(fc)

                // Load messages via ConversationLogger (includes tool calls).
                if (workflowData.conversation_id) {
                    await syncConversationMessages(workflowId, workflowData.conversation_id)
                }
            } catch (err) {
                console.error('[WorkflowPage] Failed to re-fetch after build complete:', err)
            }
        }

        window.addEventListener('subworkflow-build-complete', handleBuildComplete)
        return () => window.removeEventListener('subworkflow-build-complete', handleBuildComplete)
    }, [workflowId, setFlowchart])

    // No cleanup needed on unmount — conversation state persists in chatStore
    // across navigations. In-flight streaming tasks continue emitting events.

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

        // Orchestrate exit sequence — sets activeWorkflowId BEFORE adding
        // the user message so sendUserMessage can route to the right conversation.
        await startWorkflowSession()

        // Add user message to store locally so it appears in chat history right away
        sendUserMessage(text)

        // Small delay to let the transition begin before opening the stream
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

    const completeImportedNavigation = useCallback(async (newId: string) => {
        loadedWorkflowIdRef.current = null
        useChatStore.getState().setActiveWorkflowId(newId)
        setCurrentWorkflowId(newId)
        setShowImportModal(false)
        setImportJsonText('')
        setImportError(null)
        setImportValidationErrors(null)
        pendingImportActionRef.current = null

        setHomeExited(true)
        await new Promise(resolve => setTimeout(resolve, 400))
        navigate(`/workflow/${newId}`)
        triggerReveal()
    }, [navigate, setCurrentWorkflowId, setHomeExited, triggerReveal])

    const handleImportFailure = useCallback((err: unknown, fallbackMessage: string) => {
        const importError = err as WorkflowImportError
        const validationErrors = Array.isArray(importError.validation_errors)
            ? importError.validation_errors
            : null
        setImportValidationErrors(validationErrors)
        setImportError(importError.message || fallbackMessage)
    }, [])

    const handleImportJson = useCallback(async () => {
        try {
            const payload = JSON.parse(importJsonText)
            const result = await importWorkflowJson(payload)
            await completeImportedNavigation(result.workflow_id)
        } catch (err) {
            try {
                const payload = JSON.parse(importJsonText)
                pendingImportActionRef.current = async () => {
                    const result = await importWorkflowJson(payload, true)
                    await completeImportedNavigation(result.workflow_id)
                }
            } catch {
                pendingImportActionRef.current = null
            }
            handleImportFailure(err, 'Invalid JSON')
        }
    }, [completeImportedNavigation, handleImportFailure, importJsonText])

    const handleImportAnyway = useCallback(async () => {
        if (!pendingImportActionRef.current) return
        try {
            await pendingImportActionRef.current()
        } catch (err) {
            handleImportFailure(err, 'Import failed')
        }
    }, [handleImportFailure])

    const handleImportFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        if (file.name.toLowerCase().endsWith('.zip')) {
            importWorkflowBundle(file)
                .then(result => completeImportedNavigation(result.workflow_id))
                .catch(err => {
                    pendingImportActionRef.current = async () => {
                        const result = await importWorkflowBundle(file, true)
                        await completeImportedNavigation(result.workflow_id)
                    }
                    handleImportFailure(err, 'Invalid workflow bundle')
                })

            if (homeImportInputRef.current) {
                homeImportInputRef.current.value = ''
            }
            return
        }

        const reader = new FileReader()
        reader.onload = async (event) => {
            try {
                const content = event.target?.result as string
                const payload = JSON.parse(content)
                const result = await importWorkflowJson(payload)
                await completeImportedNavigation(result.workflow_id)
            } catch (err) {
                try {
                    const payload = JSON.parse(event.target?.result as string)
                    pendingImportActionRef.current = async () => {
                        const result = await importWorkflowJson(payload, true)
                        await completeImportedNavigation(result.workflow_id)
                    }
                } catch {
                    pendingImportActionRef.current = null
                }
                handleImportFailure(err, 'Invalid JSON file')
            }
        }
        reader.onerror = () => {
            setImportError('Failed to read file')
        }
        reader.readAsText(file)

        if (homeImportInputRef.current) {
            homeImportInputRef.current.value = ''
        }
    }, [completeImportedNavigation, setImportError])

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

                        <button className="home-chip" onClick={() => setShowImportModal(true)}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                            Import
                        </button>
                    </div>
                </div>
            </div>

            <input
                ref={homeImportInputRef}
                type="file"
                accept=".json,.zip,application/json,application/zip"
                style={{ display: 'none' }}
                onChange={handleImportFileUpload}
            />

            {showImportModal && (
                <div className="json-modal-overlay" onClick={() => setShowImportModal(false)}>
                    <div className="json-modal" onClick={(e) => e.stopPropagation()}>
                        <h3>Import Workflow</h3>
                        <p className="muted small">Start a new session and load a workflow from JSON or a workflow bundle zip</p>
                        <button className="ghost full-width file-upload-btn" onClick={() => homeImportInputRef.current?.click()}>
                            Choose JSON or ZIP File
                        </button>
                        <div className="import-divider">
                            <span>or paste JSON</span>
                        </div>
                        <textarea
                            value={importJsonText}
                            onChange={(e) => {
                                setImportJsonText(e.target.value)
                                setImportError(null)
                                setImportValidationErrors(null)
                                pendingImportActionRef.current = null
                            }}
                            rows={10}
                        />
                        {importError && <p className="error-text">{importError}</p>}
                        {importValidationErrors && importValidationErrors.length > 0 && (
                            <div className="validation-warning">
                                <p className="muted small">The import is valid JSON, but the workflow failed strict validation:</p>
                                <ul>
                                    {importValidationErrors.map((error, index) => (
                                        <li key={`${error.code}-${index}`}>{error.code}: {error.message}</li>
                                    ))}
                                </ul>
                                <p className="muted small">You can still import this workflow, but it will be marked unvalidated.</p>
                            </div>
                        )}
                        <div className="json-modal-actions">
                            <button className="ghost" onClick={() => setShowImportModal(false)}>Cancel</button>
                            {importValidationErrors && importValidationErrors.length > 0 ? (
                                <button className="primary warning" onClick={handleImportAnyway}>Import Anyway</button>
                            ) : (
                                <button className="primary" onClick={handleImportJson} disabled={!importJsonText.trim()}>Import</button>
                            )}
                        </div>
                    </div>
                </div>
            )}

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
