/**
 * Miro Import Modal
 *
 * Allows users to connect their Miro account and import flowcharts
 * as LEMON workflows.
 */

import { useState, useEffect } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import {
  getMiroStatus,
  startMiroOAuth,
  disconnectMiro,
  listMiroBoards,
  importMiroBoard,
  confirmMiroImport,
  type MiroBoard,
  type MiroImportResponse,
} from '../api/miro'
import type { Flowchart, Workflow, WorkflowAnalysis } from '../types'

type ImportStep = 'connect' | 'select' | 'preview' | 'success'

export default function MiroImportModal() {
  const { closeModal } = useUIStore()
  const { addTab, setAnalysis } = useWorkflowStore()

  // Connection state (isConnected is set but checked via step state)
  const [, setIsConnected] = useState(false)
  const [isCheckingConnection, setIsCheckingConnection] = useState(true)

  // Import flow state
  const [step, setStep] = useState<ImportStep>('connect')
  const [boardUrl, setBoardUrl] = useState('')
  const [boards, setBoards] = useState<MiroBoard[]>([])
  const [isLoadingBoards, setIsLoadingBoards] = useState(false)
  const [selectedBoard, setSelectedBoard] = useState<string | null>(null)

  // Import result state
  const [importResult, setImportResult] = useState<MiroImportResponse | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  // UI state
  const [error, setError] = useState<string | null>(null)
  const [showConventions, setShowConventions] = useState(false)

  // Check connection status on mount
  useEffect(() => {
    checkConnectionStatus()
  }, [])

  const checkConnectionStatus = async () => {
    setIsCheckingConnection(true)
    try {
      const status = await getMiroStatus()
      setIsConnected(status.connected)
      if (status.connected) {
        setStep('select')
        // Load user's boards when connected
        loadBoardsAsync()
      }
    } catch (err) {
      console.error('Failed to check Miro status:', err)
    } finally {
      setIsCheckingConnection(false)
    }
  }

  // Load user's boards (async helper to avoid function hoisting issues)
  const loadBoardsAsync = async () => {
    setIsLoadingBoards(true)
    setError(null)
    try {
      const boardList = await listMiroBoards()
      setBoards(boardList)
    } catch (err) {
      // Don't show error for listing boards - user can paste URL instead
      console.error('Failed to load boards:', err)
    } finally {
      setIsLoadingBoards(false)
    }
  }

  // Connect via OAuth - redirects to Miro
  const handleConnect = () => {
    startMiroOAuth()
    // User will be redirected to Miro, then back to /#/miro-callback
  }

  // Disconnect
  const handleDisconnect = async () => {
    try {
      await disconnectMiro()
      setIsConnected(false)
      setStep('connect')
      setBoards([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect')
    }
  }

  // Import board
  const handleImport = async () => {
    const boardInput = boardUrl.trim() || selectedBoard
    if (!boardInput) {
      setError('Please enter a board URL or select a board')
      return
    }

    setIsImporting(true)
    setError(null)

    try {
      const result = await importMiroBoard(boardInput)

      if (!result.success) {
        setError(result.error || 'Import failed')
        return
      }

      setImportResult(result)
      setStep('preview')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setIsImporting(false)
    }
  }

  // Confirm and save import
  const handleConfirmImport = async () => {
    if (!importResult?.workflow) return

    setIsSaving(true)
    setError(null)

    try {
      const response = await confirmMiroImport(
        importResult.workflow,
        importResult.inferences.map((i) => i.id)
      )

      setStep('success')

      // Open the workflow in a new tab
      const flowchart: Flowchart = {
        nodes: importResult.workflow.nodes,
        edges: importResult.workflow.edges,
      }

      const workflow: Workflow = {
        id: response.workflow_id,
        output_type: importResult.workflow.output_type,
        metadata: {
          name: importResult.workflow.name,
          description: importResult.workflow.description,
          domain: 'imported',
          tags: ['miro-import'],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          validation_score: 0,
          validation_count: 0,
          confidence: 'none',
          is_validated: false,
        },
        blocks: [],
        connections: [],
      }

      addTab(importResult.workflow.name, workflow, flowchart)

      // Set analysis data
      const analysis: WorkflowAnalysis = {
        variables: importResult.workflow.variables,
        outputs: [],
        tree: {},
        doubts: [],
      }
      setAnalysis(analysis)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save workflow')
    } finally {
      setIsSaving(false)
    }
  }

  // Render connection step
  const renderConnectStep = () => (
    <div className="miro-connect-step">
      <div className="miro-info">
        <h3>Connect to Miro</h3>
        <p>
          To import flowcharts from Miro, connect your Miro account.
          You'll be redirected to Miro to authorize LEMON to read your boards.
        </p>
      </div>

      <div className="miro-oauth-info">
        <div className="oauth-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>
        <ul className="oauth-benefits">
          <li>Secure OAuth 2.0 authentication</li>
          <li>LEMON only gets read access to your boards</li>
          <li>You can disconnect anytime</li>
        </ul>
      </div>

      <div className="miro-actions">
        <button onClick={closeModal} className="btn-secondary">
          Cancel
        </button>
        <button onClick={handleConnect} className="btn-primary miro-connect-btn-large">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
            <polyline points="10 17 15 12 10 7" />
            <line x1="15" y1="12" x2="3" y2="12" />
          </svg>
          Connect to Miro
        </button>
      </div>
    </div>
  )

  // Render board selection step
  const renderSelectStep = () => (
    <div className="miro-select-step">
      <div className="miro-connection-status">
        <span className="connected-badge">Connected to Miro</span>
        <button onClick={handleDisconnect} className="btn-link">
          Disconnect
        </button>
      </div>

      <div className="miro-board-input">
        <label htmlFor="board-url">Paste Miro Board URL</label>
        <input
          id="board-url"
          type="text"
          value={boardUrl}
          onChange={(e) => {
            setBoardUrl(e.target.value)
            setSelectedBoard(null)
          }}
          placeholder="https://miro.com/app/board/..."
        />
      </div>

      {boards.length > 0 && (
        <>
          <div className="miro-or-divider">
            <span>or select from your boards</span>
          </div>

          <div className="miro-board-list">
            {boards.map((board) => (
              <button
                key={board.id}
                className={`miro-board-item ${selectedBoard === board.id ? 'selected' : ''}`}
                onClick={() => {
                  setSelectedBoard(board.id)
                  setBoardUrl('')
                }}
              >
                <span className="board-name">{board.name}</span>
                {board.description && (
                  <span className="board-description">{board.description}</span>
                )}
              </button>
            ))}
          </div>
        </>
      )}

      {isLoadingBoards && <p className="loading-text">Loading your boards...</p>}

      {!isLoadingBoards && boards.length === 0 && (
        <button onClick={loadBoardsAsync} className="btn-link" style={{ marginTop: '0.5rem' }}>
          Load my boards
        </button>
      )}

      <div className="miro-actions">
        <button onClick={() => setShowConventions(true)} className="btn-link">
          Conventions Guide
        </button>
        <div className="miro-actions-right">
          <button onClick={closeModal} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={isImporting || (!boardUrl && !selectedBoard)}
            className="btn-primary"
          >
            {isImporting ? 'Importing...' : 'Import'}
          </button>
        </div>
      </div>

      {/* Conventions Guide Popup */}
      {showConventions && (
        <div className="conventions-popup-overlay" onClick={() => setShowConventions(false)}>
          <div className="conventions-popup" onClick={(e) => e.stopPropagation()}>
            <div className="conventions-popup-header">
              <h3>Miro Board Conventions</h3>
              <button onClick={() => setShowConventions(false)} className="popup-close">×</button>
            </div>
            <div className="conventions-popup-body">
              <ConventionsGuide />
            </div>
          </div>
        </div>
      )}
    </div>
  )

  // Render preview step
  const renderPreviewStep = () => {
    if (!importResult?.workflow) return null

    return (
      <div className="miro-preview-step">
        <h3>Import Preview</h3>

        <div className="import-stats">
          <div className="stat">
            <span className="stat-value">{importResult.stats?.nodes || 0}</span>
            <span className="stat-label">Nodes</span>
          </div>
          <div className="stat">
            <span className="stat-value">{importResult.stats?.edges || 0}</span>
            <span className="stat-label">Connections</span>
          </div>
          <div className="stat">
            <span className="stat-value">{importResult.stats?.variables || 0}</span>
            <span className="stat-label">Variables</span>
          </div>
        </div>

        {/* Node preview list */}
        {importResult.workflow.nodes && importResult.workflow.nodes.length > 0 && (
          <div className="import-nodes-preview">
            <h4>Nodes</h4>
            <ul className="nodes-list">
              {importResult.workflow.nodes.map((node: { id: string; type: string; label: string; _miro_type?: string }) => (
                <li key={node.id} className={`node-item node-type-${node.type}`}>
                  <span className="node-type-badge">{node.type}</span>
                  <span className="node-label">{node.label}</span>
                  {node._miro_type && (
                    <span className="node-miro-type">(Miro: {node._miro_type})</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {importResult.warnings.length > 0 && (
          <div className="import-warnings">
            <h4>Warnings ({importResult.warnings.length})</h4>
            <ul>
              {importResult.warnings.map((warning, i) => (
                <li key={i} className="warning-item">
                  <span className="warning-code">{warning.code}</span>
                  <span className="warning-message">{warning.message}</span>
                  {warning.fix && <span className="warning-fix">Fix: {warning.fix}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {importResult.inferences.length > 0 && (
          <div className="import-inferences">
            <h4>AI Inferences ({importResult.inferences.length})</h4>
            <p className="inference-note">
              These elements couldn't be parsed automatically. AI has made suggestions.
            </p>
            <ul>
              {importResult.inferences.map((inference, i) => (
                <li key={i} className="inference-item">
                  <span className="inference-type">{inference.type}</span>
                  <span className="inference-original">"{inference.original_text}"</span>
                  <span className={`inference-confidence ${inference.confidence}`}>
                    {inference.confidence} confidence
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="miro-actions">
          <button onClick={() => setStep('select')} className="btn-secondary">
            Back
          </button>
          <button onClick={handleConfirmImport} disabled={isSaving} className="btn-primary">
            {isSaving ? 'Saving...' : 'Create Workflow'}
          </button>
        </div>
      </div>
    )
  }

  // Render success step
  const renderSuccessStep = () => (
    <div className="miro-success-step">
      <div className="success-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      </div>
      <h3>Workflow Imported!</h3>
      <p>Your Miro flowchart has been converted to a LEMON workflow and opened in a new tab.</p>

      <div className="miro-actions">
        <button onClick={closeModal} className="btn-primary">
          Done
        </button>
      </div>
    </div>
  )

  // Main render
  if (isCheckingConnection) {
    return (
      <div className="miro-import-modal">
        <p className="loading-text">Checking Miro connection...</p>
      </div>
    )
  }

  return (
    <div className="miro-import-modal">
      {error && (
        <div className="miro-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {step === 'connect' && renderConnectStep()}
      {step === 'select' && renderSelectStep()}
      {step === 'preview' && renderPreviewStep()}
      {step === 'success' && renderSuccessStep()}
    </div>
  )
}

// Conventions Guide Component
function ConventionsGuide() {
  return (
    <div className="conventions-guide">
      <h4>Miro Board Conventions</h4>

      <div className="convention-section">
        <h5>Shapes</h5>
        <ul>
          <li>
            <span className="shape-icon terminator">○</span>
            <strong>Terminator (rounded)</strong> → Start/End nodes
          </li>
          <li>
            <span className="shape-icon process">□</span>
            <strong>Rectangle</strong> → Process steps
          </li>
          <li>
            <span className="shape-icon decision">◇</span>
            <strong>Diamond</strong> → Decision nodes
          </li>
          <li>
            <span className="shape-icon subprocess">⧈</span>
            <strong>Predefined Process</strong> → Subprocess calls
          </li>
          <li>
            <span className="shape-icon input">▱</span>
            <strong>Parallelogram</strong> → Variable declaration
          </li>
        </ul>
      </div>

      <div className="convention-section">
        <h5>Decision Conditions</h5>
        <p>Format: <code>variable operator value</code></p>
        <div className="examples">
          <span className="good">✓ age &gt;= 18</span>
          <span className="good">✓ status == "active"</span>
          <span className="bad">✗ Is the user an adult?</span>
        </div>
      </div>

      <div className="convention-section">
        <h5>Connector Labels</h5>
        <p>Label decision branches: <strong>Yes/No</strong> or <strong>True/False</strong></p>
      </div>

      <div className="convention-tip">
        <strong>Tip:</strong> Boards that don't follow conventions will still import —
        you'll see warnings and can use AI to help interpret non-standard elements.
      </div>
    </div>
  )
}
