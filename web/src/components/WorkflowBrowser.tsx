import { useState, useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { listWorkflows, getWorkflow, getDomains } from '../api/workflows'
import type { Workflow, Block } from '../types'

export default function WorkflowBrowser() {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [domains, setDomains] = useState<string[]>([])
  const [selectedDomain, setSelectedDomain] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { setCurrentWorkflow, setFlowchart } = useWorkflowStore()
  const { closeModal } = useUIStore()

  // Load workflows and domains on mount
  useEffect(() => {
    async function loadData() {
      setIsLoading(true)
      setError(null)
      try {
        const [workflowsData, domainsData] = await Promise.all([
          listWorkflows(),
          getDomains(),
        ])
        setWorkflows(workflowsData)
        setDomains(domainsData)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load workflows')
      } finally {
        setIsLoading(false)
      }
    }
    loadData()
  }, [])

  // Filter workflows
  const filteredWorkflows = workflows.filter((workflow) => {
    const matchesDomain =
      !selectedDomain || workflow.metadata.domain === selectedDomain
    const matchesSearch =
      !searchQuery ||
      workflow.metadata.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      workflow.metadata.description
        .toLowerCase()
        .includes(searchQuery.toLowerCase())
    return matchesDomain && matchesSearch
  })

  // Handle workflow selection
  const handleSelectWorkflow = async (workflowId: string) => {
    try {
      const workflow = await getWorkflow(workflowId)
      setCurrentWorkflow(workflow)

      // Convert workflow blocks to flowchart nodes/edges for canvas
      const nodes = workflow.blocks.map((block) => ({
        id: block.id,
        type: blockTypeToFlowType(block.type),
        label: getBlockLabel(block),
        x: block.position.x,
        y: block.position.y,
        color: 'teal' as const,
      }))

      const edges = workflow.connections.map((conn) => ({
        from: conn.from_block,
        to: conn.to_block,
        label: conn.from_port === 'default' ? '' : conn.from_port,
      }))

      setFlowchart({ nodes, edges })
      closeModal()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow')
    }
  }

  // Convert block type to flow node type
  function blockTypeToFlowType(blockType: string): 'start' | 'process' | 'decision' | 'subprocess' | 'end' {
    switch (blockType) {
      case 'input':
        return 'start'
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
      {/* Search and filter */}
      <div className="browser-filters">
        <input
          type="text"
          placeholder="Search workflows..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="search-input"
        />
        <select
          value={selectedDomain}
          onChange={(e) => setSelectedDomain(e.target.value)}
          className="domain-select"
        >
          <option value="">All domains</option>
          {domains.map((domain) => (
            <option key={domain} value={domain}>
              {domain}
            </option>
          ))}
        </select>
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
                <h4>{workflow.metadata.name}</h4>
                {workflow.metadata.is_validated && (
                  <span className="validated-badge" title="Validated">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                      <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                  </span>
                )}
              </div>
              <p className="workflow-description">{workflow.metadata.description}</p>
              <div className="workflow-meta">
                {workflow.metadata.domain && (
                  <span className="domain-tag">{workflow.metadata.domain}</span>
                )}
                {workflow.metadata.tags.slice(0, 3).map((tag) => (
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
