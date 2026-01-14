import { useState, useCallback } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { executeWorkflow } from '../api/execution'
import WorkflowBrowser from './WorkflowBrowser'
import type { SidebarTab, ExecutionResult, InputBlock } from '../types'

export default function RightSidebar() {
  const { activeTab, setActiveTab, openModal } = useUIStore()
  const { currentWorkflow } = useWorkflowStore()

  const [inputValues, setInputValues] = useState<Record<string, unknown>>({})
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Get input blocks from current workflow
  const inputBlocks = currentWorkflow?.blocks.filter(
    (b): b is InputBlock => b.type === 'input'
  ) || []

  // Handle input change
  const handleInputChange = useCallback(
    (name: string, value: unknown) => {
      setInputValues((prev) => ({ ...prev, [name]: value }))
    },
    []
  )

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
        {!currentWorkflow ? (
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
