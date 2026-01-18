import { useCallback, useState } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useValidationStore } from '../stores/validationStore'
import { startValidation, submitValidationAnswer } from '../api/validation'
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
