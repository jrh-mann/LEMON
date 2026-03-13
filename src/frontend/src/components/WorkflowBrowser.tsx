import { useState, useEffect, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { listWorkflows, getWorkflow, deleteWorkflow } from '../api/workflows'
import { hydrateWorkflowDetail } from '../utils/workflowHydration'
import type { WorkflowSummary } from '../types'

export default function WorkflowBrowser() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { setCurrentWorkflow, setFlowchart, setAnalysis, setWorkflows: setGlobalWorkflows } = useWorkflowStore()
  const { setZoomingCard, closeModal } = useUIStore()

  // Load workflows
  const loadWorkflows = useCallback(async () => {
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

  useEffect(() => {
    loadWorkflows()
  }, [loadWorkflows])

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

  const filteredWorkflows = workflows.filter(filterBySearch)

  // Handle workflow deletion
  const handleDeleteWorkflow = async (workflowId: string, workflowName: string, e: React.MouseEvent) => {
    e.stopPropagation()

    if (!confirm(`Delete workflow "${workflowName}"? This cannot be undone.`)) {
      return
    }

    try {
      await deleteWorkflow(workflowId)
      const updatedWorkflows = await listWorkflows()
      setWorkflows(updatedWorkflows)
      setGlobalWorkflows(updatedWorkflows)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete workflow')
    }
  }

  // Handle workflow selection
  const handleSelectWorkflow = async (workflowSummary: WorkflowSummary, e: React.MouseEvent) => {
    try {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
      setZoomingCard({
        id: workflowSummary.id,
        title: workflowSummary.name,
        rect
      })

      // Wait for BOTH the 100ms UI expansion AND the network fetch to complete
      const [workflowData] = await Promise.all([
        getWorkflow(workflowSummary.id),
        new Promise(resolve => setTimeout(resolve, 100))
      ])

      const { workflow, flowchart, analysis } = hydrateWorkflowDetail(workflowData)
      setCurrentWorkflow(workflow)
      setFlowchart(flowchart)
      setAnalysis(analysis)

      closeModal()

      // Small delay to let the modal close completely
      await new Promise(resolve => setTimeout(resolve, 100))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow')
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

  // Render workflow card
  const renderWorkflowCard = (workflow: WorkflowSummary) => (
    <div key={workflow.id} className="workflow-card-container">
      <button
        className="workflow-card"
        onClick={(e) => handleSelectWorkflow(workflow, e)}
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
      </button>

      {/* Delete button */}
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
    </div>
  )

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
          filteredWorkflows.map((workflow) => renderWorkflowCard(workflow))
        )}
      </div>
    </div>
  )
}
