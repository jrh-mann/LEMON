import { useCallback, useRef, useState, type ChangeEvent } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { generateNodeId } from '../utils/canvas'
import type { FlowNodeType, FlowNode } from '../types'
import DevToolsPanel from './DevToolsPanel'

interface BlockConfig {
  type: FlowNodeType
  label: string
  defaultLabel: string
  icon: React.ReactNode
}

const BLOCKS: BlockConfig[] = [
  {
    type: 'start',
    label: 'Start',
    defaultLabel: 'Input',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="4" />
      </svg>
    )
  },
  {
    type: 'decision',
    label: 'Decision',
    defaultLabel: 'Condition?',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M9.5 9.5L12 12m0 0l2.5 2.5M12 12l2.5-2.5M12 12l-2.5 2.5" />
      </svg>
    )
  },
  {
    type: 'calculation',
    label: 'Calculation',
    defaultLabel: 'Calculate',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M9 7h6M12 4v6M7 13h10M9 17h6" />
      </svg>
    )
  },
  {
    type: 'end',
    label: 'Output',
    defaultLabel: 'Result',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    )
  },
  {
    type: 'subprocess',
    label: 'Subflow',
    defaultLabel: 'Workflow',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <rect x="6" y="6" width="12" height="12" rx="2" />
      </svg>
    )
  },
]

export default function Palette() {
  const { addNode, flowchart, setFlowchart, setAnalysis } = useWorkflowStore()
  const { openModal, devMode } = useUIStore()
  const dragDataRef = useRef<BlockConfig | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showJsonInput, setShowJsonInput] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  // Parse and validate workflow JSON - handles both old and new formats
  const parseWorkflowJson = useCallback((jsonString: string) => {
    const parsed = JSON.parse(jsonString)

    // Detect format: new format has flowchart.nodes, old format has nodes at root
    let nodes: unknown[]
    let edges: unknown[]
    let variables: unknown[] | undefined
    let outputs: unknown[] | undefined

    if (parsed.flowchart && Array.isArray(parsed.flowchart.nodes)) {
      // New export format: { id, metadata, flowchart: { nodes, edges }, variables, outputs }
      nodes = parsed.flowchart.nodes
      edges = parsed.flowchart.edges || []
      // Extract analysis data - check multiple possible keys for backwards compatibility
      variables = parsed.variables || parsed.inputs || parsed.flowchart.variables || parsed.flowchart.inputs
      outputs = parsed.outputs || parsed.flowchart.outputs
    } else if (Array.isArray(parsed.nodes)) {
      // Old format: { nodes, edges } at root level
      nodes = parsed.nodes
      edges = parsed.edges || []
      // Check both 'variables' and 'inputs' for backwards compatibility
      variables = parsed.variables || parsed.inputs
      outputs = parsed.outputs
    } else {
      throw new Error('Invalid format: JSON must have "nodes" array (either at root or under "flowchart")')
    }

    // Validate and normalize nodes
    const validatedNodes: FlowNode[] = nodes.map((n: unknown, i: number) => {
      const node = n as Record<string, unknown>
      return {
        id: (node.id as string) || `node_${i}`,
        type: (node.type as FlowNodeType) || 'process',
        label: (node.label as string) || `Node ${i + 1}`,
        x: typeof node.x === 'number' ? node.x : 400,
        y: typeof node.y === 'number' ? node.y : 100 + i * 120,
        color: (node.color as FlowNode['color']) || 'teal',
        // Preserve additional node properties
        condition: node.condition as FlowNode['condition'],
        subworkflow_id: node.subworkflow_id as string | undefined,
        input_mapping: node.input_mapping as Record<string, string> | undefined,
        output_variable: node.output_variable as string | undefined,
        output_type: node.output_type as string | undefined,
        output_template: node.output_template as string | undefined,
      }
    })

    // Validate edges
    const validatedEdges = (edges as Array<Record<string, unknown>>).map((e) => ({
      from: e.from as string,
      to: e.to as string,
      label: (e.label as string) || '',
    }))

    return { nodes: validatedNodes, edges: validatedEdges, variables, outputs }
  }, [])

  // Handle JSON import from text
  const handleJsonImport = useCallback(() => {
    try {
      const { nodes, edges, variables, outputs } = parseWorkflowJson(jsonText)

      setFlowchart({ nodes, edges })

      // Always set analysis - use imported data or empty arrays
      // This ensures the Variables panel is properly initialized
      setAnalysis({
        variables: (variables as never[]) || [],
        outputs: (outputs as never[]) || [],
        tree: {},
        doubts: [],
      })

      setShowJsonInput(false)
      setJsonText('')
      setJsonError(null)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }, [jsonText, setFlowchart, setAnalysis, parseWorkflowJson])

  // Handle file upload
  const handleFileUpload = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string
        const { nodes, edges, variables, outputs } = parseWorkflowJson(content)

        setFlowchart({ nodes, edges })

        // Always set analysis - use imported data or empty arrays
        // This ensures the Variables panel is properly initialized
        setAnalysis({
          variables: (variables as never[]) || [],
          outputs: (outputs as never[]) || [],
          tree: {},
          doubts: [],
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

    // Reset input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }, [setFlowchart, setAnalysis, parseWorkflowJson])

  // Handle drag start
  const handleDragStart = useCallback(
    (e: React.DragEvent, block: BlockConfig) => {
      dragDataRef.current = block
      e.dataTransfer.setData('text/plain', block.type)
      e.dataTransfer.effectAllowed = 'copy'
    },
    []
  )

  // Handle drag end (drop on canvas)
  const handleDragEnd = useCallback(() => {
    dragDataRef.current = null
  }, [])

  // Handle click to add node at default position
  const handleClick = useCallback(
    (block: BlockConfig) => {
      // Calculate position based on existing nodes
      const existingNodes = flowchart.nodes
      let x = 600
      let y = 100

      if (existingNodes.length > 0) {
        // Place below the lowest node
        const maxY = Math.max(...existingNodes.map((n) => n.y))
        y = maxY + 150
      }

      addNode({
        id: generateNodeId(),
        type: block.type,
        label: block.defaultLabel,
        x,
        y,
        color: 'teal',
      })
    },
    [addNode, flowchart.nodes]
  )

  // Handle Run button click - opens the execute modal
  const handleRunClick = useCallback(() => {
    openModal('execute')
  }, [openModal])

  return (
    <aside className="sidebar palette-sidebar">
      <div className="sidebar-section">
        <p className="eyebrow">BLOCKS</p>
        <div className="block-palette">
          {BLOCKS.map((block) => (
            <button
              key={block.type}
              className="palette-block"
              data-type={block.type}
              draggable="true"
              onDragStart={(e) => handleDragStart(e, block)}
              onDragEnd={handleDragEnd}
              onClick={() => handleClick(block)}
              title={`Click to add ${block.label} block`}
            >
              <div className={`block-icon ${block.type}-icon`}>{block.icon}</div>
              <span>{block.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Run Workflow Button */}
      <div className="sidebar-section">
        <p className="eyebrow">EXECUTE</p>
        <button
          className="run-btn full-width"
          onClick={handleRunClick}
          disabled={flowchart.nodes.length === 0}
          title="Run workflow with visual execution"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
            <path d="M8 5v14l11-7z" />
          </svg>
          Run Workflow
        </button>
      </div>

      <div className="sidebar-section">
        <p className="eyebrow">TIPS</p>
        <ul className="tips-list">
          <li>Click a block to add it to canvas</li>
          <li>Double-click a node to start connecting</li>
          <li>Press Delete to remove selected node</li>
          <li>Cmd+Z to undo, Cmd+Shift+Z to redo</li>
        </ul>
      </div>

      <div className="sidebar-section">
        <p className="eyebrow">IMPORT</p>
        <button
          className="ghost full-width"
          onClick={() => setShowJsonInput(true)}
          title="Import flowchart from JSON"
        >
          Import JSON
        </button>
        <button
          className="ghost full-width"
          onClick={() => {
            // Sample flowchart with proper English labels
            const sampleFlowchart = {
              nodes: [
                { id: 'n1', type: 'start' as const, label: 'Patient Arrives', x: 400, y: 100, color: 'teal' as const },
                { id: 'n2', type: 'process' as const, label: 'Check Vitals', x: 400, y: 220, color: 'teal' as const },
                { id: 'n3', type: 'decision' as const, label: 'Temperature > 38C?', x: 400, y: 340, color: 'amber' as const },
                { id: 'n4', type: 'process' as const, label: 'Administer Fever Medication', x: 200, y: 460, color: 'teal' as const },
                { id: 'n5', type: 'process' as const, label: 'Continue Monitoring', x: 600, y: 460, color: 'teal' as const },
                { id: 'n6', type: 'end' as const, label: 'Discharge Patient', x: 400, y: 580, color: 'green' as const },
              ],
              edges: [
                { from: 'n1', to: 'n2', label: '' },
                { from: 'n2', to: 'n3', label: '' },
                { from: 'n3', to: 'n4', label: 'Yes' },
                { from: 'n3', to: 'n5', label: 'No' },
                { from: 'n4', to: 'n6', label: '' },
                { from: 'n5', to: 'n6', label: '' },
              ],
            }
            setFlowchart(sampleFlowchart)
          }}
          title="Load a sample flowchart to test frontend rendering"
        >
          Load Example
        </button>
      </div>

      {/* Hidden file input for JSON upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        style={{ display: 'none' }}
        onChange={handleFileUpload}
      />

      {/* Developer Tools Panel - shown when devMode is on */}
      {devMode && <DevToolsPanel />}

      {/* JSON Input Modal */}
      {showJsonInput && (
        <div className="json-modal-overlay" onClick={() => setShowJsonInput(false)}>
          <div className="json-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Import Workflow JSON</h3>
            <p className="muted small">Upload a JSON file or paste JSON below</p>

            {/* File upload button */}
            <button
              className="ghost full-width file-upload-btn"
              onClick={() => fileInputRef.current?.click()}
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
    </aside>
  )
}
