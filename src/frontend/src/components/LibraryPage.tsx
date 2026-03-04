import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUIStore } from '../stores/uiStore'
import { listWorkflows, deleteWorkflow, listPublicWorkflows, voteOnWorkflow } from '../api/workflows'
import type { WorkflowSummary } from '../types'
import '../styles/LibraryPage.css'

type BrowserTab = 'mine' | 'published' | 'peer_review'

export default function LibraryPage() {
    const navigate = useNavigate()
    const { setZoomingCard, setZoomPhase } = useUIStore()

    const [activeTab, setActiveTab] = useState<BrowserTab>('mine')
    const [myWorkflows, setMyWorkflows] = useState<WorkflowSummary[] | null>(null)
    const [publicWorkflows, setPublicWorkflows] = useState<WorkflowSummary[] | null>(null)
    const [peerReviewWorkflows, setPeerReviewWorkflows] = useState<WorkflowSummary[] | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

    // Fetch workflows for a specific tab if not already loaded
    const fetchTabData = useCallback(async (tab: BrowserTab) => {
        // Skip if already loaded
        if (tab === 'mine' && myWorkflows !== null) return
        if (tab === 'published' && publicWorkflows !== null) return
        if (tab === 'peer_review' && peerReviewWorkflows !== null) return

        setIsLoading(true)
        try {
            switch (tab) {
                case 'mine':
                    const mineResult = await listWorkflows()
                    setMyWorkflows(mineResult)
                    break
                case 'published':
                    const publishedResult = await listPublicWorkflows('reviewed')
                    setPublicWorkflows(publishedResult.workflows)
                    break
                case 'peer_review':
                    const reviewResult = await listPublicWorkflows('unreviewed')
                    setPeerReviewWorkflows(reviewResult.workflows)
                    break
            }
        } catch (err) {
            console.error(`Failed to fetch ${tab} workflows:`, err)
        } finally {
            setIsLoading(false)
        }
    }, [myWorkflows, publicWorkflows, peerReviewWorkflows])

    // Load active tab data on mount or tab change
    useEffect(() => {
        fetchTabData(activeTab)
    }, [activeTab, fetchTabData])

    // Force refresh the active tab
    const refreshActiveTab = useCallback(async () => {
        setIsLoading(true)
        try {
            switch (activeTab) {
                case 'mine':
                    setMyWorkflows(await listWorkflows())
                    break
                case 'published':
                    const published = await listPublicWorkflows('reviewed')
                    setPublicWorkflows(published.workflows)
                    break
                case 'peer_review':
                    const review = await listPublicWorkflows('unreviewed')
                    setPeerReviewWorkflows(review.workflows)
                    break
            }
        } catch { /* ignore */ }
        finally { setIsLoading(false) }
    }, [activeTab])

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
            // Refresh current tab
            await refreshActiveTab()
        } catch (err) {
            console.error('Failed to delete:', err)
        }
    }, [refreshActiveTab])

    // Handle vote
    const handleVote = useCallback(async (id: string, vote: number) => {
        try {
            await voteOnWorkflow(id, vote)
            // Refresh current tab
            await refreshActiveTab()
        } catch (err) {
            console.error('Failed to vote:', err)
        }
    }, [refreshActiveTab])

    const getDisplayWorkflows = () => {
        let list: WorkflowSummary[] | null = null
        switch (activeTab) {
            case 'mine': list = myWorkflows; break
            case 'published': list = publicWorkflows; break
            case 'peer_review': list = peerReviewWorkflows; break
        }
        if (!list) return []
        return list.filter(filterBySearch)
    }

    const workflows = getDisplayWorkflows()
    const isTabLoaded = (activeTab === 'mine' && myWorkflows !== null) ||
                       (activeTab === 'published' && publicWorkflows !== null) ||
                       (activeTab === 'peer_review' && peerReviewWorkflows !== null)

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
                <h1 className="library-title">Library</h1>
                <div className="library-header-right" />
            </header>

            <div className="library-body">
                {/* Tabs */}
                <div className="library-tabs">
                    {(['mine', 'published', 'peer_review'] as BrowserTab[]).map(tab => (
                        <button
                            key={tab}
                            className={`library-tab ${activeTab === tab ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab)}
                        >
                            {tab === 'mine' ? 'My Workflows' : tab === 'published' ? 'Published' : 'Peer Review'}
                            <span className="library-tab-count">
                                {tab === 'mine' ? (myWorkflows?.length ?? '...') : 
                                 tab === 'published' ? (publicWorkflows?.length ?? '...') : 
                                 (peerReviewWorkflows?.length ?? '...')}
                            </span>
                        </button>
                    ))}
                </div>

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
                {!isTabLoaded && isLoading ? (
                    <div className="library-loading">
                        <div className="spinner-small" />
                        <span>Loading {activeTab === 'mine' ? 'your' : activeTab} workflows...</span>
                    </div>
                ) : workflows.length === 0 ? (
                    <div className="library-empty">
                        <p>{searchQuery ? 'No workflows match your search.' : 'No workflows found.'}</p>
                        {activeTab === 'mine' && !searchQuery && (
                            <button className="primary" onClick={() => navigate('/workflow')}>
                                Create your first workflow
                            </button>
                        )}
                    </div>
                ) : (
                    <div className="library-grid">
                        {workflows.map(wf => (
                            <div key={wf.id} className="library-card" onClick={(e) => handleSelect(wf, e)}>
                                <div className="library-card-header">
                                    <h3 className="library-card-name">
                                        {wf.name}
                                        {wf.building && (
                                            <span className="library-card-building">Building...</span>
                                        )}
                                    </h3>
                                    {activeTab === 'mine' && (
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
                                    )}
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
                                {activeTab === 'peer_review' && (
                                    <div className="library-card-votes">
                                        <button
                                            className={`vote-btn ${wf.user_vote === 1 ? 'voted' : ''}`}
                                            onClick={(e) => { e.stopPropagation(); handleVote(wf.id, wf.user_vote === 1 ? 0 : 1) }}
                                        >
                                            ▲ {(wf.net_votes || 0) > 0 ? `+${wf.net_votes}` : wf.net_votes || 0}
                                        </button>
                                        <button
                                            className={`vote-btn down ${wf.user_vote === -1 ? 'voted' : ''}`}
                                            onClick={(e) => { e.stopPropagation(); handleVote(wf.id, wf.user_vote === -1 ? 0 : -1) }}
                                        >
                                            ▼
                                        </button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
