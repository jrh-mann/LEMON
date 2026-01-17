import { useState, useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { listWorkflows, getWorkflow } from '../api/workflows'
import { autoLayoutFlowchart } from '../utils/canvas'
import type { WorkflowSummary, Block, FlowNode, Flowchart } from '../types'

export default function WorkflowBrowser() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { addTab } = useWorkflowStore()
  const { closeModal } = useUIStore()

  // Load workflows on mount
  useEffect(() => {
    async function loadData() {
      setIsLoading(true)
      setError(null)
      try {
        const workflowsData = await listWorkflows()
        setWorkflows(workflowsData)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load workflows')
      } finally {
        setIsLoading(false)
      }
    }
    loadData()
  }, [])

  // Filter workflows by search query
  const filteredWorkflows = workflows.filter((workflow) => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      workflow.name.toLowerCase().includes(query) ||
      workflow.description.toLowerCase().includes(query) ||
      workflow.domain?.toLowerCase().includes(query)
    )
  })

  // Handle workflow selection - opens in new tab
  const handleSelectWorkflow = async (workflowId: string) => {
    try {
      const workflow = await getWorkflow(workflowId)

      // Convert workflow blocks to flowchart nodes/edges for canvas
      const nodes: FlowNode[] = workflow.blocks.map((block) => ({
        id: block.id,
        type: blockTypeToFlowType(block.type),
        label: getBlockLabel(block),
        x: block.position.x,
        y: block.position.y,
        color: getBlockColor(block.type),
      }))

      const edges = workflow.connections.map((conn) => ({
        from: conn.from_block,
        to: conn.to_block,
        label: conn.from_port === 'default' ? '' : conn.from_port,
      }))

      let flowchart: Flowchart = { nodes, edges }

      // Check if positions are all at (0,0) or overlapping - apply auto-layout
      const needsLayout = nodes.length > 1 && nodes.every((n) => n.x === 0 && n.y === 0)
        || new Set(nodes.map((n) => `${n.x},${n.y}`)).size < nodes.length / 2

      if (needsLayout) {
        flowchart = autoLayoutFlowchart(flowchart)
      }

      // Open workflow in a new tab
      addTab(workflow.metadata.name, workflow, flowchart)
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

  return (
    <div className="workflow-browser">
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

      {/* Workflow list */}
      <div className="workflow-list">
        {filteredWorkflows.length === 0 ? (
          <p className="muted">No workflows found</p>
        ) : (
          filteredWorkflows.map((workflow) => (
            <button
              key={workflow.id}
              className="workflow-card"
              onClick={() => handleSelectWorkflow(workflow.id)}
            >
              <div className="workflow-card-header">
                <h4>{workflow.name}</h4>
                {workflow.is_validated && (
                  <span className="validated-badge" title="Validated">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                      <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                  </span>
                )}
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
            </button>
          ))
        )}
      </div>
    </div>
  )
}
