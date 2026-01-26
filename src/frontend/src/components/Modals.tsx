import { useCallback, useState } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useValidationStore } from '../stores/validationStore'
import { startValidation, submitValidationAnswer } from '../api/validation'
import { createWorkflow, validateWorkflow, ValidationError } from '../api/workflows'
import WorkflowBrowser from './WorkflowBrowser'

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
  const { closeModal, setError } = useUIStore()
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
          inputs: currentAnalysis?.inputs || [],
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
        inputs: currentAnalysis?.inputs || [],
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
