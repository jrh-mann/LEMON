import { useState, useCallback, useEffect, useRef } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { listWorkflows } from '../api/workflows'
import VariableModal from './VariableModal'
import type {
  InputType,
  VariableSource,
  WorkflowAnalysis,
  WorkflowVariable,
  FlowNode,
} from '../types'

/** Node configuration editors — extracted into node-config/ package */
import {
  EndNodeConfig,
  SubprocessConfig,
  DecisionConditionEditor,
  CalculationConfigEditor,
} from './node-config'

/* ── Helpers ─────────────────────────────────────────────── */

/** SVG icon per variable data-type — keeps the palette consistent */
const TYPE_ICONS: Record<InputType, React.ReactNode> = {
  number: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="var-type-icon">
      <path d="M7 20l4-16M17 4l-4 16M3 12h18M3 8h18" />
    </svg>
  ),
  string: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="var-type-icon">
      <path d="M4 7V4h16v3M9 20h6M12 4v16" />
    </svg>
  ),
  bool: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="var-type-icon">
      <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
    </svg>
  ),
  date: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="var-type-icon">
      <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  ),
  enum: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="var-type-icon">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  ),
}

/** Human-readable label for variable source */
const SOURCE_LABELS: Record<VariableSource, string> = {
  input: 'Input',
  subprocess: 'Subprocess',
  calculated: 'Calculated',
  constant: 'Constant',
}

/** Human-readable label for variable type */
const TYPE_LABELS: Record<InputType, string> = {
  number: 'Number',
  string: 'String',
  bool: 'Boolean',
  date: 'Date',
  enum: 'Enum',
}

const DEFAULT_WIDTH = 200
const MIN_WIDTH = 0

export default function RightSidebar() {
  const {
    currentWorkflow,
    currentAnalysis,
    setAnalysis,
    selectedNodeId,
    selectedEdge,
    flowchart,
    updateNode,
    updateEdgeLabel,
    workflows,
    setWorkflows,
  } = useWorkflowStore()

  /* ── Resizable sidebar state (mirrors Palette) ───────── */
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      // Width = distance from right edge of viewport to cursor
      const newWidth = window.innerWidth - e.clientX
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(newWidth, window.innerWidth * 0.4))
      setSidebarWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      // Snap to closed if very small
      setSidebarWidth(prev => (prev < 40 ? 0 : prev))
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ew-resize'

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [isResizing])

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  // Load library workflows for subprocess node config
  useEffect(() => {
    listWorkflows().then(setWorkflows).catch(() => {})
  }, [setWorkflows])

  /* ── Derived state ────────────────────────────────────── */
  const analysisInputs: WorkflowVariable[] = currentAnalysis?.variables || []
  const effectiveAnalysis: WorkflowAnalysis = currentAnalysis ?? {
    variables: [],
    outputs: [],
    output_type: currentWorkflow?.output_type || 'string',
  }
  const isCollapsed = sidebarWidth === 0

  const selectedNode: FlowNode | undefined = selectedNodeId
    ? flowchart.nodes.find(n => n.id === selectedNodeId)
    : undefined

  const selectedEdgeObj = selectedEdge
    ? flowchart.edges.find(e => e.from === selectedEdge.from && e.to === selectedEdge.to)
    : undefined

  // Check whether the selected edge originates from a decision node.
  // Decision edges must be labelled "true" or "false" — show a toggle
  // instead of free-text input.
  const isDecisionEdge = selectedEdgeObj
    ? flowchart.nodes.find(n => n.id === selectedEdgeObj.from)?.type === 'decision'
    : false

  /* ── Variable modal state ─────────────────────────────── */
  // null = modal closed, WorkflowVariable = editing, undefined-like handled via isModalOpen
  const [editingVariable, setEditingVariable] = useState<WorkflowVariable | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  // Track the index of the variable being edited (-1 = creating new)
  const [editingIndex, setEditingIndex] = useState(-1)

  /** Open the modal in "create new variable" mode */
  const handleNewVariable = useCallback(() => {
    setEditingVariable(null) // null signals "create" mode to VariableModal
    setEditingIndex(-1)
    setIsModalOpen(true)
  }, [])

  /** Open the modal in "edit existing variable" mode */
  const handleEditVariable = useCallback((variable: WorkflowVariable, index: number) => {
    setEditingVariable(variable)
    setEditingIndex(index)
    setIsModalOpen(true)
  }, [])

  /** Close the modal without saving */
  const handleModalClose = useCallback(() => {
    setIsModalOpen(false)
    setEditingVariable(null)
    setEditingIndex(-1)
  }, [])

  /** Save a variable from the modal (create or update) */
  const handleModalSave = useCallback((variable: WorkflowVariable) => {
    let newVars: WorkflowVariable[]
    if (editingIndex === -1) {
      // Creating a new variable — append to list
      newVars = [...analysisInputs, variable]
    } else {
      // Updating an existing variable — replace at index
      newVars = [...analysisInputs]
      newVars[editingIndex] = variable
    }

    const updated: WorkflowAnalysis = {
      ...effectiveAnalysis,
      variables: newVars,
    }
    setAnalysis(updated)
    handleModalClose()
  }, [effectiveAnalysis, analysisInputs, editingIndex, setAnalysis, handleModalClose])

  /** Delete a variable by index */
  const handleVariableDelete = useCallback(
    (index: number) => {
      const newVars = analysisInputs.filter((_, i) => i !== index)
      const updated: WorkflowAnalysis = {
        ...effectiveAnalysis,
        variables: newVars,
      }
      setAnalysis(updated)
    },
    [effectiveAnalysis, analysisInputs, setAnalysis],
  )

  /* ── Node update passthrough ──────────────────────────── */
  const handleNodeUpdate = useCallback(
    (updates: Partial<FlowNode>) => {
      if (selectedNode) {
        updateNode(selectedNode.id, updates)
      }
    },
    [selectedNode, updateNode],
  )

  /* ── Render ───────────────────────────────────────────── */
  return (
    <>
      <aside
        ref={sidebarRef}
        className={`sidebar right-sidebar ${isResizing ? 'resizing' : ''} ${isCollapsed ? 'sidebar-collapsed' : ''}`}
        style={{
          width: isCollapsed ? 0 : sidebarWidth,
          minWidth: isCollapsed ? 0 : sidebarWidth,
          overflowX: isCollapsed ? 'visible' : 'hidden',
          paddingLeft: isCollapsed ? 0 : sidebarWidth < 40 ? 0 : undefined,
          paddingRight: isCollapsed ? 0 : sidebarWidth < 40 ? 0 : undefined,
        }}
      >
        {/* Resize handle — always rendered so drag-to-reopen works when collapsed */}
        <div
          className="sidebar-resize-handle right-resize-handle"
          onMouseDown={handleResizeStart}
          title={isCollapsed ? 'Drag to expand' : 'Drag to resize'}
        >
          <div className="resize-grip" />
        </div>

        {/* Mutually exclusive panels: edge props > node props > variables.
            Only one panel is visible at a time so the sidebar stays focused. */}
        {!isCollapsed && (
          <>
            {selectedEdgeObj ? (
              /* ── Edge properties (highest priority) ───── */
              <div className="sidebar-section">
                <p className="eyebrow">EDGE PROPERTIES</p>
                <div className="form-group">
                  <label>Label</label>
                  {isDecisionEdge ? (
                    /* Decision edges: true/false toggle. updateEdgeLabel
                       auto-swaps the sibling edge to the opposite value. */
                    <div className="sidebar-toggle-group">
                      <button
                        className={`sidebar-toggle-btn ${selectedEdgeObj.label === 'true' ? 'active' : ''}`}
                        onClick={() => updateEdgeLabel(selectedEdgeObj.from, selectedEdgeObj.to, 'true')}
                      >
                        True
                      </button>
                      <button
                        className={`sidebar-toggle-btn ${selectedEdgeObj.label === 'false' ? 'active' : ''}`}
                        onClick={() => updateEdgeLabel(selectedEdgeObj.from, selectedEdgeObj.to, 'false')}
                      >
                        False
                      </button>
                    </div>
                  ) : (
                    /* Non-decision edges: free-text label input */
                    <input
                      type="text"
                      value={selectedEdgeObj.label || ''}
                      onChange={e =>
                        updateEdgeLabel(selectedEdgeObj.from, selectedEdgeObj.to, e.target.value)
                      }
                    />
                  )}
                </div>
              </div>
            ) : selectedNode ? (
              /* ── Node properties ────────────────────────── */
              <div className="sidebar-section">
                <p className="eyebrow">NODE PROPERTIES</p>

                <div className="form-group">
                  <label>Label</label>
                  <input
                    type="text"
                    value={selectedNode.label}
                    onChange={e => handleNodeUpdate({ label: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Type</label>
                  <span className="node-type-badge">{selectedNode.type}</span>
                </div>

                {/* Type-specific config editors */}
                {selectedNode.type === 'end' && (
                  <EndNodeConfig
                    node={selectedNode}
                    analysisInputs={analysisInputs}
                    workflowOutputType={currentWorkflow?.output_type || 'string'}
                    onUpdate={handleNodeUpdate}
                  />
                )}
                {selectedNode.type === 'subprocess' && (
                  <SubprocessConfig
                    node={selectedNode}
                    workflows={workflows}
                    analysisInputs={analysisInputs}
                    currentWorkflowId={currentWorkflow?.id}
                    onUpdate={handleNodeUpdate}
                  />
                )}
                {selectedNode.type === 'decision' && (
                  <DecisionConditionEditor
                    node={selectedNode}
                    analysisInputs={analysisInputs}
                    onUpdate={handleNodeUpdate}
                  />
                )}
                {selectedNode.type === 'calculation' && (
                  <CalculationConfigEditor
                    node={selectedNode}
                    analysisInputs={analysisInputs}
                    onUpdate={handleNodeUpdate}
                  />
                )}
              </div>
            ) : (
              /* ── Variables (default when nothing selected) ── */
              <div className="sidebar-section">
                <p className="eyebrow">VARIABLES</p>

                {analysisInputs.length === 0 && (
                  <p className="sidebar-empty-hint">No variables yet.</p>
                )}

                <div className="var-list">
                  {analysisInputs.map((v, idx) => (
                    <div key={v.id} className="var-card" data-source={v.source}>
                      {/* Row 1: icon + name (read-only) + action buttons */}
                      <div className="var-card-header">
                        <span className="var-icon" title={v.type}>
                          {TYPE_ICONS[v.type] ?? TYPE_ICONS.string}
                        </span>
                        <span className="var-name">{v.name || 'Unnamed'}</span>
                        {/* Only input/constant variables are user-editable.
                            Subprocess/calculated variables are managed by their
                            corresponding nodes and removed when those nodes are deleted. */}
                        {(v.source === 'input' || v.source === 'constant') && (
                          <div className="var-card-actions">
                            <button
                              className="var-action-btn"
                              onClick={() => handleEditVariable(v, idx)}
                              title="Edit variable"
                            >
                              {/* Pencil icon */}
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                                <path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5Z" />
                              </svg>
                            </button>
                            <button
                              className="var-action-btn var-action-delete"
                              onClick={() => handleVariableDelete(idx)}
                              title="Delete variable"
                            >
                              ×
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Row 2: type label + source badge (read-only) */}
                      <div className="var-card-meta">
                        <span className="var-type-label">{TYPE_LABELS[v.type] ?? v.type}</span>
                        <span className={`var-source-badge source-${v.source}`}>
                          {SOURCE_LABELS[v.source] ?? v.source}
                        </span>
                      </div>

                      {/* Optional: enum values preview */}
                      {v.type === 'enum' && v.enum_values && v.enum_values.length > 0 && (
                        <p className="var-enum-hint">
                          {v.enum_values.join(', ')}
                        </p>
                      )}

                      {/* Optional: range preview for numbers */}
                      {v.type === 'number' && v.range && (
                        <p className="var-range-hint">
                          Range: {v.range.min ?? '−∞'} – {v.range.max ?? '∞'}
                        </p>
                      )}

                      {/* Optional: description preview */}
                      {v.description && (
                        <p className="var-description-hint">{v.description}</p>
                      )}
                    </div>
                  ))}
                </div>

                <button className="ghost full-width add-var-btn" onClick={handleNewVariable}>
                  + Add Variable
                </button>
              </div>
            )}
          </>
        )}
      </aside>

      {/* Variable modal — rendered outside sidebar to avoid overflow clipping */}
      {isModalOpen && (
        <VariableModal
          variable={editingVariable}
          onSave={handleModalSave}
          onClose={handleModalClose}
        />
      )}
    </>
  )
}
