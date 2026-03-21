import { useCallback, useRef, useState, useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { generateNodeId } from '../utils/canvas'
import type { FlowNodeType } from '../types'
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
  }
]

const DEFAULT_WIDTH = 200
const MIN_WIDTH = 0

export default function Palette() {
  const { addNode, flowchart, setFlowchart } = useWorkflowStore()
  const { openModal, devMode } = useUIStore()
  const dragDataRef = useRef<BlockConfig | null>(null)
  const [paletteMode, setPaletteMode] = useState<'build' | 'dev'>('build')

  // Resizable sidebar state
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)

  // Handle resize drag
  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      // Calculate new width based on mouse position from left edge of window
      const newWidth = e.clientX
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(newWidth, window.innerWidth * 0.4))
      setSidebarWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      // Snap to closed if very small
      setSidebarWidth(prev => prev < 40 ? 0 : prev)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ew-resize'

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [isResizing])

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

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
      const x = 600
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

  const isCollapsed = sidebarWidth === 0
  const activePaletteMode = devMode ? paletteMode : 'build'

  return (
    <aside
      ref={sidebarRef}
      className={`sidebar palette-sidebar ${isResizing ? 'resizing' : ''} ${isCollapsed ? 'sidebar-collapsed' : ''}`}
      style={{
        width: isCollapsed ? 0 : sidebarWidth,
        minWidth: isCollapsed ? 0 : sidebarWidth,
        overflowX: isCollapsed ? 'visible' : 'hidden', // Required for the handle to float
        paddingLeft: isCollapsed ? 0 : (sidebarWidth < 40 ? 0 : undefined),
        paddingRight: isCollapsed ? 0 : (sidebarWidth < 40 ? 0 : undefined),
      }}
    >
      <div
        className="sidebar-resize-handle palette-resize-handle"
        onMouseDown={handleResizeStart}
        title={isCollapsed ? "Drag to expand" : "Drag to resize"}
      >
        <div className="resize-grip"></div>
      </div>

      {!isCollapsed && (
        <>
          {/* Dev Mode Toggle */}
          {devMode && (
            <div className="sidebar-section">
              <div className="sidebar-toggle-group">
                <button
                  className={`sidebar-toggle-btn ${activePaletteMode === 'build' ? 'active' : ''}`}
                  onClick={() => setPaletteMode('build')}
                >
                  Build
                </button>
                <button
                  className={`sidebar-toggle-btn ${activePaletteMode === 'dev' ? 'active' : ''}`}
                  onClick={() => setPaletteMode('dev')}
                >
                  Dev Tools
                </button>
              </div>
            </div>
          )}

          {activePaletteMode === 'build' ? (
            <>
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
                <p className="eyebrow">EXAMPLES</p>
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
            </>
          ) : (
            <DevToolsPanel />
          )}

        </>
      )}
    </aside>
  )
}
