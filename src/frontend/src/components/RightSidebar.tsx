import { useState, useCallback, useEffect } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { executeWorkflow } from '../api/execution'
import WorkflowBrowser from './WorkflowBrowser'
import type { SidebarTab, ExecutionResult, InputBlock, InputType, WorkflowAnalysis, WorkflowInput, FlowNode } from '../types'

const slugifyInputName = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')

const buildInputId = (name: string, type: InputType): string => {
  const slug = slugifyInputName(name) || 'input'
  return `input_${slug}_${type}`
}

export default function RightSidebar() {
  const { activeTab, setActiveTab, openModal } = useUIStore()
  const { currentWorkflow, currentAnalysis, setAnalysis, selectedNodeId, flowchart, updateNode } = useWorkflowStore()

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

  // Get input blocks from current workflow
  const inputBlocks = currentWorkflow?.blocks.filter(
    (b): b is InputBlock => b.type === 'input'
  ) || []
  const analysisInputs = currentAnalysis?.inputs ?? []
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
    const existing = analysisInputs.some((input) => {
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
        nextInput.enum = values
      }
    }
    if ((draftType === 'int' || draftType === 'float') && (draftRangeMin || draftRangeMax)) {
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
      inputs: [],
      outputs: [],
      tree: {},
      doubts: [],
    }
    const nextAnalysis: WorkflowAnalysis = {
      ...baseAnalysis,
      inputs: nextInputs,
    }
    setAnalysis(nextAnalysis)
    resetDraftInput()
    setShowAddInput(false)
  }

  const renderAnalysisInput = (input: WorkflowInput) => {
    const enumValues = input.enum ?? input.enum_values ?? []
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
    <aside className="sidebar library-sidebar">
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
          className={`sidebar-tab ${activeTab === 'inputs' ? 'active' : ''}`}
          onClick={() => handleTabClick('inputs')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="12" y1="18" x2="12" y2="12" />
            <line x1="9" y1="15" x2="15" y2="15" />
          </svg>
          <span>Inputs</span>
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

      {/* Inputs panel */}
      <div
        className={`sidebar-panel ${activeTab === 'inputs' ? '' : 'hidden'}`}
        data-panel="inputs"
      >
        {/* ... Inputs content ... */}
        <div className="inputs-header">
          <div>
            <h4>Inputs</h4>
            <p className="muted small">Canonical list for this workflow.</p>
          </div>
          <button
            className="ghost inputs-add-btn"
            onClick={() => {
              if (!currentAnalysis) {
                setAnalysis({ inputs: [], outputs: [], tree: {}, doubts: [] })
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
                    <option value="int">int</option>
                    <option value="float">float</option>
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
                {(draftType === 'int' || draftType === 'float') && (
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
                <p className="muted">No inputs listed yet.</p>
                <p className="muted small">Run analysis or add an input to start the list.</p>
              </div>
            ) : (
              <div className="inputs-list">
                {analysisInputs.map(renderAnalysisInput)}
              </div>
            )}
          </>
        ) : !currentWorkflow ? (
          <div className="inputs-empty">
            <p className="muted">No inputs defined.</p>
            <p className="muted small">Create or load a workflow to see its inputs.</p>
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
                    <option value="int">Integer</option>
                    <option value="float">Float</option>
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

    case 'int':
    case 'float':
      return (
        <div className="input-field">
          <label htmlFor={inputId}>{input.name}</label>
          <input
            type="number"
            id={inputId}
            value={value !== undefined ? String(value) : ''}
            min={input.range?.min}
            max={input.range?.max}
            step={input.input_type === 'float' ? '0.1' : '1'}
            onChange={(e) => {
              const val = input.input_type === 'float'
                ? parseFloat(e.target.value)
                : parseInt(e.target.value, 10)
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