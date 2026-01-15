import { useRef, useEffect, useCallback, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import {
  getNodeSize,
  getNodeColor,
  calculateEdgePath,
  calculateViewBox,
  getDecisionPath,
  generateNodeId,
} from '../utils/canvas'
import type { FlowNode, FlowNodeType } from '../types'

// Default labels for each node type
const DEFAULT_LABELS: Record<FlowNodeType, string> = {
  start: 'Input',
  end: 'Result',
  process: 'Process',
  decision: 'Condition?',
  subprocess: 'Workflow',
}

export default function Canvas() {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const {
    flowchart,
    selectedNodeId,
    connectMode,
    connectFromId,
    selectNode,
    moveNode,
    addNode,
    addEdge,
    startConnect,
    completeConnect,
    cancelConnect,
    deleteNode,
    undo,
    redo,
    pushHistory,
  } = useWorkflowStore()

  const { zoom, zoomIn, zoomOut, resetZoom, canvasTab, setCanvasTab } = useUIStore()
  const { pendingImage, pendingImageName, clearPendingImage } = useChatStore()

  // Auto-switch to image tab when image is uploaded
  useEffect(() => {
    if (pendingImage) {
      setCanvasTab('image')
    }
  }, [pendingImage, setCanvasTab])

  // Drag state
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number; nodeX: number; nodeY: number } | null>(null)
  const [dragNodeId, setDragNodeId] = useState<string | null>(null)

  // Drag-to-connect state
  const [dragConnection, setDragConnection] = useState<{
    fromNodeId: string
    fromDir: string
    startX: number
    startY: number
    currentX: number
    currentY: number
  } | null>(null)

  // Calculate viewBox
  const viewBox = calculateViewBox(flowchart.nodes)
  const viewBoxStr = `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`

  // Convert screen coords to SVG coords
  const screenToSVG = useCallback(
    (screenX: number, screenY: number): { x: number; y: number } => {
      const svg = svgRef.current
      if (!svg) return { x: screenX, y: screenY }

      const pt = svg.createSVGPoint()
      pt.x = screenX
      pt.y = screenY

      const ctm = svg.getScreenCTM()
      if (!ctm) return { x: screenX, y: screenY }

      const svgPt = pt.matrixTransform(ctm.inverse())
      return { x: svgPt.x, y: svgPt.y }
    },
    []
  )

  // Get port position relative to node center
  const getPortPosition = (dir: string, size: { w: number; h: number }) => {
    const halfW = size.w / 2
    const halfH = size.h / 2
    switch (dir) {
      case 'top': return { x: 0, y: -halfH }
      case 'bottom': return { x: 0, y: halfH }
      case 'left': return { x: -halfW, y: 0 }
      case 'right': return { x: halfW, y: 0 }
      default: return { x: 0, y: 0 }
    }
  }

  // Always show all 4 ports (unlimited connections)
  const getAvailablePorts = () => {
    return ['top', 'bottom', 'left', 'right']
  }

  // Handle port pointer down - start drag connection
  const handlePortPointerDown = useCallback(
    (e: React.PointerEvent, node: FlowNode, dir: string) => {
      e.stopPropagation()
      e.preventDefault()

      const svgCoords = screenToSVG(e.clientX, e.clientY)
      const size = getNodeSize(node.type)
      const portPos = getPortPosition(dir, size)
      const startX = node.x + portPos.x
      const startY = node.y + portPos.y

      setDragConnection({
        fromNodeId: node.id,
        fromDir: dir,
        startX,
        startY,
        currentX: svgCoords.x,
        currentY: svgCoords.y,
      })

      svgRef.current?.setPointerCapture(e.pointerId)
    },
    [screenToSVG]
  )

  // Handle pointer down on node
  const handleNodePointerDown = useCallback(
    (e: React.PointerEvent, node: FlowNode) => {
      e.stopPropagation()
      e.preventDefault()

      if (connectMode) {
        // Complete connection
        if (connectFromId && connectFromId !== node.id) {
          completeConnect(node.id)
        }
        return
      }

      // Start drag
      const svgCoords = screenToSVG(e.clientX, e.clientY)
      setDragNodeId(node.id)
      setDragStart({
        x: svgCoords.x,
        y: svgCoords.y,
        nodeX: node.x,
        nodeY: node.y,
      })
      setIsDragging(true)
      selectNode(node.id)

      // Capture pointer on SVG for reliable tracking
      svgRef.current?.setPointerCapture(e.pointerId)
    },
    [connectMode, connectFromId, completeConnect, screenToSVG, selectNode]
  )

  // Handle pointer move
  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      const svgCoords = screenToSVG(e.clientX, e.clientY)

      // Handle drag connection preview
      if (dragConnection) {
        setDragConnection({
          ...dragConnection,
          currentX: svgCoords.x,
          currentY: svgCoords.y,
        })
        return
      }

      // Handle node dragging
      if (!isDragging || !dragNodeId || !dragStart) return

      const dx = svgCoords.x - dragStart.x
      const dy = svgCoords.y - dragStart.y

      moveNode(dragNodeId, dragStart.nodeX + dx, dragStart.nodeY + dy)
    },
    [isDragging, dragNodeId, dragStart, screenToSVG, moveNode, dragConnection]
  )

  // Handle pointer up
  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      // Handle drag connection completion
      if (dragConnection) {
        const svgCoords = screenToSVG(e.clientX, e.clientY)

        // Find if we're over a node
        const targetNode = flowchart.nodes.find((node) => {
          if (node.id === dragConnection.fromNodeId) return false
          const size = getNodeSize(node.type)
          const halfW = size.w / 2
          const halfH = size.h / 2
          return (
            svgCoords.x >= node.x - halfW &&
            svgCoords.x <= node.x + halfW &&
            svgCoords.y >= node.y - halfH &&
            svgCoords.y <= node.y + halfH
          )
        })

        if (targetNode) {
          // Create edge
          addEdge(dragConnection.fromNodeId, targetNode.id, '')
          pushHistory()
        }

        setDragConnection(null)
        svgRef.current?.releasePointerCapture(e.pointerId)
        return
      }

      // Handle node drag end
      if (isDragging && dragNodeId) {
        pushHistory()
      }
      setIsDragging(false)
      setDragNodeId(null)
      setDragStart(null)
      // Release pointer capture from SVG
      svgRef.current?.releasePointerCapture(e.pointerId)
    },
    [isDragging, dragNodeId, pushHistory, dragConnection, flowchart.nodes, screenToSVG, addEdge]
  )

  // Handle drag over (allow drop)
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  // Handle drop from palette
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const nodeType = e.dataTransfer.getData('text/plain') as FlowNodeType
      if (!nodeType) return

      // Convert drop coordinates to SVG coordinates
      const svgCoords = screenToSVG(e.clientX, e.clientY)

      addNode({
        id: generateNodeId(),
        type: nodeType,
        label: DEFAULT_LABELS[nodeType] || 'Node',
        x: svgCoords.x,
        y: svgCoords.y,
        color: 'teal',
      })
    },
    [screenToSVG, addNode]
  )

  // Handle canvas click (deselect)
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === svgRef.current || (e.target as SVGElement).tagName === 'rect') {
        selectNode(null)
        if (connectMode) {
          cancelConnect()
        }
      }
    },
    [selectNode, connectMode, cancelConnect]
  )

  // Handle double-click to start connection
  const handleNodeDoubleClick = useCallback(
    (e: React.MouseEvent, node: FlowNode) => {
      e.stopPropagation()
      startConnect(node.id)
    },
    [startConnect]
  )

  // Handle context menu
  const handleNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: FlowNode) => {
      e.preventDefault()
      selectNode(node.id)
      // Could show context menu here
    },
    [selectNode]
  )

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Delete selected node
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeId) {
        deleteNode(selectedNodeId)
      }

      // Undo/Redo
      if (e.key === 'z' && (e.metaKey || e.ctrlKey)) {
        if (e.shiftKey) {
          redo()
        } else {
          undo()
        }
      }

      // Cancel connect mode
      if (e.key === 'Escape' && connectMode) {
        cancelConnect()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNodeId, deleteNode, undo, redo, connectMode, cancelConnect])

  // Render node
  const renderNode = (node: FlowNode) => {
    const size = getNodeSize(node.type)
    const color = getNodeColor(node.color)
    const isSelected = node.id === selectedNodeId
    const isConnectSource = node.id === connectFromId

    const halfW = size.w / 2
    const halfH = size.h / 2

    return (
      <g
        key={node.id}
        className={`flow-node ${node.type} ${isSelected ? 'selected' : ''} ${isConnectSource ? 'connect-source' : ''}`}
        transform={`translate(${node.x}, ${node.y})`}
        onPointerDown={(e) => handleNodePointerDown(e, node)}
        onDoubleClick={(e) => handleNodeDoubleClick(e, node)}
        onContextMenu={(e) => handleNodeContextMenu(e, node)}
        style={{ cursor: isDragging && dragNodeId === node.id ? 'grabbing' : 'grab' }}
      >
        {/* Invisible hit area for better click/drag detection */}
        <rect
          x={-halfW}
          y={-halfH}
          width={size.w}
          height={size.h}
          fill="transparent"
          stroke="none"
        />

        {/* Node shape */}
        {node.type === 'decision' ? (
          <path
            d={getDecisionPath(0, 0, size.w, size.h)}
            fill="var(--paper)"
            stroke={isSelected ? color : 'var(--edge)'}
            strokeWidth={isSelected ? 2 : 1}
            style={{ pointerEvents: 'none' }}
          />
        ) : (
          <rect
            x={-halfW}
            y={-halfH}
            width={size.w}
            height={size.h}
            rx={node.type === 'start' || node.type === 'end' ? 32 : 8}
            fill="var(--paper)"
            stroke={isSelected ? color : 'var(--edge)'}
            strokeWidth={isSelected ? 2 : 1}
          />
        )}

        {/* Subprocess double border */}
        {node.type === 'subprocess' && (
          <rect
            x={-halfW + 8}
            y={-halfH + 8}
            width={size.w - 16}
            height={size.h - 16}
            rx={4}
            fill="none"
            stroke="var(--edge)"
            strokeWidth={1}
          />
        )}

        {/* Node label */}
        <text
          x={0}
          y={4}
          textAnchor="middle"
          fontSize="13"
          fill="var(--ink)"
          style={{ pointerEvents: 'none', userSelect: 'none' }}
        >
          {truncateLabel(node.label, node.type === 'decision' ? 20 : 25)}
        </text>

        {/* Color indicator */}
        <circle cx={halfW - 12} cy={-halfH + 12} r={5} fill={color} />

        {/* Selection ring */}
        {isSelected && (
          <rect
            x={-halfW - 4}
            y={-halfH - 4}
            width={size.w + 8}
            height={size.h + 8}
            rx={node.type === 'start' || node.type === 'end' ? 36 : 12}
            fill="none"
            stroke={color}
            strokeWidth={2}
            strokeDasharray="4 2"
            opacity={0.5}
          />
        )}

        {/* Connection ports - appear on hover */}
        {getAvailablePorts().map((dir) => {
          const pos = getPortPosition(dir, size)
          return (
            <circle
              key={dir}
              className="connection-port"
              cx={pos.x}
              cy={pos.y}
              r={6}
              fill="var(--paper)"
              stroke="var(--teal)"
              strokeWidth={2}
              onPointerDown={(e) => handlePortPointerDown(e, node, dir)}
              style={{ cursor: 'crosshair' }}
            />
          )
        })}
      </g>
    )
  }

  // Render edge
  const renderEdge = (edge: { from: string; to: string; label: string }) => {
    const fromNode = flowchart.nodes.find((n) => n.id === edge.from)
    const toNode = flowchart.nodes.find((n) => n.id === edge.to)

    if (!fromNode || !toNode) return null

    const path = calculateEdgePath(fromNode, toNode)

    return (
      <g key={`${edge.from}-${edge.to}`} className="flow-edge">
        <path
          d={path}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1.5}
          markerEnd="url(#arrowhead)"
        />
        {edge.label && (
          <text
            x={(fromNode.x + toNode.x) / 2}
            y={(fromNode.y + toNode.y) / 2 - 8}
            textAnchor="middle"
            fontSize="11"
            fill="var(--muted)"
          >
            {edge.label}
          </text>
        )}
      </g>
    )
  }

  // Truncate label helper
  function truncateLabel(label: string, maxLen: number): string {
    if (label.length <= maxLen) return label
    return label.slice(0, maxLen - 1) + '…'
  }

  const isEmpty = flowchart.nodes.length === 0

  return (
    <div className="canvas-area">
      {/* Workspace tabs */}
      <div className="workspace-tabs" id="workspaceTabs">
        <button
          className={`workspace-tab ${canvasTab === 'workflow' ? 'active' : ''}`}
          onClick={() => setCanvasTab('workflow')}
        >
          Workflow
        </button>
        {pendingImage && (
          <button
            className={`workspace-tab ${canvasTab === 'image' ? 'active' : ''}`}
            onClick={() => setCanvasTab('image')}
          >
            Source Image
          </button>
        )}
      </div>

      {/* Image preview tab */}
      {canvasTab === 'image' && pendingImage && (
        <div className="image-preview-container">
          <div className="image-preview-header">
            <span className="image-name">{pendingImageName || 'Uploaded image'}</span>
            <button
              className="clear-image-btn"
              onClick={() => {
                clearPendingImage()
                setCanvasTab('workflow')
              }}
              title="Remove image"
            >
              ×
            </button>
          </div>
          <div className="image-preview-content">
            <img src={pendingImage} alt="Uploaded workflow" />
          </div>
          <div className="image-preview-hint">
            Ask the orchestrator to analyse this image in the chat below
          </div>
        </div>
      )}

      {/* Workflow canvas tab */}
      <div
        className="canvas-container"
        id="canvasContainer"
        ref={containerRef}
        style={{ display: canvasTab === 'workflow' ? 'block' : 'none' }}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <svg
          ref={svgRef}
          id="flowchartCanvas"
          viewBox={viewBoxStr}
          onClick={handleCanvasClick}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          style={{ transform: `scale(${zoom})`, transformOrigin: 'center' }}
        >
          <defs>
            <marker
              id="arrowhead"
              markerWidth="10"
              markerHeight="7"
              refX="10"
              refY="3.5"
              orient="auto"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill="var(--ink)" />
            </marker>
            <marker
              id="arrowhead-preview"
              markerWidth="10"
              markerHeight="7"
              refX="10"
              refY="3.5"
              orient="auto"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill="var(--teal)" />
            </marker>
            <pattern
              id="grid"
              width="40"
              height="40"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 40 0 L 0 0 0 40"
                fill="none"
                stroke="var(--edge)"
                strokeWidth="0.5"
                opacity="0.5"
              />
            </pattern>
          </defs>

          {/* Grid background */}
          <rect width="100%" height="100%" fill="url(#grid)" />

          {/* Edges layer */}
          <g id="edgeLayer">
            {flowchart.edges.map(renderEdge)}
          </g>

          {/* Nodes layer */}
          <g id="nodeLayer">
            {flowchart.nodes.map(renderNode)}
          </g>

          {/* Preview edge during drag connection */}
          {dragConnection && (
            <path
              d={`M ${dragConnection.startX} ${dragConnection.startY} L ${dragConnection.currentX} ${dragConnection.currentY}`}
              fill="none"
              stroke="var(--teal)"
              strokeWidth={2}
              strokeDasharray="5,5"
              markerEnd="url(#arrowhead-preview)"
              style={{ pointerEvents: 'none' }}
            />
          )}
        </svg>

        {/* Empty state overlay */}
        {isEmpty && (
          <div className="canvas-empty" id="canvasEmpty">
            <div className="empty-content">
              <div className="empty-icon">
                <svg
                  width="64"
                  height="64"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </div>
              <h2>Start building</h2>
              <p>Drag blocks from the left, or describe your workflow below</p>
            </div>
          </div>
        )}

        {/* Connect mode indicator */}
        {connectMode && (
          <div className="connect-mode-indicator">
            Click another node to connect, or press Escape to cancel
          </div>
        )}

        {/* Zoom controls */}
        <div className="zoom-controls">
          <button className="zoom-btn" onClick={zoomIn} title="Zoom in (+)">
            +
          </button>
          <button className="zoom-btn" onClick={resetZoom} title="Reset zoom (0)">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" />
            </svg>
          </button>
          <button className="zoom-btn" onClick={zoomOut} title="Zoom out (-)">
            -
          </button>
        </div>

        {/* Meta controls */}
        <div className="meta-controls">
          <button className="meta-btn" title="Undo (Cmd+Z)" onClick={undo}>
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M3 7v6h6" />
              <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
            </svg>
          </button>
          <button className="meta-btn" title="Redo (Cmd+Shift+Z)" onClick={redo}>
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 7v6h-6" />
              <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
