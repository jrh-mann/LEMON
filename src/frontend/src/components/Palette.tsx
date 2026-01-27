import { useCallback, useRef, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { generateNodeId } from '../utils/canvas'
import type { FlowNodeType, Flowchart } from '../types'

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
  const { addNode, flowchart, setFlowchart } = useWorkflowStore()
  const { openModal } = useUIStore()
  const dragDataRef = useRef<BlockConfig | null>(null)
  const [showJsonInput, setShowJsonInput] = useState(false)
  const [jsonText, setJsonText] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  // Handle JSON import
  const handleJsonImport = useCallback(() => {
    try {
      const parsed = JSON.parse(jsonText) as Flowchart

      // Validate basic structure
      if (!parsed.nodes || !Array.isArray(parsed.nodes)) {
        throw new Error('JSON must have a "nodes" array')
      }
      if (!parsed.edges || !Array.isArray(parsed.edges)) {
        parsed.edges = [] // Allow missing edges
      }

      // Ensure nodes have required fields
      const validatedNodes = parsed.nodes.map((n: any, i: number) => ({
        id: n.id || `node_${i}`,
        type: n.type || 'process',
        label: n.label || `Node ${i + 1}`,
        x: typeof n.x === 'number' ? n.x : 400,
        y: typeof n.y === 'number' ? n.y : 100 + i * 120,
        color: n.color || 'teal',
      }))

      setFlowchart({ nodes: validatedNodes, edges: parsed.edges })
      setShowJsonInput(false)
      setJsonText('')
      setJsonError(null)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : 'Invalid JSON')
    }
  }, [jsonText, setFlowchart])

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

      {/* JSON Input Modal */}
      {showJsonInput && (
        <div className="json-modal-overlay" onClick={() => setShowJsonInput(false)}>
          <div className="json-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Import Flowchart JSON</h3>
            <p className="muted small">Paste JSON with nodes and edges arrays</p>
            <textarea
              value={jsonText}
              onChange={(e) => {
                setJsonText(e.target.value)
                setJsonError(null)
              }}
              placeholder={`{
  "nodes": [
    {"id": "n1", "type": "start", "label": "Start", "x": 400, "y": 100},
    {"id": "n2", "type": "decision", "label": "Check?", "x": 400, "y": 220}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "label": ""}
  ]
}`}
              rows={12}
            />
            {jsonError && <p className="error-text">{jsonError}</p>}
            <div className="json-modal-actions">
              <button className="ghost" onClick={() => setShowJsonInput(false)}>Cancel</button>
              <button className="primary" onClick={handleJsonImport}>Import</button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
