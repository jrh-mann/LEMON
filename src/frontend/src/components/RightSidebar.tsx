import { useState, useCallback, useEffect, useRef } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { executeWorkflow } from '../api/execution'
import { listWorkflows } from '../api/workflows'
import type {
  ExecutionResult,
  InputBlock,
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

const slugifyInputName = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')

/**
 * Build a variable ID using the unified variable naming convention.
 * Format: var_{slug}_{type} for input variables
 */
const buildVariableId = (name: string, type: InputType): string => {
  const slug = slugifyInputName(name) || 'var'
  return `var_${slug}_${type}`
}

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

const DEFAULT_WIDTH = 200
const MIN_WIDTH = 0

export default function RightSidebar() {
  const { openModal } = useUIStore()
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
    inputValues,
    setInputValues,
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

  /* ── Execution state ──────────────────────────────────── */
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)

  // Load library workflows for subprocess node config
  useEffect(() => {
    listWorkflows().then(setWorkflows).catch(() => {})
  }, [setWorkflows])

  /* ── Derived state ────────────────────────────────────── */
  const analysisInputs: WorkflowVariable[] = currentAnalysis?.variables || []
  const isCollapsed = sidebarWidth === 0

  const selectedNode: FlowNode | undefined = selectedNodeId
    ? flowchart.nodes.find(n => n.id === selectedNodeId)
    : undefined

  const selectedEdgeObj = selectedEdge
    ? flowchart.edges.find(e => e.from === selectedEdge.from && e.to === selectedEdge.to)
    : undefined

  /* ── Variable CRUD handlers ───────────────────────────── */
  const handleAddVariable = useCallback(() => {
    const newVar: WorkflowVariable = {
      id: buildVariableId('New Variable', 'string'),
      name: 'New Variable',
      type: 'string',
      source: 'input',
    }
    const updated: WorkflowAnalysis = {
      ...currentAnalysis!,
      variables: [...analysisInputs, newVar],
    }
    setAnalysis(updated)
  }, [currentAnalysis, analysisInputs, setAnalysis])

  const handleVariableUpdate = useCallback(
    (index: number, updates: Partial<WorkflowVariable>) => {
      const newVars = [...analysisInputs]
      const old = newVars[index]
      const merged = { ...old, ...updates }

      // Regenerate ID when name or type changes
      if (updates.name !== undefined || updates.type !== undefined) {
        merged.id = buildVariableId(merged.name, merged.type as InputType)
      }

      newVars[index] = merged
      const updated: WorkflowAnalysis = {
        ...currentAnalysis!,
        variables: newVars,
      }
      setAnalysis(updated)
    },
    [currentAnalysis, analysisInputs, setAnalysis],
  )

  const handleVariableDelete = useCallback(
    (index: number) => {
      const newVars = analysisInputs.filter((_, i) => i !== index)
      const updated: WorkflowAnalysis = {
        ...currentAnalysis!,
        variables: newVars,
      }
      setAnalysis(updated)
    },
    [currentAnalysis, analysisInputs, setAnalysis],
  )

  /* ── Execute workflow ─────────────────────────────────── */
  const handleExecute = useCallback(async () => {
    if (!currentWorkflow?.id) return
    setIsExecuting(true)
    setExecutionResult(null)
    try {
      const result = await executeWorkflow(currentWorkflow.id, inputValues)
      setExecutionResult(result)
    } catch (err: unknown) {
      setExecutionResult({
        success: false,
        error: err instanceof Error ? err.message : String(err),
        path: [],
      })
    } finally {
      setIsExecuting(false)
    }
  }, [currentWorkflow, inputValues])

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

      {!isCollapsed && (
        <>
          {/* ── Variables panel ─────────────────────────── */}
          {currentAnalysis && (
            <div className="sidebar-section">
              <p className="eyebrow">VARIABLES</p>

              {analysisInputs.length === 0 && (
                <p className="sidebar-empty-hint">No variables yet.</p>
              )}

              <div className="var-list">
                {analysisInputs.map((v, idx) => (
                  <div key={v.id} className="var-card" data-source={v.source}>
                    {/* Row 1: icon + name input + delete */}
                    <div className="var-card-header">
                      <span className="var-icon" title={v.type}>
                        {TYPE_ICONS[v.type] ?? TYPE_ICONS.string}
                      </span>
                      <input
                        type="text"
                        className="var-name-input"
                        value={v.name}
                        onChange={e => handleVariableUpdate(idx, { name: e.target.value })}
                      />
                      <button
                        className="var-delete-btn"
                        onClick={() => handleVariableDelete(idx)}
                        title="Delete variable"
                      >
                        ×
                      </button>
                    </div>

                    {/* Row 2: type selector + source badge */}
                    <div className="var-card-meta">
                      <select
                        className="var-type-select"
                        value={v.type}
                        onChange={e => handleVariableUpdate(idx, { type: e.target.value as InputType })}
                      >
                        <option value="string">string</option>
                        <option value="number">number</option>
                        <option value="bool">bool</option>
                        <option value="date">date</option>
                        <option value="enum">enum</option>
                      </select>
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
                  </div>
                ))}
              </div>

              <button className="ghost full-width add-var-btn" onClick={handleAddVariable}>
                + Add Variable
              </button>
            </div>
          )}

          {/* ── Node properties panel ──────────────────── */}
          {selectedNode && (
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

              <button
                className="ghost full-width"
                onClick={() => openModal('nodeProperties', { nodeId: selectedNode.id })}
                style={{ marginTop: 8 }}
              >
                Open in modal
              </button>
            </div>
          )}

          {/* ── Edge properties ────────────────────────── */}
          {selectedEdgeObj && (
            <div className="sidebar-section">
              <p className="eyebrow">EDGE PROPERTIES</p>
              <div className="form-group">
                <label>Label</label>
                <input
                  type="text"
                  value={selectedEdgeObj.label || ''}
                  onChange={e =>
                    updateEdgeLabel(selectedEdgeObj.from, selectedEdgeObj.to, e.target.value)
                  }
                />
              </div>
            </div>
          )}

          {/* ── Execute ────────────────────────────────── */}
          {currentWorkflow && (
            <div className="sidebar-section">
              <p className="eyebrow">EXECUTE</p>

              {/* Input fields for execution — only source=input variables */}
              {analysisInputs
                .filter(v => v.source === 'input')
                .map(input => {
                  const block: InputBlock = {
                    id: input.id,
                    name: input.name,
                    input_type: input.type,
                    description: input.description,
                    enum_values: input.enum_values,
                    range: input.range,
                  }
                  return (
                    <InputField
                      key={input.id}
                      input={block}
                      value={inputValues[input.id]}
                      onChange={val => setInputValues({ ...inputValues, [input.id]: val })}
                    />
                  )
                })}

              <button
                className="run-btn full-width"
                onClick={handleExecute}
                disabled={isExecuting}
              >
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                  <path d="M8 5v14l11-7z" />
                </svg>
                {isExecuting ? 'Running...' : 'Run Workflow'}
              </button>

              {/* Execution result */}
              {executionResult && (
                <div className={`execution-result ${executionResult.success ? 'success' : 'error'}`}>
                  {executionResult.success ? (
                    <>
                      <p>
                        <strong>Result:</strong> {String(executionResult.output)}
                      </p>
                      <p className="muted small">
                        Path: {executionResult.path?.map(p => p.label).join(' → ')}
                      </p>
                    </>
                  ) : (
                    <p className="error-message">{executionResult.error}</p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </aside>
  )
}

/* ── InputField ──────────────────────────────────────────── */

/**
 * Renders a typed input field (bool/enum/number/date/string)
 * for workflow execution. Used only by RightSidebar's execution section.
 */
function InputField({
  input,
  value,
  onChange,
}: {
  input: InputBlock
  value: unknown
  onChange: (value: unknown) => void
}) {
  const inputId = `input-${input.id}`

  switch (input.input_type) {
    case 'bool':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>
            <input
              type="checkbox"
              id={inputId}
              checked={Boolean(value)}
              onChange={e => onChange(e.target.checked)}
            />
            {input.name}
          </label>
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )

    case 'enum':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>{input.name}</label>
          <select
            id={inputId}
            value={String(value || '')}
            onChange={e => onChange(e.target.value)}
          >
            <option value="">Select...</option>
            {input.enum_values?.map(opt => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )

    case 'number':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>{input.name}</label>
          <input
            type="number"
            id={inputId}
            value={value !== undefined ? String(value) : ''}
            min={input.range?.min}
            max={input.range?.max}
            step="any"
            onChange={e => {
              const val = parseFloat(e.target.value)
              onChange(isNaN(val) ? undefined : val)
            }}
          />
          {input.range && (
            <p className="input-range">
              Range: {input.range.min ?? '∞'} – {input.range.max ?? '∞'}
            </p>
          )}
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )

    case 'date':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>{input.name}</label>
          <input
            type="date"
            id={inputId}
            value={String(value || '')}
            onChange={e => onChange(e.target.value)}
          />
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )

    default: // string
      return (
        <div className="input-field">
          <label htmlFor={inputId}>{input.name}</label>
          <input
            type="text"
            id={inputId}
            value={String(value || '')}
            onChange={e => onChange(e.target.value)}
          />
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )
  }
}
