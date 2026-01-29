import { useCallback, useState } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useValidationStore } from '../stores/validationStore'
import { startValidation, submitValidationAnswer } from '../api/validation'
import { createWorkflow, validateWorkflow, type ValidationError } from '../api/workflows'
import {
  startWorkflowExecution,
  pauseWorkflowExecution,
  resumeWorkflowExecution,
  stopWorkflowExecution,
} from '../api/socket'
import WorkflowBrowser from './WorkflowBrowser'
import type { WorkflowInput, WorkflowVariable } from '../types'

export default function Modals() {
  const { modalOpen, closeModal } = useUIStore()

  return (
    <>
      {/* Library Modal */}
      <Modal isOpen={modalOpen === 'library'} onClose={closeModal} title="Workflow Library">
        <WorkflowBrowser />
      </Modal>

      {/* Validation Modal */}
      <Modal isOpen={modalOpen === 'validation'} onClose={closeModal} title="Validate Workflow">
        <ValidationFlow />
      </Modal>

      {/* Save Modal */}
      <Modal isOpen={modalOpen === 'save'} onClose={closeModal} title="Save Workflow">
        <SaveWorkflowForm />
      </Modal>

      {/* Execute Modal */}
      <Modal isOpen={modalOpen === 'execute'} onClose={closeModal} title="Run Workflow">
        <ExecuteWorkflowForm />
      </Modal>
    </>
  )
}

// Generic Modal wrapper
function Modal({
  isOpen,
  onClose,
  title,
  children,
}: {
  isOpen: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}) {
  if (!isOpen) return null

  return (
    <div className="modal open">
      <div className="modal-backdrop" onClick={onClose}></div>
      <div className="modal-content">
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

// Validation flow component
function ValidationFlow() {
  const { currentWorkflow } = useWorkflowStore()
  const {
    sessionId,
    currentCase,
    progress,
    score,
    lastResult,
    isSubmitting,
    startSession,
    handleAnswerResult,
    setSubmitting,
    reset,
  } = useValidationStore()

  const [selectedAnswer, setSelectedAnswer] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Get possible outputs from workflow
  const possibleOutputs = currentWorkflow?.blocks
    .filter((b) => b.type === 'output')
    .map((b) => (b as { value: string }).value) || []

  // Start validation session
  const handleStart = useCallback(async () => {
    if (!currentWorkflow) return

    setError(null)
    try {
      const response = await startValidation({
        workflow_id: currentWorkflow.id,
        case_count: 10,
        strategy: 'comprehensive',
      })

      startSession(response.session_id, response.current_case, response.progress)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start validation')
    }
  }, [currentWorkflow, startSession])

  // Submit answer
  const handleSubmit = useCallback(async () => {
    if (!sessionId || !selectedAnswer) return

    setSubmitting(true)
    setError(null)

    try {
      const response = await submitValidationAnswer({
        session_id: sessionId,
        answer: selectedAnswer,
      })

      handleAnswerResult(
        response.matched,
        response.user_answer,
        response.workflow_output,
        response.next_case,
        response.progress,
        response.current_score
      )

      setSelectedAnswer('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit answer')
      setSubmitting(false)
    }
  }, [sessionId, selectedAnswer, setSubmitting, handleAnswerResult])

  // Reset and start over
  const handleReset = useCallback(() => {
    reset()
    setSelectedAnswer('')
    setError(null)
  }, [reset])

  // No workflow loaded
  if (!currentWorkflow) {
    return (
      <div className="validation-empty">
        <p className="muted">No workflow loaded.</p>
        <p className="muted small">Load a workflow from the library first.</p>
      </div>
    )
  }

  // Not started yet
  if (!sessionId) {
    return (
      <div className="validation-start">
        <h3>Validate: {currentWorkflow.metadata.name}</h3>
        <p className="muted">
          You'll be shown test cases and asked to select the expected output.
          This helps verify the workflow logic is correct.
        </p>
        <button className="primary" onClick={handleStart}>
          Start Validation
        </button>
        {error && <p className="error-text">{error}</p>}
      </div>
    )
  }

  // Session complete
  if (!currentCase && score) {
    return (
      <div className="validation-complete">
        <h3>Validation Complete!</h3>
        <div className="final-score">
          <span className="score-value">{score.score.toFixed(0)}%</span>
          <span className="score-label">
            {score.matches} of {score.total} correct
          </span>
        </div>
        {score.is_validated ? (
          <p className="validation-badge success">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            Workflow is now validated
          </p>
        ) : (
          <p className="validation-badge warning">
            Score below 80% threshold for validation
          </p>
        )}
        <button className="ghost" onClick={handleReset}>
          Start Over
        </button>
      </div>
    )
  }

  // Active validation
  return (
    <div className="validation-active">
      {/* Progress */}
      {progress && (
        <div className="validation-progress">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${(progress.current / progress.total) * 100}%` }}
            />
          </div>
          <span className="progress-text">
            {progress.current} / {progress.total}
          </span>
        </div>
      )}

      {/* Last result feedback */}
      {lastResult && (
        <div className={`last-result ${lastResult.matched ? 'correct' : 'incorrect'}`}>
          {lastResult.matched ? (
            <span>✓ Correct!</span>
          ) : (
            <span>
              ✗ Incorrect. Expected: <strong>{lastResult.workflowOutput}</strong>
            </span>
          )}
        </div>
      )}

      {/* Current case */}
      {currentCase && (
        <div className="current-case">
          <h4>Given these inputs:</h4>
          <div className="case-inputs">
            {Object.entries(currentCase.inputs).map(([key, value]) => (
              <div key={key} className="input-row">
                <span className="input-name">{key}:</span>
                <span className="input-value">{String(value)}</span>
              </div>
            ))}
          </div>

          <h4>What should the output be?</h4>
          <div className="answer-options">
            {possibleOutputs.map((output) => (
              <button
                key={output}
                className={`answer-option ${selectedAnswer === output ? 'selected' : ''}`}
                onClick={() => setSelectedAnswer(output)}
              >
                {output}
              </button>
            ))}
          </div>

          <button
            className="primary"
            onClick={handleSubmit}
            disabled={!selectedAnswer || isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit Answer'}
          </button>

          {error && <p className="error-text">{error}</p>}
        </div>
      )}

      {/* Current score */}
      {score && (
        <div className="current-score">
          Current score: {score.score.toFixed(0)}% ({score.matches}/{score.total})
        </div>
      )}
    </div>
  )
}

// Save workflow form component
function SaveWorkflowForm() {
  const { closeModal } = useUIStore()
  const { flowchart, currentAnalysis } = useWorkflowStore()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState('')
  const [tags, setTags] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [validationErrors, setValidationErrors] = useState<ValidationError[] | null>(null)
  const [showValidationWarning, setShowValidationWarning] = useState(false)

  const handleSave = useCallback(async (skipValidation = false) => {
    if (!name.trim()) {
      setSaveError('Workflow name is required')
      return
    }

    if (flowchart.nodes.length === 0) {
      setSaveError('Cannot save empty workflow')
      return
    }

    setIsSaving(true)
    setSaveError(null)
    setValidationErrors(null)

    try {
      // Validate workflow first (unless explicitly skipping)
      if (!skipValidation) {
        const validationResult = await validateWorkflow({
          nodes: flowchart.nodes,
          edges: flowchart.edges,
          inputs: currentAnalysis?.variables || [],  // Backend expects 'inputs'
        })

        if (!validationResult.valid) {
          // Show validation errors and ask user to confirm
          setValidationErrors(validationResult.errors || [])
          setShowValidationWarning(true)
          setIsSaving(false)
          return
        }
      }

      // Parse tags from comma-separated string
      const tagArray = tags
        .split(',')
        .map(t => t.trim())
        .filter(t => t.length > 0)

      // Create workflow payload
      const payload = {
        name: name.trim(),
        description: description.trim(),
        domain: domain.trim() || undefined,
        tags: tagArray,
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],  // Unified variable system
        inputs: currentAnalysis?.variables || [],     // Backend compatibility
        outputs: currentAnalysis?.outputs || [],
        tree: currentAnalysis?.tree || {},
        doubts: currentAnalysis?.doubts || [],
        validation_score: 0,
        validation_count: 0,
        is_validated: false,
      }

      await createWorkflow(payload)

      setSaveSuccess(true)
      setShowValidationWarning(false)
      setValidationErrors(null)

      // Close modal after short delay to show success message
      setTimeout(() => {
        closeModal()
        setSaveSuccess(false)
        setName('')
        setDescription('')
        setDomain('')
        setTags('')
      }, 1500)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save workflow')
      setIsSaving(false)
    }
  }, [name, description, domain, tags, flowchart, currentAnalysis, closeModal])

  if (flowchart.nodes.length === 0) {
    return (
      <div className="save-empty">
        <p className="muted">No workflow to save.</p>
        <p className="muted small">Create a workflow first by chatting with the assistant.</p>
      </div>
    )
  }

  if (saveSuccess) {
    return (
      <div className="save-success">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <h3>Workflow Saved!</h3>
        <p className="muted">Your workflow has been saved to your library.</p>
      </div>
    )
  }

  return (
    <div className="save-form">
      <div className="form-group">
        <label htmlFor="workflow-name">
          Workflow Name <span className="required">*</span>
        </label>
        <input
          id="workflow-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Enter workflow name"
          disabled={isSaving}
          autoFocus
        />
      </div>

      <div className="form-group">
        <label htmlFor="workflow-description">Description</label>
        <textarea
          id="workflow-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe what this workflow does"
          disabled={isSaving}
          rows={3}
        />
      </div>

      <div className="form-group">
        <label htmlFor="workflow-domain">Domain</label>
        <input
          id="workflow-domain"
          type="text"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          placeholder="e.g., Healthcare, Finance, Education"
          disabled={isSaving}
        />
      </div>

      <div className="form-group">
        <label htmlFor="workflow-tags">Tags</label>
        <input
          id="workflow-tags"
          type="text"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="Comma-separated tags (e.g., diabetes, triage, urgent)"
          disabled={isSaving}
        />
        <small className="muted">Separate tags with commas</small>
      </div>

      {saveError && <p className="error-text">{saveError}</p>}

      {showValidationWarning && validationErrors && (
        <div className="validation-warning">
          <h4>⚠️ Workflow Validation Failed</h4>
          <p>The workflow has the following issues:</p>
          <ul className="validation-errors">
            {validationErrors.map((error, idx) => (
              <li key={idx}>
                <strong>{error.code}:</strong> {error.message}
                {error.node_id && <span className="node-ref"> (Node: {error.node_id})</span>}
              </li>
            ))}
          </ul>
          <p className="muted">You can still save this workflow, but it may not execute correctly.</p>
          <div className="validation-actions">
            <button
              className="ghost"
              onClick={() => {
                setShowValidationWarning(false)
                setValidationErrors(null)
              }}
            >
              Cancel
            </button>
            <button
              className="primary warning"
              onClick={() => handleSave(true)}
              disabled={isSaving}
            >
              Save Anyway
            </button>
          </div>
        </div>
      )}

      {!showValidationWarning && (
        <div className="form-actions">
          <button className="ghost" onClick={closeModal} disabled={isSaving}>
            Cancel
          </button>
          <button className="primary" onClick={() => handleSave(false)} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save Workflow'}
          </button>
        </div>
      )}
    </div>
  )
}

// Execute workflow form component - similar to SaveWorkflowForm
// Allows user to provide input values and run the workflow with visual execution
function ExecuteWorkflowForm() {
  const { closeModal } = useUIStore()
  const {
    flowchart,
    currentAnalysis,
    execution,
    setExecutionSpeed,
    clearExecution,
  } = useWorkflowStore()

  // Initialize input values from workflow variables
  const workflowInputs = currentAnalysis?.variables ?? []
  const [inputValues, setInputValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {}
    for (const input of workflowInputs) {
      switch (input.type) {
        case 'bool':
          initial[input.id] = false
          break
        case 'int':
        case 'float':
          initial[input.id] = input.range?.min ?? 0
          break
        case 'enum':
          const enumVals = input.enum_values ?? []
          initial[input.id] = enumVals[0] ?? ''
          break
        case 'date':
          initial[input.id] = new Date().toISOString().split('T')[0]
          break
        case 'string':
        default:
          initial[input.id] = ''
          break
      }
    }
    return initial
  })

  // Handle input value change
  const handleInputChange = useCallback((inputId: string, value: unknown) => {
    setInputValues((prev) => ({ ...prev, [inputId]: value }))
  }, [])

  // Handle speed slider change
  const handleSpeedChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = parseInt(e.target.value, 10)
      setExecutionSpeed(value)
    },
    [setExecutionSpeed]
  )

  // Start execution - closes modal immediately so user can watch canvas
  // Modal will reopen when execution completes or errors (handled by socket.ts)
  const handleRun = useCallback(() => {
    startWorkflowExecution(inputValues, execution.executionSpeed)
    closeModal()  // Close modal so user can see the canvas with execution highlighting
  }, [inputValues, execution.executionSpeed, closeModal])

  // Render input field based on type
  const renderInputField = (input: WorkflowInput) => {
    const inputId = `exec-input-${input.id}`
    const value = inputValues[input.id]

    switch (input.type) {
      case 'bool':
        return (
          <div className="form-group checkbox-group">
            <label>
              <input
                id={inputId}
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => handleInputChange(input.id, e.target.checked)}
                disabled={execution.isExecuting}
              />
              {input.name}
            </label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
          </div>
        )

      case 'int':
        return (
          <div className="form-group">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
            <input
              id={inputId}
              type="number"
              step="1"
              min={input.range?.min}
              max={input.range?.max}
              value={Number(value)}
              onChange={(e) => handleInputChange(input.id, parseInt(e.target.value, 10))}
              disabled={execution.isExecuting}
            />
          </div>
        )

      case 'float':
        return (
          <div className="form-group">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
            <input
              id={inputId}
              type="number"
              step="0.01"
              min={input.range?.min}
              max={input.range?.max}
              value={Number(value)}
              onChange={(e) => handleInputChange(input.id, parseFloat(e.target.value))}
              disabled={execution.isExecuting}
            />
          </div>
        )

      case 'enum':
        const enumValues = input.enum_values ?? []
        return (
          <div className="form-group">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
            <select
              id={inputId}
              value={String(value)}
              onChange={(e) => handleInputChange(input.id, e.target.value)}
              disabled={execution.isExecuting}
            >
              {enumValues.map((opt: string) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )

      case 'date':
        return (
          <div className="form-group">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
            <input
              id={inputId}
              type="date"
              value={String(value)}
              onChange={(e) => handleInputChange(input.id, e.target.value)}
              disabled={execution.isExecuting}
            />
          </div>
        )

      case 'string':
      default:
        return (
          <div className="form-group">
            <label htmlFor={inputId}>{input.name}</label>
            {input.description && (
              <small className="muted">{input.description}</small>
            )}
            <input
              id={inputId}
              type="text"
              value={String(value)}
              onChange={(e) => handleInputChange(input.id, e.target.value)}
              placeholder={`Enter ${input.name}`}
              disabled={execution.isExecuting}
            />
          </div>
        )
    }
  }

  // No workflow to execute
  if (flowchart.nodes.length === 0) {
    return (
      <div className="execute-empty">
        <p className="muted">No workflow to run.</p>
        <p className="muted small">Create a workflow first by chatting with the assistant.</p>
      </div>
    )
  }

  // Execution complete - show results
  if (!execution.isExecuting && (execution.executionOutput !== null || execution.executionError)) {
    return (
      <div className="execute-complete">
        {execution.executionError ? (
          <>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </svg>
            <h3>Execution Failed</h3>
            <p className="error-text">{execution.executionError}</p>
          </>
        ) : (
          <>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            <h3>Execution Complete</h3>
            <div className="execution-result">
              <span className="result-label">Output:</span>
              <code className="result-value">
                {typeof execution.executionOutput === 'object'
                  ? JSON.stringify(execution.executionOutput, null, 2)
                  : String(execution.executionOutput)}
              </code>
            </div>
          </>
        )}
        <div className="execution-path">
          <span className="path-label">Execution path:</span>
          <span className="path-value">{execution.executionPath.length} nodes</span>
        </div>
        <div className="form-actions">
          <button className="ghost" onClick={closeModal}>
            Close
          </button>
          <button className="primary" onClick={clearExecution}>
            Run Again
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="execute-form">
      {/* Input fields section */}
      {workflowInputs.length > 0 ? (
        <div className="inputs-section">
          <h4>Workflow Inputs</h4>
          <p className="muted small">Provide values for the workflow inputs</p>
          {workflowInputs.map((input: WorkflowVariable) => (
            <div key={input.id}>{renderInputField(input)}</div>
          ))}
        </div>
      ) : (
        <div className="no-inputs-notice">
          <p className="muted">This workflow has no defined inputs.</p>
        </div>
      )}

      {/* Speed control */}
      <div className="form-group speed-control-group">
        <label htmlFor="exec-speed">
          Execution Speed: {execution.executionSpeed}ms
        </label>
        <input
          id="exec-speed"
          type="range"
          min="100"
          max="2000"
          step="100"
          value={execution.executionSpeed}
          onChange={handleSpeedChange}
          disabled={execution.isExecuting}
        />
        <div className="speed-labels">
          <span className="muted small">Fast (100ms)</span>
          <span className="muted small">Slow (2000ms)</span>
        </div>
      </div>

      {/* Execution status */}
      {execution.isExecuting && (
        <div className="execution-status-bar">
          <div className={`status-indicator ${execution.isPaused ? 'paused' : 'running'}`} />
          <span>{execution.isPaused ? 'Paused' : 'Running...'}</span>
          {execution.executingNodeId && (
            <span className="current-node">
              Current: {flowchart.nodes.find(n => n.id === execution.executingNodeId)?.label || execution.executingNodeId}
            </span>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="form-actions">
        {!execution.isExecuting ? (
          <>
            <button className="ghost" onClick={closeModal}>
              Cancel
            </button>
            <button className="primary run-btn" onClick={handleRun}>
              <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                <path d="M8 5v14l11-7z" />
              </svg>
              Run Workflow
            </button>
          </>
        ) : (
          <>
            {execution.isPaused ? (
              <button className="primary" onClick={resumeWorkflowExecution}>
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                  <path d="M8 5v14l11-7z" />
                </svg>
                Resume
              </button>
            ) : (
              <button className="ghost" onClick={pauseWorkflowExecution}>
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                  <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                </svg>
                Pause
              </button>
            )}
            <button className="ghost warning" onClick={stopWorkflowExecution}>
              <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                <rect x="6" y="6" width="12" height="12" />
              </svg>
              Stop
            </button>
          </>
        )}
      </div>
    </div>
  )
}
