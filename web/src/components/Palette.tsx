import { useCallback, useRef } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { generateNodeId } from '../utils/canvas'
import type { FlowNodeType } from '../types'

interface BlockConfig {
  type: FlowNodeType
  label: string
  defaultLabel: string
}

const BLOCKS: BlockConfig[] = [
  { type: 'start', label: 'Start', defaultLabel: 'Input' },
  { type: 'decision', label: 'Decision', defaultLabel: 'Condition?' },
  { type: 'end', label: 'Output', defaultLabel: 'Result' },
  { type: 'subprocess', label: 'Subflow', defaultLabel: 'Workflow' },
]

export default function Palette() {
  const { addNode, flowchart } = useWorkflowStore()
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
              <div className={`block-icon ${block.type}-icon`}></div>
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
    </aside>
  )
}
