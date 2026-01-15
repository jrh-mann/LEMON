import { useCallback, useRef } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { generateNodeId } from '../utils/canvas'
import type { FlowNodeType } from '../types'

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
  const dragDataRef = useRef<BlockConfig | null>(null)

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
        <p className="eyebrow">DEBUG</p>
        <button
          className="ghost full-width"
          onClick={() => {
            // Sample flowchart with proper English labels (simulating what backend should return)
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
          Load Test Flowchart
        </button>
      </div>
    </aside>
  )
}
