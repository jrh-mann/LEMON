import { useRef, useCallback, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { logoutUser } from '../api/auth'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import type { FlowNode, FlowNodeType } from '../types'
import toast from 'react-hot-toast'

export default function Header() {
  const navigate = useNavigate()
  const { openModal, setError, devMode, toggleDevMode } = useUIStore()
  const { currentWorkflow, flowchart, setFlowchart, setAnalysis } = useWorkflowStore()

  // Secret dev mode activation: 20 rapid clicks on LEMON logo
  const clickCountRef = useRef(0)
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleLogoClick = useCallback(() => {
    clickCountRef.current += 1

    // Reset counter after 5 seconds of inactivity
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current)
    clickTimerRef.current = setTimeout(() => {
      clickCountRef.current = 0
    }, 5000)

    if (clickCountRef.current >= 20) {
      clickCountRef.current = 0
      toggleDevMode()
      toast(devMode ? 'Developer mode disabled' : 'Developer mode enabled', {
        icon: devMode ? '🔒' : '🔧',
        duration: 2000,
      })
    }
  }, [devMode, toggleDevMode])

  const canExport = currentWorkflow || flowchart.nodes.length > 0

  // --- Import JSON state and handlers ---
  const [showJsonInput, setShowJsonInput] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const fileInputRef2 = useRef<HTMLInputElement>(null)

  // Parse and validate workflow JSON — expects new export format only
  const parseWorkflowJson = useCallback((jsonString: string) => {
    const parsed = JSON.parse(jsonString)

    if (!parsed.flowchart || !Array.isArray(parsed.flowchart.nodes)) {
      throw new Error('Invalid format: JSON must have a "flowchart" object with a "nodes" array')
    }

    const nodes: unknown[] = parsed.flowchart.nodes
    const edges: unknown[] = parsed.flowchart.edges || []
    const variables: unknown[] | undefined = parsed.variables || parsed.flowchart.variables
    const outputs: unknown[] | undefined = parsed.outputs || parsed.flowchart.outputs

    const validatedNodes: FlowNode[] = nodes.map((n: unknown, i: number) => {
      const node = n as Record<string, unknown>
      return {
        id: (node.id as string) || `node_${i}`,
        type: (node.type as FlowNodeType) || 'process',
        label: (node.label as string) || `Node ${i + 1}`,
        x: typeof node.x === 'number' ? node.x : 400,
        y: typeof node.y === 'number' ? node.y : 100 + i * 120,
        color: (node.color as FlowNode['color']) || 'teal',
        condition: node.condition as FlowNode['condition'],
        subworkflow_id: node.subworkflow_id as string | undefined,
        input_mapping: node.input_mapping as Record<string, string> | undefined,
        output_variable: node.output_variable as string | undefined,
        output_type: node.output_type as string | undefined,
        output_template: node.output_template as string | undefined,
      }
    })

    const validatedEdges = (edges as Array<Record<string, unknown>>).map((e) => ({
      from: e.from as string,
      to: e.to as string,
      label: (e.label as string) || '',
    }))

    return { nodes: validatedNodes, edges: validatedEdges, variables, outputs }
  }, [])

  const handleJsonImport = useCallback(() => {
    try {
      const { nodes, edges, variables, outputs } = parseWorkflowJson(jsonText)
      setFlowchart({ nodes, edges })
      setAnalysis({
        variables: (variables as never[]) || [],
        outputs: (outputs as never[]) || [],
      })
      setShowJsonInput(false)
      setJsonText('')
      setJsonError(null)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }, [jsonText, setFlowchart, setAnalysis, parseWorkflowJson])

  const handleFileUpload = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string
        const { nodes, edges, variables, outputs } = parseWorkflowJson(content)
        setFlowchart({ nodes, edges })
        setAnalysis({
          variables: (variables as never[]) || [],
          outputs: (outputs as never[]) || [],
        })
        setShowJsonInput(false)
        setJsonText('')
        setJsonError(null)
      } catch (err) {
        setJsonError(err instanceof Error ? err.message : 'Invalid JSON file')
      }
    }
    reader.onerror = () => {
      setJsonError('Failed to read file')
    }
    reader.readAsText(file)

    if (fileInputRef2.current) {
      fileInputRef2.current.value = ''
    }
  }, [setFlowchart, setAnalysis, parseWorkflowJson])

  const handleLogout = useCallback(async () => {
    try {
      await logoutUser()
      navigate('/auth')
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Sign out failed.'
      setError(message)
    }
  }, [setError, navigate])

  return (
    <>
      <header className="app-header animate-slide-down-1">
        <div className="logo" onClick={handleLogoClick} style={{ cursor: 'pointer', position: 'relative' }}>
          <span className="logo-mark">L</span>
          <span className="logo-text">LEMON</span>
          {devMode && (
            <span style={{
              position: 'absolute',
              top: 2,
              right: -6,
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'var(--green)',
              border: '2px solid var(--paper)',
            }} />
          )}
        </div>

        <div className="header-actions">
          <button className="ghost" onClick={() => navigate('/library')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
            </svg>
            Browse Library
          </button>

          <button
            className="primary"
            disabled={!canExport}
            onClick={() => openModal('save')}
            title={canExport ? 'Save workflow to library' : 'No workflow to save'}
          >
            Save
          </button>

          <button
            className="ghost"
            onClick={() => setShowJsonInput(true)}
            title="Import workflow from JSON"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Import
          </button>

          <button
            className="ghost"
            disabled={!canExport}
            onClick={() => navigate('/export')}
            title={canExport ? 'Export workflow' : 'No workflow to export'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export
          </button>

          <button className="ghost" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      {/* Hidden file input for JSON upload — outside header to avoid clipping */}
      <input
        ref={fileInputRef2}
        type="file"
        accept=".json,application/json"
        style={{ display: 'none' }}
        onChange={handleFileUpload}
      />

      {/* JSON Import Modal — outside header so fixed overlay covers full viewport */}
      {showJsonInput && (
        <div className="json-modal-overlay" onClick={() => setShowJsonInput(false)}>
          <div className="json-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Import Workflow JSON</h3>
            <p className="muted small">Upload a JSON file or paste JSON below</p>

            <button
              className="ghost full-width file-upload-btn"
              onClick={() => fileInputRef2.current?.click()}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Choose JSON File
            </button>

            <div className="import-divider">
              <span>or paste JSON</span>
            </div>

            <textarea
              value={jsonText}
              onChange={(e) => {
                setJsonText(e.target.value)
                setJsonError(null)
              }}
              placeholder={`{
  "flowchart": {
    "nodes": [
      {"id": "n1", "type": "start", "label": "Start", "x": 400, "y": 100},
      {"id": "n2", "type": "decision", "label": "Check?", "x": 400, "y": 220}
    ],
    "edges": [
      {"from": "n1", "to": "n2", "label": ""}
    ]
  }
}`}
              rows={10}
            />
            {jsonError && <p className="error-text">{jsonError}</p>}
            <div className="json-modal-actions">
              <button className="ghost" onClick={() => setShowJsonInput(false)}>Cancel</button>
              <button className="primary" onClick={handleJsonImport} disabled={!jsonText.trim()}>Import</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
