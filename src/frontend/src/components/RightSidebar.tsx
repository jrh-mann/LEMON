import { useState, useCallback, useEffect, useRef } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { executeWorkflow } from '../api/execution'
import { listWorkflows } from '../api/workflows'
import WorkflowBrowser from './WorkflowBrowser'
import type { 
  SidebarTab, 
  ExecutionResult, 
  InputBlock, 
  InputType, 
  WorkflowAnalysis, 
  WorkflowInput, 
  FlowNode, 
  WorkflowSummary,
  DecisionCondition,
  Comparator,
  CalculationConfig as CalculationConfigType,
  Operand
} from '../types'
import { COMPARATORS_BY_TYPE, COMPARATOR_LABELS, getOperator, getOperatorsByCategory } from '../types'

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

// Backwards compatibility alias
const buildInputId = buildVariableId

// Storage key and default/min width for sidebar
const SIDEBAR_WIDTH_KEY = 'lemon_right_sidebar_width'
const DEFAULT_WIDTH = 320
const MIN_WIDTH = 280  // Minimum to show all 3 tabs comfortably

export default function RightSidebar() {
  const { activeTab, setActiveTab, openModal } = useUIStore()
  const { currentWorkflow, currentAnalysis, setAnalysis, selectedNodeId, flowchart, updateNode, workflows, setWorkflows } = useWorkflowStore()

  // Resizable sidebar state
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY)
    return stored ? Math.max(parseInt(stored, 10), MIN_WIDTH) : DEFAULT_WIDTH
  })
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)

  // Handle resize drag
  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      // Calculate new width based on mouse position from right edge of window
      const newWidth = window.innerWidth - e.clientX
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(newWidth, window.innerWidth * 0.6))
      setSidebarWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      // Persist to localStorage
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth))
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
  }, [isResizing, sidebarWidth])

  // Start resizing
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  const [inputValues, setInputValues] = useState<Record<string, unknown>>({})
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAddInput, setShowAddInput] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [draftType, setDraftType] = useState<InputType>('string')
  const [draftDescription, setDraftDescription] = useState('')
  const [draftEnum, setDraftEnum] = useState('')
  const [draftRangeMin, setDraftRangeMin] = useState('')
  const [draftRangeMax, setDraftRangeMax] = useState('')
  const [inputError, setInputError] = useState<string | null>(null)

  // Auto-switch to properties tab when a node is selected
  useEffect(() => {
    if (selectedNodeId) {
      setActiveTab('properties')
    }
  }, [selectedNodeId, setActiveTab])

  // Get selected node
  const selectedNode = selectedNodeId
    ? flowchart.nodes.find((n) => n.id === selectedNodeId)
    : null

  // Load workflows from API if not already loaded (needed for subprocess config)
  useEffect(() => {
    if (selectedNode?.type === 'subprocess' && workflows.length === 0) {
      listWorkflows()
        .then(setWorkflows)
        .catch((err) => console.error('Failed to load workflows for subprocess config:', err))
    }
  }, [selectedNode?.type, workflows.length, setWorkflows])

  // Get input blocks from current workflow
  const inputBlocks = currentWorkflow?.blocks.filter(
    (b): b is InputBlock => b.type === 'input'
  ) || []
  const analysisInputs = currentAnalysis?.variables ?? []  // Unified variable system
  const showAnalysisInputs = currentAnalysis !== null
  const showAnalysisView = showAnalysisInputs || showAddInput

  // Handle input change
  const handleInputChange = useCallback(
    (name: string, value: unknown) => {
      setInputValues((prev) => ({ ...prev, [name]: value }))
    },
    []
  )

  const resetDraftInput = () => {
    setDraftName('')
    setDraftType('string')
    setDraftDescription('')
    setDraftEnum('')
    setDraftRangeMin('')
    setDraftRangeMax('')
    setInputError(null)
  }

  const handleAddInput = () => {
    const name = draftName.trim()
    if (!name) {
      setInputError('Input name is required.')
      return
    }
    if (!draftType) {
      setInputError('Input type is required.')
      return
    }
    const key = `${slugifyInputName(name)}:${draftType}`
    const existing = analysisInputs.some((input: WorkflowInput) => {
      const existingKey = `${slugifyInputName(input.name)}:${input.type}`
      return existingKey === key
    })
    if (existing) {
      setInputError('Input name and type must be unique.')
      return
    }

    const nextInputs: WorkflowInput[] = [...analysisInputs]
    const nextInput: WorkflowInput = {
      id: buildInputId(name, draftType),
      name,
      type: draftType,
      source: 'input',  // Manual inputs are user-provided values
    }
    if (draftDescription.trim()) {
      nextInput.description = draftDescription.trim()
    }
    if (draftType === 'enum' && draftEnum.trim()) {
      const values = draftEnum
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
      if (values.length > 0) {
        nextInput.enum_values = values  // Use enum_values, not enum
      }
    }
    if (draftType === 'number' && (draftRangeMin || draftRangeMax)) {
      const min = draftRangeMin.trim() ? Number(draftRangeMin) : undefined
      const max = draftRangeMax.trim() ? Number(draftRangeMax) : undefined
      nextInput.range = {}
      if (!Number.isNaN(min) && min !== undefined) {
        nextInput.range.min = min
      }
      if (!Number.isNaN(max) && max !== undefined) {
        nextInput.range.max = max
      }
      if (nextInput.range.min === undefined && nextInput.range.max === undefined) {
        delete nextInput.range
      }
    }

    nextInputs.push(nextInput)
    const baseAnalysis: WorkflowAnalysis = currentAnalysis ?? {
      variables: [],
      outputs: [],
      tree: {},
      doubts: [],
    }
    const nextAnalysis: WorkflowAnalysis = {
      ...baseAnalysis,
      variables: nextInputs,
    }
    setAnalysis(nextAnalysis)
    resetDraftInput()
    setShowAddInput(false)
  }

  const renderAnalysisInput = (input: WorkflowInput) => {
    const enumValues = input.enum_values ?? []
    const range = input.range
    const hasRange = range && (range.min !== undefined || range.max !== undefined)
    return (
      <div className="input-card" key={input.id}>
        <div className="input-card-name">{input.name}</div>
        <div className="input-card-type">{input.type}</div>
        {input.description && <div className="input-card-desc">{input.description}</div>}
        {Array.isArray(enumValues) && enumValues.length > 0 && (
          <div className="input-card-enum">Enum: {enumValues.join(', ')}</div>
        )}
        {hasRange && (
          <div className="input-card-range">
            Range: {range?.min ?? 'any'} - {range?.max ?? 'any'}
          </div>
        )}
      </div>
    )
  }

  // Handle execute
  const handleExecute = useCallback(async () => {
    if (!currentWorkflow) return

    setIsExecuting(true)
    setError(null)
    setExecutionResult(null)

    try {
      const result = await executeWorkflow(currentWorkflow.id, inputValues)
      setExecutionResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Execution failed')
    } finally {
      setIsExecuting(false)
    }
  }, [currentWorkflow, inputValues])

  // Handle tab click
  const handleTabClick = useCallback(
    (tab: SidebarTab) => {
      setActiveTab(tab)
    },
    [setActiveTab]
  )

  return (
    <aside
      ref={sidebarRef}
      className={`sidebar library-sidebar ${isResizing ? 'resizing' : ''}`}
      style={{ width: sidebarWidth }}
    >
      {/* Resize handle on left edge */}
      <div
        className="sidebar-resize-handle"
        onMouseDown={handleResizeStart}
        title="Drag to resize"
      >
        <div className="resize-grip"></div>
      </div>
      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${activeTab === 'library' ? 'active' : ''}`}
          onClick={() => handleTabClick('library')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          <span>Library</span>
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'variables' ? 'active' : ''}`}
          onClick={() => handleTabClick('variables')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="12" y1="18" x2="12" y2="12" />
            <line x1="9" y1="15" x2="15" y2="15" />
          </svg>
          <span>Variables</span>
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'properties' ? 'active' : ''}`}
          onClick={() => handleTabClick('properties')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
          <span>Props</span>
        </button>
      </div>

      {/* Library panel */}
      <div
        className={`sidebar-panel ${activeTab === 'library' ? '' : 'hidden'}`}
        data-panel="library"
      >
        <WorkflowBrowser />
      </div>

      {/* Variables panel */}
      <div
        className={`sidebar-panel ${activeTab === 'variables' ? '' : 'hidden'}`}
        data-panel="variables"
      >
        {/* ... Variables content ... */}
        <div className="inputs-header">
          <div>
            <h4>Variables</h4>
            <p className="muted small">Canonical list for this workflow.</p>
          </div>
          <button
            className="ghost inputs-add-btn"
            onClick={() => {
              if (!currentAnalysis) {
                setAnalysis({ variables: [], outputs: [], tree: {}, doubts: [] })
              }
              setInputError(null)
              setShowAddInput(true)
            }}
          >
            + Input
          </button>
        </div>

        {showAnalysisView ? (
          <>
            {showAddInput && (
              <div className="input-add-form">
                <div className="input-add-row">
                  <label>Name</label>
                  <input
                    type="text"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    placeholder="e.g. Total Cholesterol"
                  />
                </div>
                <div className="input-add-row">
                  <label>Type</label>
                  <select
                    value={draftType}
                    onChange={(e) => setDraftType(e.target.value as InputType)}
                  >
<option value="string">string</option>
                    <option value="number">number</option>
                    <option value="bool">bool</option>
                    <option value="enum">enum</option>
                    <option value="date">date</option>
                  </select>
                </div>
                <div className="input-add-row">
                  <label>Description</label>
                  <input
                    type="text"
                    value={draftDescription}
                    onChange={(e) => setDraftDescription(e.target.value)}
                    placeholder="Optional"
                  />
                </div>
                {draftType === 'enum' && (
                  <div className="input-add-row">
                    <label>Enum values</label>
                    <input
                      type="text"
                      value={draftEnum}
                      onChange={(e) => setDraftEnum(e.target.value)}
                      placeholder="Comma-separated values"
                    />
                  </div>
                )}
                {draftType === 'number' && (
                  <div className="input-add-row input-add-range">
                    <label>Range</label>
                    <div className="input-add-range-fields">
                      <input
                        type="number"
                        value={draftRangeMin}
                        onChange={(e) => setDraftRangeMin(e.target.value)}
                        placeholder="Min"
                      />
                      <input
                        type="number"
                        value={draftRangeMax}
                        onChange={(e) => setDraftRangeMax(e.target.value)}
                        placeholder="Max"
                      />
                    </div>
                  </div>
                )}
                {inputError && <p className="error-text">{inputError}</p>}
                <div className="input-add-actions">
                  <button className="primary" onClick={handleAddInput}>
                    Add Input
                  </button>
                  <button
                    className="ghost"
                    onClick={() => {
                      resetDraftInput()
                      setShowAddInput(false)
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {analysisInputs.length === 0 ? (
              <div className="inputs-empty">
                <p className="muted">No variables listed yet.</p>
                <p className="muted small">Run analysis or add a variable to start the list.</p>
              </div>
            ) : (
              <div className="inputs-list">
                {analysisInputs.map(renderAnalysisInput)}
              </div>
            )}
          </>
        ) : !currentWorkflow ? (
          <div className="inputs-empty">
            <p className="muted">No variables defined.</p>
            <p className="muted small">Create or load a workflow to see its variables.</p>
          </div>
        ) : inputBlocks.length === 0 ? (
          <div className="inputs-empty">
            <p className="muted">This workflow has no input blocks.</p>
          </div>
        ) : (
          <>
            <div className="inputs-list">
              {inputBlocks.map((input) => (
                <InputField
                  key={input.id}
                  input={input}
                  value={inputValues[input.name]}
                  onChange={(val) => handleInputChange(input.name, val)}
                />
              ))}
            </div>

            <div className="execute-section">
              <button
                className="primary full-width"
                onClick={handleExecute}
                disabled={isExecuting}
              >
                {isExecuting ? 'Executing...' : 'Execute Workflow'}
              </button>

              {error && <p className="error-text">{error}</p>}

              {executionResult && (
                <div className="execution-result">
                  <h4>Result</h4>
                  <div className={`result-output ${executionResult.success ? 'success' : 'error'}`}>
                    {executionResult.output || executionResult.error || 'No output'}
                  </div>
                  {executionResult.path && (
                    <details>
                      <summary>Execution path ({executionResult.path.length} steps)</summary>
                      <ol className="execution-path">
                        {executionResult.path.map((step, i) => (
                          <li key={i}>{step}</li>
                        ))}
                      </ol>
                    </details>
                  )}
                </div>
              )}
            </div>

            <div className="validate-section">
              <button
                className="ghost full-width"
                onClick={() => openModal('validation')}
              >
                Validate Workflow
              </button>
            </div>
          </>
        )}
      </div>

      {/* Properties panel */}
      <div
        className={`sidebar-panel ${activeTab === 'properties' ? '' : 'hidden'}`}
        data-panel="properties"
      >
        {selectedNode ? (
          <div className="properties-panel">
            <div className="properties-header">
              <h4>Properties</h4>
              <p className="muted small">{selectedNode.type} node</p>
            </div>
            
            <div className="form-group">
              <label>Label</label>
              <input
                type="text"
                value={selectedNode.label}
                onChange={(e) => updateNode(selectedNode.id, { label: e.target.value })}
                placeholder="Node label"
              />
              <p className="muted small">Display text for the node</p>
            </div>

            {selectedNode.type === 'decision' && (
              <DecisionConditionEditor
                node={selectedNode}
                analysisInputs={analysisInputs}
                onUpdate={(updates) => updateNode(selectedNode.id, updates)}
              />
            )}

            {selectedNode.type === 'end' && (
              <>
                <div className="form-divider" />
                <h5>Output Configuration</h5>
                
                <div className="form-group">
                  <label>Data Type</label>
                  <select
                    value={selectedNode.output_type || 'string'}
                    onChange={(e) => updateNode(selectedNode.id, { output_type: e.target.value })}
                  >
<option value="string">String</option>
                    <option value="number">Number</option>
                    <option value="bool">Boolean</option>
                    <option value="json">JSON</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Value Template</label>
                  <textarea
                    value={selectedNode.output_template || ''}
                    onChange={(e) => updateNode(selectedNode.id, { output_template: e.target.value })}
                    placeholder="e.g. Result: {value}"
                    rows={3}
                  />
                  <p className="muted small">
                    Use {'{variable}'} to insert input values.
                  </p>
                </div>

                <div className="form-group">
                  <label>Static Value (Optional)</label>
                  <input
                    type="text"
                    value={String(selectedNode.output_value || '')}
                    onChange={(e) => updateNode(selectedNode.id, { output_value: e.target.value })}
                    placeholder="Constant value"
                  />
                  <p className="muted small">Overridden by template if present.</p>
                </div>
              </>
            )}

            {selectedNode.type === 'subprocess' && (
              <SubprocessConfig
                node={selectedNode}
                workflows={workflows}
                analysisInputs={analysisInputs}
                currentWorkflowId={currentWorkflow?.id}
                onUpdate={(updates) => updateNode(selectedNode.id, updates)}
              />
            )}

            {selectedNode.type === 'calculation' && (
              <CalculationConfigEditor
                node={selectedNode}
                analysisInputs={analysisInputs}
                onUpdate={(updates) => updateNode(selectedNode.id, updates)}
              />
            )}
          </div>
        ) : (
          <div className="properties-empty">
            <p className="muted">No node selected.</p>
            <p className="muted small">Select a node on the canvas to edit its properties.</p>
          </div>
        )}
      </div>
    </aside>
  )
}

// Input field component
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

/**
 * SubprocessConfig - Configuration panel for subprocess nodes.
 * Allows selecting a subworkflow, mapping parent inputs to subworkflow inputs,
 * and naming the output variable for use in subsequent nodes.
 */
function SubprocessConfig({
  node,
  workflows,
  analysisInputs,
  currentWorkflowId,
  onUpdate,
}: {
  node: FlowNode
  workflows: WorkflowSummary[]
  analysisInputs: WorkflowInput[]
  currentWorkflowId?: string
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Local state for new mapping entry
  const [newMappingParent, setNewMappingParent] = useState('')
  const [newMappingSubflow, setNewMappingSubflow] = useState('')

  // Get the selected subworkflow's input names for the mapping dropdown
  const selectedWorkflow = workflows.find(w => w.id === node.subworkflow_id)
  const subflowInputNames = selectedWorkflow?.input_names ?? []

  // Current input mapping (parent input name -> subflow input name)
  const inputMapping = node.input_mapping ?? {}

  // Handle subworkflow selection change
  const handleWorkflowChange = (workflowId: string) => {
    onUpdate({
      subworkflow_id: workflowId || undefined,
      // Clear mappings when workflow changes since inputs may differ
      input_mapping: {},
    })
  }

  // Add a new input mapping entry
  const handleAddMapping = () => {
    if (!newMappingParent || !newMappingSubflow) return
    // Prevent duplicate mappings for the same parent input
    if (inputMapping[newMappingParent]) return

    onUpdate({
      input_mapping: {
        ...inputMapping,
        [newMappingParent]: newMappingSubflow,
      },
    })
    setNewMappingParent('')
    setNewMappingSubflow('')
  }

  // Remove a mapping entry by parent input name
  const handleRemoveMapping = (parentKey: string) => {
    const { [parentKey]: _, ...remaining } = inputMapping
    onUpdate({ input_mapping: remaining })
  }

  // Filter out parent inputs already used in mappings
  const availableParentInputs = analysisInputs.filter(
    input => !inputMapping[input.name]
  )

  return (
    <>
      <div className="form-divider" />
      <h5>Subprocess Configuration</h5>

      {/* Subworkflow selector */}
      <div className="form-group">
        <label>Target Workflow</label>
        <select
          value={node.subworkflow_id || ''}
          onChange={(e) => handleWorkflowChange(e.target.value)}
        >
          <option value="">Select a workflow...</option>
          {workflows
            .filter(w => w.id !== currentWorkflowId) // Prevent self-reference
            .map(w => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
        </select>
        <p className="muted small">The workflow to execute as a subprocess.</p>
      </div>

      {/* Show subflow details if selected */}
      {selectedWorkflow && (
        <div className="subprocess-info">
          <p className="muted small">
            <strong>Inputs:</strong> {subflowInputNames.length > 0 ? subflowInputNames.join(', ') : 'None'}
          </p>
          <p className="muted small">
            <strong>Outputs:</strong> {selectedWorkflow.output_values?.join(', ') || 'None'}
          </p>
        </div>
      )}

      {/* Input mapping section */}
      {node.subworkflow_id && (
        <>
          <div className="form-divider" />
          <h5>Input Mapping</h5>
          <p className="muted small">Map this workflow's inputs to the subprocess inputs.</p>

          {/* Existing mappings */}
          {Object.entries(inputMapping).length > 0 && (
            <div className="mapping-list">
              {Object.entries(inputMapping).map(([parentInput, subflowInput]) => (
                <div className="mapping-row" key={parentInput}>
                  <span className="mapping-parent">{parentInput}</span>
                  <span className="mapping-arrow">→</span>
                  <span className="mapping-subflow">{subflowInput}</span>
                  <button
                    className="mapping-remove ghost"
                    onClick={() => handleRemoveMapping(parentInput)}
                    title="Remove mapping"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add new mapping */}
          {availableParentInputs.length > 0 && subflowInputNames.length > 0 && (
            <div className="mapping-add">
              <select
                value={newMappingParent}
                onChange={(e) => setNewMappingParent(e.target.value)}
              >
                <option value="">Parent input...</option>
                {availableParentInputs.map(input => (
                  <option key={input.id} value={input.name}>
                    {input.name}
                  </option>
                ))}
              </select>
              <span className="mapping-arrow">→</span>
              <select
                value={newMappingSubflow}
                onChange={(e) => setNewMappingSubflow(e.target.value)}
              >
                <option value="">Subflow input...</option>
                {subflowInputNames.map(name => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                className="ghost"
                onClick={handleAddMapping}
                disabled={!newMappingParent || !newMappingSubflow}
              >
                Add
              </button>
            </div>
          )}

          {availableParentInputs.length === 0 && Object.keys(inputMapping).length > 0 && (
            <p className="muted small">All parent inputs are mapped.</p>
          )}

          {analysisInputs.length === 0 && (
            <p className="muted small warning">
              No variables defined for this workflow. Add variables in the Variables panel.
            </p>
          )}
        </>
      )}

      {/* Output variable name */}
      {node.subworkflow_id && (
        <>
          <div className="form-divider" />
          <h5>Output Variable</h5>
          <div className="form-group">
            <label>Variable Name</label>
            <input
              type="text"
              value={node.output_variable || ''}
              onChange={(e) => onUpdate({ output_variable: e.target.value })}
              placeholder="e.g. subprocess_result"
            />
            <p className="muted small">
              Name for the subprocess output. Use this variable in subsequent decision nodes.
            </p>
          </div>
        </>
      )}
    </>
  )
}

/**
 * DecisionConditionEditor - Configuration panel for decision node conditions.
 * Allows selecting an input, choosing a comparator appropriate for the input type,
 * and specifying comparison value(s).
 */
function DecisionConditionEditor({
  node,
  analysisInputs,
  onUpdate,
}: {
  node: FlowNode
  analysisInputs: WorkflowInput[]
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Get current condition or create empty one
  const condition = node.condition ?? { input_id: '', comparator: 'eq' as Comparator, value: '' }
  
  // Find the selected input to determine available comparators
  const selectedInput = analysisInputs.find(inp => inp.id === condition.input_id)
  const inputType = selectedInput?.type ?? 'string'
  const availableComparators = COMPARATORS_BY_TYPE[inputType] ?? COMPARATORS_BY_TYPE.string
  
  // Get enum values if input is enum type
  const enumValues = selectedInput?.enum_values ?? []

  // Update the condition field on the node
  const updateCondition = (updates: Partial<DecisionCondition>) => {
    const newCondition: DecisionCondition = {
      ...condition,
      ...updates,
    }
    onUpdate({ condition: newCondition })
  }

  // When input changes, reset comparator to first valid one for the new type
  const handleInputChange = (inputId: string) => {
    const newInput = analysisInputs.find(inp => inp.id === inputId)
    const newType = newInput?.type ?? 'string'
    const validComparators = COMPARATORS_BY_TYPE[newType] ?? COMPARATORS_BY_TYPE.string
    
    // Reset comparator if current one is invalid for new type
    const newComparator = validComparators.includes(condition.comparator as Comparator) 
      ? condition.comparator 
      : validComparators[0]

    updateCondition({ 
      input_id: inputId, 
      comparator: newComparator,
      value: '',
      value2: undefined 
    })
  }

  // Check if comparator requires a second value (for range comparisons)
  const needsSecondValue = condition.comparator === 'within_range' || condition.comparator === 'date_between'
  
  // Check if comparator doesn't need any value (boolean comparators)
  const noValueNeeded = condition.comparator === 'is_true' || condition.comparator === 'is_false'

  // Render value input based on input type
  const renderValueInput = (isSecondValue = false) => {
    const valueKey = isSecondValue ? 'value2' : 'value'
    const currentValue = isSecondValue ? condition.value2 : condition.value
    const placeholder = isSecondValue ? 'Max value' : needsSecondValue ? 'Min value' : 'Comparison value'

    // For enum inputs with enum comparators, show a dropdown
    if (inputType === 'enum' && enumValues.length > 0 && !isSecondValue) {
      return (
        <select
          value={String(currentValue ?? '')}
          onChange={(e) => updateCondition({ [valueKey]: e.target.value })}
        >
          <option value="">Select value...</option>
          {enumValues.map((val: string) => (
            <option key={val} value={val}>{val}</option>
          ))}
        </select>
      )
    }

    // For boolean, no input needed
    if (noValueNeeded) {
      return null
    }

    // For date inputs
    if (inputType === 'date') {
      return (
        <input
          type="date"
          value={String(currentValue ?? '')}
          onChange={(e) => updateCondition({ [valueKey]: e.target.value })}
        />
      )
    }

// For numeric inputs
    if (inputType === 'number') {
      return (
        <input
          type="number"
          value={currentValue !== undefined && currentValue !== '' ? String(currentValue) : ''}
          step="any"
          onChange={(e) => {
            const val = parseFloat(e.target.value)
            updateCondition({ [valueKey]: isNaN(val) ? '' : val })
          }}
          placeholder={placeholder}
        />
      )
    }

    // Default: string input
    return (
      <input
        type="text"
        value={String(currentValue ?? '')}
        onChange={(e) => updateCondition({ [valueKey]: e.target.value })}
        placeholder={placeholder}
      />
    )
  }

  return (
    <>
      <div className="form-divider" />
      <h5>Decision Condition</h5>
      <p className="muted small">Define when this decision evaluates to true.</p>

      {analysisInputs.length === 0 ? (
        <div className="condition-warning">
          <p className="muted small warning">
            No variables defined. Add variables in the Variables panel before configuring the condition.
          </p>
        </div>
      ) : (
        <>
          {/* Input selector */}
          <div className="form-group">
            <label>Input Variable</label>
            <select
              value={condition.input_id || ''}
              onChange={(e) => handleInputChange(e.target.value)}
            >
              <option value="">Select an input...</option>
              {analysisInputs.map(inp => (
                <option key={inp.id} value={inp.id}>
                  {inp.name} ({inp.type})
                </option>
              ))}
            </select>
          </div>

          {/* Comparator selector (only show if input is selected) */}
          {condition.input_id && (
            <div className="form-group">
              <label>Comparator</label>
              <select
                value={condition.comparator}
                onChange={(e) => updateCondition({ 
                  comparator: e.target.value as Comparator,
                  // Reset value2 if switching away from range comparator
                  value2: (e.target.value === 'within_range' || e.target.value === 'date_between') 
                    ? condition.value2 
                    : undefined
                })}
              >
                {availableComparators.map(comp => (
                  <option key={comp} value={comp}>
                    {COMPARATOR_LABELS[comp]}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Value input(s) */}
          {condition.input_id && !noValueNeeded && (
            <div className="form-group">
              <label>{needsSecondValue ? 'Range Values' : 'Value'}</label>
              {needsSecondValue ? (
                <div className="condition-range-inputs">
                  {renderValueInput(false)}
                  <span className="condition-range-separator">to</span>
                  {renderValueInput(true)}
                </div>
              ) : (
                renderValueInput(false)
              )}
            </div>
          )}

          {/* Condition preview */}
          {condition.input_id && (
            <div className="condition-preview">
              <p className="muted small">
                <strong>Preview:</strong> {formatConditionPreview(condition, analysisInputs)}
              </p>
            </div>
          )}
        </>
      )}
    </>
  )
}

/**
 * Format a condition as a human-readable string for preview.
 */
function formatConditionPreview(condition: DecisionCondition, inputs: WorkflowInput[]): string {
  if (!condition.input_id) return '(no condition set)'
  
  const input = inputs.find(inp => inp.id === condition.input_id)
  const inputName = input?.name ?? condition.input_id
  const compLabel = COMPARATOR_LABELS[condition.comparator] ?? condition.comparator
  
  // Boolean comparators don't need a value
  if (condition.comparator === 'is_true' || condition.comparator === 'is_false') {
    return `${inputName} ${compLabel}`
  }
  
  // Range comparators
  if (condition.comparator === 'within_range' || condition.comparator === 'date_between') {
    return `${inputName} ${compLabel} [${condition.value ?? '?'}, ${condition.value2 ?? '?'}]`
  }
  
  // Standard comparators
  const valueStr = typeof condition.value === 'string' 
    ? `"${condition.value}"` 
    : String(condition.value ?? '?')
  return `${inputName} ${compLabel} ${valueStr}`
}

/**
 * CalculationConfigEditor - Configuration panel for calculation nodes.
 * Allows selecting an operator, configuring operands (variable references or literals),
 * and specifying the output variable name.
 */
function CalculationConfigEditor({
  node,
  analysisInputs,
  onUpdate,
}: {
  node: FlowNode
  analysisInputs: WorkflowInput[]
  onUpdate: (updates: Partial<FlowNode>) => void
}) {
  // Get current calculation config or create empty one
  const calculation: CalculationConfigType = node.calculation ?? {
    output: { name: '', description: '' },
    operator: 'add',
    operands: []
  }

  // Get the selected operator definition
  const selectedOperator = getOperator(calculation.operator)
  const minOperands = selectedOperator?.minArity ?? 2
  const maxOperands = selectedOperator?.maxArity ?? null // null = unlimited

  // Filter to only numeric variables
  const numericVariables = analysisInputs.filter(v => 
    v.type === 'number'
  )

  // Validation errors state
  const [validationErrors, setValidationErrors] = useState<string[]>([])

  // Validate the calculation configuration
  const validateCalculation = useCallback((calc: CalculationConfigType): string[] => {
    const errors: string[] = []
    
    // Check output name
    if (!calc.output.name.trim()) {
      errors.push('Output variable name is required')
    }

    // Check operator
    const op = getOperator(calc.operator)
    if (!op) {
      errors.push(`Unknown operator: ${calc.operator}`)
    } else {
      // Check operand count
      if (calc.operands.length < op.minArity) {
        errors.push(`${op.displayName} requires at least ${op.minArity} operand(s)`)
      }
      if (op.maxArity !== null && calc.operands.length > op.maxArity) {
        errors.push(`${op.displayName} accepts at most ${op.maxArity} operand(s)`)
      }
    }

    // Check each operand
    calc.operands.forEach((operand, idx) => {
      if (operand.kind === 'variable') {
        if (!operand.ref) {
          errors.push(`Operand ${idx + 1}: Variable reference is required`)
        } else {
          // Check if variable exists
          const varExists = analysisInputs.some(v => v.id === operand.ref)
          if (!varExists) {
            errors.push(`Operand ${idx + 1}: Variable "${operand.ref}" not found`)
          }
        }
      } else if (operand.kind === 'literal') {
        if (operand.value === undefined || operand.value === null || isNaN(operand.value)) {
          errors.push(`Operand ${idx + 1}: Numeric value is required`)
        }
      }
    })

    return errors
  }, [analysisInputs])

  // Validate on calculation change
  useEffect(() => {
    const errors = validateCalculation(calculation)
    setValidationErrors(errors)
  }, [calculation, validateCalculation])

  // Update the calculation field on the node
  const updateCalculation = (updates: Partial<CalculationConfigType>) => {
    const newCalculation: CalculationConfigType = {
      ...calculation,
      ...updates,
    }
    onUpdate({ calculation: newCalculation })
  }

  // Update output name
  const updateOutputName = (name: string) => {
    updateCalculation({
      output: { ...calculation.output, name }
    })
  }

  // Update output description
  const updateOutputDescription = (description: string) => {
    updateCalculation({
      output: { ...calculation.output, description }
    })
  }

  // Handle operator change - reset operands if arity requirements change
  const handleOperatorChange = (operatorName: string) => {
    const newOp = getOperator(operatorName)
    if (!newOp) return

    // Adjust operands array to meet new arity requirements
    let newOperands = [...calculation.operands]
    
    // If we have fewer than min, add empty variable operands
    while (newOperands.length < newOp.minArity) {
      newOperands.push({ kind: 'variable', ref: '' })
    }
    
    // If we have more than max (and max is not null), truncate
    if (newOp.maxArity !== null && newOperands.length > newOp.maxArity) {
      newOperands = newOperands.slice(0, newOp.maxArity)
    }

    updateCalculation({
      operator: operatorName,
      operands: newOperands
    })
  }

  // Update a specific operand
  const updateOperand = (index: number, operand: Operand) => {
    const newOperands = [...calculation.operands]
    newOperands[index] = operand
    updateCalculation({ operands: newOperands })
  }

  // Add a new operand (for variadic operators)
  const addOperand = () => {
    if (maxOperands !== null && calculation.operands.length >= maxOperands) return
    updateCalculation({
      operands: [...calculation.operands, { kind: 'variable', ref: '' }]
    })
  }

  // Remove an operand (respecting minimum arity)
  const removeOperand = (index: number) => {
    if (calculation.operands.length <= minOperands) return
    const newOperands = calculation.operands.filter((_, i) => i !== index)
    updateCalculation({ operands: newOperands })
  }

  // Toggle operand between variable and literal
  const toggleOperandKind = (index: number) => {
    const current = calculation.operands[index]
    if (current.kind === 'variable') {
      updateOperand(index, { kind: 'literal', value: 0 })
    } else {
      updateOperand(index, { kind: 'variable', ref: '' })
    }
  }

  // Group operators by category for the dropdown
  const unaryOps = getOperatorsByCategory('unary')
  const binaryOps = getOperatorsByCategory('binary')
  const variadicOps = getOperatorsByCategory('variadic')

  // Check if we can add more operands
  const canAddOperand = maxOperands === null || calculation.operands.length < maxOperands
  const canRemoveOperand = calculation.operands.length > minOperands

  return (
    <>
      <div className="form-divider" />
      <h5>Calculation Configuration</h5>
      <p className="muted small">Define a mathematical operation on workflow variables.</p>

      {/* Output variable name */}
      <div className="form-group">
        <label>Output Variable Name</label>
        <input
          type="text"
          value={calculation.output.name}
          onChange={(e) => updateOutputName(e.target.value)}
          placeholder="e.g., BMI, TotalScore"
        />
        <p className="muted small">
          Name for the calculated result. Will create variable: var_{'{slug}'}_number
        </p>
      </div>

      {/* Output description (optional) */}
      <div className="form-group">
        <label>Description (optional)</label>
        <input
          type="text"
          value={calculation.output.description || ''}
          onChange={(e) => updateOutputDescription(e.target.value)}
          placeholder="e.g., Body Mass Index"
        />
      </div>

      <div className="form-divider" />

      {/* Operator selector */}
      <div className="form-group">
        <label>Operator</label>
        <select
          value={calculation.operator}
          onChange={(e) => handleOperatorChange(e.target.value)}
        >
          <optgroup label="Unary (1 operand)">
            {unaryOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
          <optgroup label="Binary (2 operands)">
            {binaryOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
          <optgroup label="Variadic (2+ operands)">
            {variadicOps.map(op => (
              <option key={op.name} value={op.name}>
                {op.symbol} - {op.displayName}
              </option>
            ))}
          </optgroup>
        </select>
        {selectedOperator && (
          <p className="muted small">{selectedOperator.description}</p>
        )}
      </div>

      <div className="form-divider" />

      {/* Operands section */}
      <div className="form-group">
        <label>
          Operands
          {selectedOperator && (
            <span className="operand-count">
              {' '}({calculation.operands.length}/{maxOperands ?? '∞'})
            </span>
          )}
        </label>

        {numericVariables.length === 0 && (
          <div className="calc-warning">
            <p className="muted small warning">
              No numeric variables defined. Add int, float, or number variables in the Variables panel.
            </p>
          </div>
        )}

        <div className="operands-list">
          {calculation.operands.map((operand, index) => (
            <div className="operand-row" key={index}>
              <span className="operand-index">{index + 1}.</span>
              
              {/* Kind toggle button */}
              <button
                className="operand-kind-toggle ghost"
                onClick={() => toggleOperandKind(index)}
                title={operand.kind === 'variable' ? 'Switch to literal value' : 'Switch to variable'}
              >
                {operand.kind === 'variable' ? 'var' : '123'}
              </button>

              {/* Operand value input */}
              {operand.kind === 'variable' ? (
                <select
                  className="operand-input"
                  value={operand.ref || ''}
                  onChange={(e) => updateOperand(index, { kind: 'variable', ref: e.target.value })}
                >
                  <option value="">Select variable...</option>
                  {numericVariables.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.type})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  className="operand-input"
                  value={operand.value ?? ''}
                  onChange={(e) => updateOperand(index, { 
                    kind: 'literal', 
                    value: parseFloat(e.target.value) || 0 
                  })}
                  placeholder="Enter number"
                  step="any"
                />
              )}

              {/* Remove button */}
              {canRemoveOperand && (
                <button
                  className="operand-remove ghost"
                  onClick={() => removeOperand(index)}
                  title="Remove operand"
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Add operand button (for variadic) */}
        {canAddOperand && (
          <button
            className="ghost add-operand-btn"
            onClick={addOperand}
          >
            + Add Operand
          </button>
        )}
      </div>

      {/* Formula preview */}
      <div className="form-divider" />
      <div className="calc-preview">
        <label>Preview</label>
        <div className="calc-formula">
          {formatCalculationPreview(calculation, analysisInputs)}
        </div>
      </div>

      {/* Validation errors */}
      {validationErrors.length > 0 && (
        <div className="calc-validation-errors">
          <label className="error-label">Validation Issues</label>
          <ul className="error-list">
            {validationErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

/**
 * Format a calculation as a human-readable formula for preview.
 */
function formatCalculationPreview(calc: CalculationConfigType, inputs: WorkflowInput[]): string {
  const op = getOperator(calc.operator)
  if (!op) return '(invalid operator)'
  
  // Format operands
  const formatOperand = (operand: Operand): string => {
    if (operand.kind === 'literal') {
      return String(operand.value ?? '?')
    }
    // Variable reference - show name if found
    const variable = inputs.find(v => v.id === operand.ref)
    return variable?.name ?? (operand.ref || '?')
  }

  const operandStrs = calc.operands.map(formatOperand)
  const outputName = calc.output.name || 'result'

  // Format based on operator category
  if (op.category === 'unary') {
    const arg = operandStrs[0] ?? '?'
    return `${outputName} = ${op.symbol.replace('x', arg)}`
  }
  
  if (op.category === 'binary') {
    const [a, b] = operandStrs
    // Replace 'a' and 'b' in symbol
    let formula = op.symbol.replace('a', a ?? '?').replace('b', b ?? '?')
    return `${outputName} = ${formula}`
  }
  
  // Variadic - join with symbol
  if (operandStrs.length === 0) {
    return `${outputName} = ${op.symbol}(?)`
  }
  
  // Special formatting for function-style operators
  if (['min', 'max', 'sum', 'average', 'hypot', 'variance', 'std_dev', 'range', 'geometric_mean', 'harmonic_mean'].includes(op.name)) {
    return `${outputName} = ${op.name}(${operandStrs.join(', ')})`
  }
  
  // Default: join with symbol
  return `${outputName} = ${operandStrs.join(` ${op.symbol} `)}`
}