import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { listWorkflows, deleteWorkflow } from '../api/workflows'
import type { WorkflowSummary } from '../types'
import '../styles/LibraryPage.css'

export default function LibraryPage() {
    const navigate = useNavigate()
    const { setZoomingCard, setZoomPhase } = useUIStore()
    // When streaming handlers signal library changes (subworkflow created/finished),
    // this counter increments and triggers a re-fetch
    const libraryRefreshTrigger = useWorkflowStore(s => s.libraryRefreshTrigger)

    const [workflows, setWorkflows] = useState<WorkflowSummary[] | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

    // Fetch workflows
    const fetchWorkflows = useCallback(async () => {
        if (workflows !== null) return
        setIsLoading(true)
        try {
            const result = await listWorkflows()
            setWorkflows(result)
        } catch (err) {
            console.error('Failed to fetch workflows:', err)
        } finally {
            setIsLoading(false)
        }
    }, [workflows])

    // Load on mount
    useEffect(() => {
        fetchWorkflows()
    }, [fetchWorkflows])

    // When streaming events signal library changes, invalidate cache
    useEffect(() => {
        if (libraryRefreshTrigger === 0) return // skip initial render
        setWorkflows(null)
    }, [libraryRefreshTrigger])

    // Force refresh
    const refreshWorkflows = useCallback(async () => {
        setIsLoading(true)
        try {
            setWorkflows(await listWorkflows())
        } catch { /* ignore */ }
        finally { setIsLoading(false) }
    }, [])

    // Filter by search
    const filterBySearch = (wf: WorkflowSummary) => {
        if (!searchQuery.trim()) return true
        const q = searchQuery.toLowerCase()
        return (
            wf.name.toLowerCase().includes(q) ||
            wf.description.toLowerCase().includes(q) ||
            wf.tags?.some(t => t.toLowerCase().includes(q))
        )
    }

    // Handle workflow selection - open in workflow page
    const handleSelect = useCallback(async (workflowSummary: WorkflowSummary, e: React.MouseEvent) => {
        try {
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            setZoomingCard({
                id: workflowSummary.id,
                title: workflowSummary.name,
                rect
            })

            // Give the transition layer 150ms to expand and cover the screen
            // before we actually switch routes and unmount LibraryPage
            setTimeout(() => {
                navigate(`/workflow/${workflowSummary.id}`)

                // Once we are on the new page, trigger the fade out
                setTimeout(() => {
                    setZoomPhase('fading')
                }, 50)
            }, 150)
        } catch (err) {
            console.error('Failed to open workflow:', err)
        }
    }, [setZoomingCard, setZoomPhase, navigate])

    // Handle delete
    const handleDelete = useCallback(async (id: string) => {
        try {
            await deleteWorkflow(id)
            setDeleteConfirm(null)
            await refreshWorkflows()
        } catch (err) {
            console.error('Failed to delete:', err)
        }
    }, [refreshWorkflows])

    const displayWorkflows = (workflows ?? []).filter(filterBySearch)

    return (
        <div className="library-page">
            <header className="library-header">
                <div className="library-header-left">
                    <button className="ghost library-back-btn" onClick={() => navigate('/workflow')}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        Back
                    </button>
                    <div className="logo">
                        <span className="logo-mark">L</span>
                        <span className="logo-text">LEMON</span>
                    </div>
                </div>
                <h1 className="library-title">My Workflows</h1>
                <div className="library-header-right" />
            </header>

            <div className="library-body">
                {/* Search */}
                <div className="library-search">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="11" cy="11" r="8" />
                        <path d="M21 21l-4.35-4.35" />
                    </svg>
                    <input
                        type="text"
                        placeholder="Search workflows..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>

                {/* Grid */}
                {workflows === null && isLoading ? (
                    <div className="library-loading">
                        <div className="spinner-small" />
                        <span>Loading your workflows...</span>
                    </div>
                ) : displayWorkflows.length === 0 ? (
                    <div className="library-empty">
                        <p>{searchQuery ? 'No workflows match your search.' : 'No workflows found.'}</p>
                        {!searchQuery && (
                            <button className="primary" onClick={() => navigate('/workflow')}>
                                Create your first workflow
                            </button>
                        )}
                    </div>
                ) : (
                    <div className="library-grid">
                        {displayWorkflows.map(wf => (
                            <div key={wf.id} className="library-card" onClick={(e) => handleSelect(wf, e)}>
                                <div className="library-card-header">
                                    <h3 className="library-card-name">
                                        {wf.name}
                                        {wf.building && (
                                            <span className="library-card-building">Building...</span>
                                        )}
                                    </h3>
                                    <button
                                        className="library-card-delete"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            if (deleteConfirm === wf.id) {
                                                handleDelete(wf.id)
                                            } else {
                                                setDeleteConfirm(wf.id)
                                                setTimeout(() => setDeleteConfirm(null), 3000)
                                            }
                                        }}
                                        title={deleteConfirm === wf.id ? 'Click again to confirm' : 'Delete workflow'}
                                    >
                                        {deleteConfirm === wf.id ? '✓ Confirm' : '✕'}
                                    </button>
                                </div>
                                {wf.description && (
                                    <p className="library-card-desc">{wf.description}</p>
                                )}
                                <div className="library-card-meta">
                                    {wf.domain && (
                                        <span className="library-card-domain">{wf.domain}</span>
                                    )}
                                    {wf.tags?.slice(0, 3).map(tag => (
                                        <span key={tag} className="library-card-tag">{tag}</span>
                                    ))}
                                    {wf.is_validated && (
                                        <span className="library-card-validated">✓ Validated</span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
