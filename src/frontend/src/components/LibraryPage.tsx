import { useState, useEffect, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { listWorkflows, getWorkflow, deleteWorkflow, listPublicWorkflows, voteOnWorkflow } from '../api/workflows'
import { autoLayoutFlowchart } from '../utils/canvas'
import type { WorkflowSummary, FlowNode, WorkflowAnalysis, Workflow } from '../types'
import '../styles/LibraryPage.css'

type BrowserTab = 'mine' | 'published' | 'peer_review'

export default function LibraryPage() {
    const { setCurrentWorkflow, setFlowchart, setAnalysis } = useWorkflowStore()

    const [activeTab, setActiveTab] = useState<BrowserTab>('mine')
    const [myWorkflows, setMyWorkflows] = useState<WorkflowSummary[]>([])
    const [publicWorkflows, setPublicWorkflows] = useState<WorkflowSummary[]>([])
    const [peerReviewWorkflows, setPeerReviewWorkflows] = useState<WorkflowSummary[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [searchQuery, setSearchQuery] = useState('')
    const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

    // Fetch workflows
    const fetchWorkflows = useCallback(async () => {
        setIsLoading(true)
        try {
            const [mineResult, publishedResult, reviewResult] = await Promise.all([
                listWorkflows(),
                listPublicWorkflows('reviewed'),
                listPublicWorkflows('unreviewed'),
            ])
            setMyWorkflows(mineResult)
            setPublicWorkflows(publishedResult.workflows)
            setPeerReviewWorkflows(reviewResult.workflows)
        } catch {
            // ignore
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => { fetchWorkflows() }, [fetchWorkflows])

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
    const handleSelect = useCallback(async (workflowId: string) => {
        try {
            const data: any = await getWorkflow(workflowId)

            const workflow: Workflow = {
                id: data.id,
                metadata: data.metadata,
                blocks: [],
                connections: [],
            }
            setCurrentWorkflow(workflow)

            let nodes: FlowNode[] = (data.nodes || []).map((n: any) => ({
                id: n.id,
                type: n.type === 'input' ? 'start' : n.type === 'output' ? 'end' : n.type || 'process',
                label: n.label || n.name || 'Node',
                x: typeof n.x === 'number' ? n.x : 400,
                y: typeof n.y === 'number' ? n.y : 200,
                color: n.color || 'teal',
                condition: n.condition,
                subworkflow_id: n.subworkflow_id,
                input_mapping: n.input_mapping,
                output_variable: n.output_variable,
                output_type: n.output_type,
                output_template: n.output_template,
                calculation: n.calculation,
            }))
            const edges = (data.edges || []).map((e: any) => ({
                from: e.from || e.source,
                to: e.to || e.target,
                label: e.label || '',
            }))

            // Auto-layout if no positions
            const needsLayout = nodes.length > 0 && nodes.every(n => n.x === 400 && n.y === 200)
            if (needsLayout) {
                const laid = autoLayoutFlowchart({ nodes, edges })
                nodes = laid.nodes
            }

            setFlowchart({ nodes, edges })

            const analysis: WorkflowAnalysis = {
                variables: data.inputs || data.variables || [],
                outputs: data.outputs || [],
                tree: data.tree || {},
                doubts: data.doubts || [],
            }
            setAnalysis(analysis)

            // Navigate to workflow
            window.location.hash = '#/workflow'
        } catch (err) {
            console.error('Failed to open workflow:', err)
        }
    }, [setCurrentWorkflow, setFlowchart, setAnalysis])

    // Handle delete
    const handleDelete = useCallback(async (id: string) => {
        try {
            await deleteWorkflow(id)
            setDeleteConfirm(null)
            fetchWorkflows()
        } catch (err) {
            console.error('Failed to delete:', err)
        }
    }, [fetchWorkflows])

    // Handle vote
    const handleVote = useCallback(async (id: string, vote: number) => {
        try {
            await voteOnWorkflow(id, vote)
            fetchWorkflows()
        } catch (err) {
            console.error('Failed to vote:', err)
        }
    }, [fetchWorkflows])

    const getDisplayWorkflows = () => {
        switch (activeTab) {
            case 'mine': return myWorkflows.filter(filterBySearch)
            case 'published': return publicWorkflows.filter(filterBySearch)
            case 'peer_review': return peerReviewWorkflows.filter(filterBySearch)
        }
    }

    const workflows = getDisplayWorkflows()

    return (
        <div className="library-page">
            <header className="library-header">
                <div className="library-header-left">
                    <button className="ghost library-back-btn" onClick={() => { window.location.hash = '#/home' }}>
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
                                {tab === 'mine' ? myWorkflows.length : tab === 'published' ? publicWorkflows.length : peerReviewWorkflows.length}
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
                {isLoading ? (
                    <div className="library-loading">
                        <div className="spinner-small" />
                        <span>Loading workflows...</span>
                    </div>
                ) : workflows.length === 0 ? (
                    <div className="library-empty">
                        <p>No workflows found.</p>
                        {activeTab === 'mine' && (
                            <button className="primary" onClick={() => { window.location.hash = '#/workflow' }}>
                                Create your first workflow
                            </button>
                        )}
                    </div>
                ) : (
                    <div className="library-grid">
                        {workflows.map(wf => (
                            <div key={wf.id} className="library-card" onClick={() => handleSelect(wf.id)}>
                                <div className="library-card-header">
                                    <h3 className="library-card-name">{wf.name}</h3>
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
