import { useState, useEffect, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { listWorkflows, getWorkflow, deleteWorkflow, listPublicWorkflows, voteOnWorkflow } from '../api/workflows'
import { autoLayoutFlowchart } from '../utils/canvas'
import type { WorkflowSummary, Block, FlowNode, Flowchart, WorkflowAnalysis, Workflow } from '../types'

// Tab options for the workflow browser
type BrowserTab = 'my-workflows' | 'peer-review' | 'published'

export default function WorkflowBrowser() {
  // Tab state
  const [activeTab, setActiveTab] = useState<BrowserTab>('my-workflows')

  // My Workflows state
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])

  // Peer Review state (all published workflows - users can vote on any)
  const [peerReviewWorkflows, setPeerReviewWorkflows] = useState<WorkflowSummary[]>([])
  // Published state (reviewed workflows)
  const [publishedWorkflows, setPublishedWorkflows] = useState<WorkflowSummary[]>([])
  const [userVotes, setUserVotes] = useState<Record<string, number>>({})  // workflow_id -> vote (+1/-1)
  const [votingId, setVotingId] = useState<string | null>(null)  // ID of workflow currently being voted on
  const [publishThreshold, setPublishThreshold] = useState<number>(1)  // Votes needed for "reviewed" status

  // Common state
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { addTab, setAnalysis, setWorkflows: setGlobalWorkflows } = useWorkflowStore()
  const { closeModal } = useUIStore()

  // Load my workflows
  const loadMyWorkflows = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const workflowsData = await listWorkflows()
      setWorkflows(workflowsData)
      setGlobalWorkflows(workflowsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflows')
    } finally {
      setIsLoading(false)
    }
  }, [setGlobalWorkflows])

  // Load all published workflows for peer review (users can vote on any)
  const loadPeerReviewWorkflows = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      // Load ALL published workflows - voting is allowed on all
      const { workflows: workflowsData, publishThreshold: threshold } = await listPublicWorkflows()
      setPeerReviewWorkflows(workflowsData)
      setPublishThreshold(threshold)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflows for review')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Load published (reviewed) workflows
  const loadPublishedWorkflows = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const { workflows: workflowsData, publishThreshold: threshold } = await listPublicWorkflows('reviewed')
      setPublishedWorkflows(workflowsData)
      setPublishThreshold(threshold)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load published workflows')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Load data based on active tab
  useEffect(() => {
    if (activeTab === 'my-workflows') {
      loadMyWorkflows()
    } else if (activeTab === 'peer-review') {
      loadPeerReviewWorkflows()
    } else {
      loadPublishedWorkflows()
    }
  }, [activeTab, loadMyWorkflows, loadPeerReviewWorkflows, loadPublishedWorkflows])

  // Handle voting on a public workflow
  const handleVote = useCallback(async (workflowId: string, vote: number, e: React.MouseEvent) => {
    e.stopPropagation()  // Prevent opening the workflow
    setVotingId(workflowId)

    try {
      // If clicking the same vote, remove it (toggle off)
      const currentVote = userVotes[workflowId] || 0
      const newVote = currentVote === vote ? 0 : vote

      const result = await voteOnWorkflow(workflowId, newVote)

      // Update local state
      setUserVotes(prev => ({
        ...prev,
        [workflowId]: result.user_vote ?? 0
      }))

      // Update workflow in peer review list with new vote count and status
      // Workflows stay in the list regardless of review status - users can continue voting
      setPeerReviewWorkflows(prev => prev.map(w =>
        w.id === workflowId
          ? { ...w, net_votes: result.net_votes, review_status: result.review_status }
          : w
      ))

      // Also update published list if the workflow is there
      setPublishedWorkflows(prev => {
        // If promoted to reviewed, add to published list if not already there
        if (result.review_status === 'reviewed') {
          const exists = prev.some(w => w.id === workflowId)
          if (!exists) {
            const workflow = peerReviewWorkflows.find(w => w.id === workflowId)
            if (workflow) {
              return [...prev, { ...workflow, net_votes: result.net_votes, review_status: result.review_status }]
            }
          }
          return prev.map(w =>
            w.id === workflowId
              ? { ...w, net_votes: result.net_votes, review_status: result.review_status }
              : w
          )
        } else {
          // If demoted to unreviewed, remove from published list
          return prev.filter(w => w.id !== workflowId)
        }
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to vote')
    } finally {
      setVotingId(null)
    }
  }, [userVotes, peerReviewWorkflows])

  // Filter workflows by search query
  const filterBySearch = (workflow: WorkflowSummary) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      workflow.name.toLowerCase().includes(query) ||
      workflow.description.toLowerCase().includes(query) ||
      workflow.domain?.toLowerCase().includes(query)
    )
  }

  // Filtered lists for each tab
  const filteredMyWorkflows = workflows.filter(filterBySearch)
  const filteredPeerReviewWorkflows = peerReviewWorkflows.filter(filterBySearch)
  const filteredPublishedWorkflows = publishedWorkflows.filter(filterBySearch)

  // Handle workflow deletion
  const handleDeleteWorkflow = async (workflowId: string, workflowName: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent opening the workflow

    if (!confirm(`Delete workflow "${workflowName}"? This cannot be undone.`)) {
      return
    }

    try {
      await deleteWorkflow(workflowId)
      // Refresh the list
      const updatedWorkflows = await listWorkflows()
      setWorkflows(updatedWorkflows)
      // Also update the global store
      setGlobalWorkflows(updatedWorkflows)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete workflow')
    }
  }

  // Handle workflow selection - opens in new tab
  const handleSelectWorkflow = async (workflowId: string) => {
    try {
      const workflowData: any = await getWorkflow(workflowId)

      // Workflow can be in two formats:
      // 1. Old format: blocks/connections (Block-based)
      // 2. New format: nodes/edges (Flowchart-based)
      let flowchart: Flowchart

      if (workflowData.blocks && workflowData.connections) {
        // Old format: convert blocks to flowchart nodes
        const nodes: FlowNode[] = workflowData.blocks.map((block: Block) => ({
          id: block.id,
          type: blockTypeToFlowType(block.type),
          label: getBlockLabel(block),
          x: block.position.x,
          y: block.position.y,
          color: getBlockColor(block.type),
        }))

        const edges = workflowData.connections.map((conn: any) => ({
          from: conn.from_block,
          to: conn.to_block,
          label: conn.from_port === 'default' ? '' : conn.from_port,
        }))

        flowchart = { nodes, edges }
      } else {
        // New format: use nodes/edges directly
        flowchart = {
          nodes: workflowData.nodes || [],
          edges: workflowData.edges || [],
        }
      }

      // Check if positions are all at (0,0) or overlapping - apply auto-layout
      const needsLayout = flowchart.nodes.length > 1 &&
        (flowchart.nodes.every((n) => n.x === 0 && n.y === 0) ||
         new Set(flowchart.nodes.map((n) => `${n.x},${n.y}`)).size < flowchart.nodes.length / 2)

      if (needsLayout) {
        flowchart = autoLayoutFlowchart(flowchart)
      }

      // Open workflow in a new tab
      // Create a proper Workflow object with empty blocks/connections
      // (we only need the flowchart for rendering)
      const workflow: Workflow = {
        id: workflowData.id,
        metadata: workflowData.metadata,
        blocks: [],
        connections: [],
      }

      addTab(workflowData.metadata.name, workflow, flowchart)

      // Set analysis data if available (map backend 'inputs' to frontend 'variables')
      if (workflowData.inputs || workflowData.outputs || workflowData.tree || workflowData.doubts) {
        const analysis: WorkflowAnalysis = {
          variables: workflowData.inputs || [],  // Backend sends 'inputs', frontend uses 'variables'
          outputs: workflowData.outputs || [],
          tree: workflowData.tree || {},
          doubts: workflowData.doubts || [],
        }
        setAnalysis(analysis)
      }

      closeModal()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow')
    }
  }

  // Get color for block type
  function getBlockColor(blockType: string): 'teal' | 'amber' | 'green' | 'slate' | 'rose' | 'sky' {
    switch (blockType) {
      case 'input': return 'teal'
      case 'decision': return 'amber'
      case 'output': return 'green'
      case 'workflow_ref': return 'sky'
      default: return 'teal'
    }
  }

  // Convert block type to flow node type
  function blockTypeToFlowType(blockType: string): 'start' | 'process' | 'decision' | 'subprocess' | 'end' {
    switch (blockType) {
      case 'input':
        return 'process'
      case 'decision':
        return 'decision'
      case 'output':
        return 'end'
      case 'workflow_ref':
        return 'subprocess'
      default:
        return 'process'
    }
  }

  // Get display label for block
  function getBlockLabel(block: Block): string {
    switch (block.type) {
      case 'input':
        return block.name
      case 'decision':
        return block.condition
      case 'output':
        return block.value
      case 'workflow_ref':
        return block.ref_name
    }
  }

  if (isLoading) {
    return (
      <div className="workflow-browser loading">
        <p className="muted">Loading workflows...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="workflow-browser error">
        <p className="error-text">{error}</p>
        <button onClick={() => window.location.reload()}>Retry</button>
      </div>
    )
  }

  // Render workflow card (shared between tabs)
  // showVoting: show vote buttons (Peer Review tab)
  // showVoteCount: show vote count without buttons (Published tab)
  const renderWorkflowCard = (workflow: WorkflowSummary, showVoting: boolean, showVoteCount: boolean = false) => (
    <div key={workflow.id} className="workflow-card-container">
      <button
        className="workflow-card"
        onClick={() => handleSelectWorkflow(workflow.id)}
      >
        <div className="workflow-card-header">
          <h4>{workflow.name}</h4>
          <div className="workflow-card-badges">
            {workflow.is_validated && (
              <span className="validated-badge" title="Validated">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </span>
            )}
            {showVoting && workflow.review_status === 'reviewed' && (
              <span className="reviewed-badge" title="Has enough votes to appear in Published">✓ Published</span>
            )}
          </div>
        </div>
        <p className="workflow-description">{workflow.description}</p>
        <div className="workflow-meta">
          {workflow.domain && (
            <span className="domain-tag">{workflow.domain}</span>
          )}
          {workflow.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="tag">
              {tag}
            </span>
          ))}
        </div>

        {/* Vote count display for peer review and published tabs */}
        {(showVoting || showVoteCount) && (
          <div className="workflow-votes">
            <span className={`vote-count ${(workflow.net_votes ?? 0) >= publishThreshold ? 'positive' : (workflow.net_votes ?? 0) < 0 ? 'negative' : ''}`}>
              {(workflow.net_votes ?? 0) > 0 ? '+' : ''}{workflow.net_votes ?? 0} / {publishThreshold} votes
            </span>
            {showVoting && workflow.review_status === 'unreviewed' && (
              <span className="votes-needed">
                ({publishThreshold - (workflow.net_votes ?? 0)} more to publish)
              </span>
            )}
          </div>
        )}
      </button>

      {/* Vote buttons for peer review */}
      {showVoting && (
        <div className="voting-buttons">
          <button
            className={`vote-btn upvote ${userVotes[workflow.id] === 1 ? 'active' : ''}`}
            onClick={(e) => handleVote(workflow.id, 1, e)}
            disabled={votingId === workflow.id}
            title="Upvote"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 19V6M5 12l7-7 7 7" />
            </svg>
          </button>
          <button
            className={`vote-btn downvote ${userVotes[workflow.id] === -1 ? 'active' : ''}`}
            onClick={(e) => handleVote(workflow.id, -1, e)}
            disabled={votingId === workflow.id}
            title="Downvote"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v13M5 12l7 7 7-7" />
            </svg>
          </button>
        </div>
      )}

      {/* Delete button (only for my workflows) */}
      {!showVoting && (
        <button
          className="workflow-delete-btn"
          onClick={(e) => handleDeleteWorkflow(workflow.id, workflow.name, e)}
          title="Delete workflow"
          aria-label={`Delete ${workflow.name}`}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <line x1="10" y1="11" x2="10" y2="17" />
            <line x1="14" y1="11" x2="14" y2="17" />
          </svg>
        </button>
      )}
    </div>
  )

  return (
    <div className="workflow-browser">
      {/* Tabs */}
      <div className="browser-tabs">
        <button
          className={`tab-btn ${activeTab === 'my-workflows' ? 'active' : ''}`}
          onClick={() => setActiveTab('my-workflows')}
        >
          My Workflows
        </button>
        <button
          className={`tab-btn ${activeTab === 'peer-review' ? 'active' : ''}`}
          onClick={() => setActiveTab('peer-review')}
        >
          Peer Review
        </button>
        <button
          className={`tab-btn ${activeTab === 'published' ? 'active' : ''}`}
          onClick={() => setActiveTab('published')}
        >
          Published
        </button>
      </div>

      {/* Search */}
      <div className="browser-filters">
        <input
          type="text"
          placeholder="Search workflows..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="search-input"
        />
      </div>

      {/* Peer review info banner */}
      {activeTab === 'peer-review' && (
        <div className="peer-review-info">
          <p>
            <strong>Help review community workflows!</strong> Workflows with {publishThreshold}+ net upvotes
            appear in Published. Continue voting to adjust their visibility.
          </p>
        </div>
      )}

      {/* Workflow list */}
      <div className="workflow-list">
        {activeTab === 'my-workflows' && (
          // My Workflows list
          filteredMyWorkflows.length === 0 ? (
            <p className="muted">No workflows found</p>
          ) : (
            filteredMyWorkflows.map((workflow) => renderWorkflowCard(workflow, false))
          )
        )}
        {activeTab === 'peer-review' && (
          // Peer Review list (all published - with voting)
          filteredPeerReviewWorkflows.length === 0 ? (
            <p className="muted">No workflows to review</p>
          ) : (
            filteredPeerReviewWorkflows.map((workflow) => renderWorkflowCard(workflow, true))
          )
        )}
        {activeTab === 'published' && (
          // Published list (reviewed - show vote count but no voting buttons)
          filteredPublishedWorkflows.length === 0 ? (
            <p className="muted">No published workflows yet</p>
          ) : (
            filteredPublishedWorkflows.map((workflow) => renderWorkflowCard(workflow, false, true))
          )
        )}
      </div>
    </div>
  )
}
