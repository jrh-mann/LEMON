import { useState, useCallback, useEffect, useRef } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { executeWorkflow } from '../api/execution'
import { listWorkflows } from '../api/workflows'
import type {
  ExecutionResult,
  InputBlock,
  InputType,
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

/** Re-export config editors so any legacy imports from './RightSidebar' still resolve */
export { EndNodeConfig, SubprocessConfig, DecisionConditionEditor, CalculationConfigEditor }

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
    setInputValues
  } = useWorkflowStore()

  // Resizable sidebar state
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)

  // Handle resize drag
  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      // Calculate new width based on mouse position from right edge of window
      const newWidth = window.innerWidth - e.clientX
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(newWidth, window.innerWidth * 0.4))
      setSidebarWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      // Snap to closed if very small
      setSidebarWidth(prev => prev < 40 ? 0 : prev)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    // Prevent text selection during resize
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

  // Execution state
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)

  // Load library workflows for subprocess node config
  useEffect(() => {
    listWorkflows().then(setWorkflows).catch(() => {})
  }, [setWorkflows])

  // Derive analysis variables for display
  const analysisInputs: WorkflowVariable[] = currentAnalysis?.variables || []

  // Selected node / edge helpers
  const selectedNode: FlowNode | undefined = selectedNodeId
    ? flowchart.nodes.find(n => n.id === selectedNodeId)
    : undefined

  const selectedEdgeObj = selectedEdge
    ? flowchart.edges.find(e => e.from === selectedEdge.from && e.to === selectedEdge.to)
    : undefined

  // Variable add handler
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

  // Variable update handler
  const handleVariableUpdate = useCallback(
    (index: number, updates: Partial<WorkflowVariable>) => {
      const newVars = [...analysisInputs]
      const old = newVars[index]
      const merged = { ...old, ...updates }

      // Regenerate ID if name or type changed
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
    [currentAnalysis, analysisInputs, setAnalysis]
  )

  // Variable delete handler
  const handleVariableDelete = useCallback(
    (index: number) => {
      const newVars = analysisInputs.filter((_, i) => i !== index)
      const updated: WorkflowAnalysis = {
        ...currentAnalysis!,
        variables: newVars,
      }
      setAnalysis(updated)
    },
    [currentAnalysis, analysisInputs, setAnalysis]
  )

  // Execute workflow handler
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

  // Node update handler (wraps updateNode for config editors)
  const handleNodeUpdate = useCallback(
    (updates: Partial<FlowNode>) => {
      if (selectedNode) {
        updateNode(selectedNode.id, updates)
      }
    },
    [selectedNode, updateNode]
  )

  // Collapsed state — don't render content
  if (sidebarWidth === 0) {
    return (
      <aside className="right-sidebar collapsed">
        <div
          className="sidebar-resize-handle"
          onMouseDown={handleResizeStart}
          title="Drag to resize"
        />
        <button
          className="sidebar-expand-btn"
          onClick={() => setSidebarWidth(DEFAULT_WIDTH)}
          title="Expand sidebar"
        >
          ‹
        </button>
      </aside>
    )
  }

  return (
    <aside
      ref={sidebarRef}
      className="right-sidebar"
      style={{ width: sidebarWidth }}
    >
      {/* Resize handle */}
      <div
        className="sidebar-resize-handle"
        onMouseDown={handleResizeStart}
        title="Drag to resize"
      />

      {/* Variables panel */}
      {currentAnalysis && (
        <>
          <h4>Variables</h4>
          {analysisInputs.map((input, idx) => (
            <div key={input.id} className="variable-row">
              <input
                type="text"
                value={input.name}
                onChange={(e) => handleVariableUpdate(idx, { name: e.target.value })}
                className="variable-name-input"
              />
              <select
                value={input.type}
                onChange={(e) => handleVariableUpdate(idx, { type: e.target.value as InputType })}
                className="variable-type-select"
              >
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="bool">bool</option>
                <option value="date">date</option>
                <option value="enum">enum</option>
                <option value="json">json</option>
              </select>
              <button
                className="ghost variable-delete-btn"
                onClick={() => handleVariableDelete(idx)}
                title="Delete variable"
              >
                ×
              </button>
            </div>
          ))}
          <button className="ghost add-variable-btn" onClick={handleAddVariable}>
            + Add Variable
          </button>
        </>
      )}

      {/* Node properties panel */}
      {selectedNode && (
        <>
          <div className="form-divider" />
          <h4>Node Properties</h4>
          <div className="form-group">
            <label>Label</label>
            <input
              type="text"
              value={selectedNode.label}
              onChange={(e) => handleNodeUpdate({ label: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Type</label>
            <span className="node-type-badge">{selectedNode.type}</span>
          </div>

          {/* Node-type-specific config editors */}
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
            className="ghost"
            onClick={() => openModal('nodeProperties', { nodeId: selectedNode.id })}
          >
            Open in modal
          </button>
        </>
      )}

      {/* Edge properties */}
      {selectedEdgeObj && (
        <>
          <div className="form-divider" />
          <h4>Edge Properties</h4>
          <div className="form-group">
            <label>Label</label>
            <input
              type="text"
              value={selectedEdgeObj.label || ''}
              onChange={(e) => updateEdgeLabel(selectedEdgeObj.from, selectedEdgeObj.to, e.target.value)}
            />
          </div>
        </>
      )}

      {/* Execution section */}
      {currentWorkflow && (
        <>
          <div className="form-divider" />
          <h4>Execute</h4>

          {/* Input fields for execution */}
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
                  onChange={(val) => setInputValues({ ...inputValues, [input.id]: val })}
                />
              )
            })}

          <button
            className="btn primary"
            onClick={handleExecute}
            disabled={isExecuting}
          >
            {isExecuting ? 'Running...' : 'Run Workflow'}
          </button>

          {/* Execution result */}
          {executionResult && (
            <div className={`execution-result ${executionResult.success ? 'success' : 'error'}`}>
              {executionResult.success ? (
                <>
                  <p><strong>Result:</strong> {String(executionResult.output)}</p>
                  <p className="muted small">
                    Path: {executionResult.path?.map(p => p.label).join(' → ')}
                  </p>
                </>
              ) : (
                <p className="error-message">{executionResult.error}</p>
              )}
            </div>
          )}
        </>
      )}
    </aside>
  )
}

/**
 * InputField - Renders a typed input field (bool/enum/number/date/string)
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

  // Render different input types
  switch (input.input_type) {
    case 'bool':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>
            <input
              type="checkbox"
              id={inputId}
              checked={Boolean(value)}
              onChange={(e) => onChange(e.target.checked)}
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
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">Select...</option>
            {input.enum_values?.map((opt) => (
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
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              onChange(isNaN(val) ? undefined : val)
            }}
          />
          {input.range && (
            <p className="input-range">
              Range: {input.range.min ?? '∞'} - {input.range.max ?? '∞'}
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
            onChange={(e) => onChange(e.target.value)}
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
            onChange={(e) => onChange(e.target.value)}
          />
          {input.description && <p className="input-description">{input.description}</p>}
        </div>
      )
  }
}
