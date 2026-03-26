import { useRef, useEffect, useCallback, useState, useMemo } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import {
  getNodeSize,
  getNodeColor,
  calculateEdgePath,
  calculateViewBox,
  getDecisionPath,
  generateNodeId,
  resolveDecisionEdgeLabel,
  resolveCollision,
} from '../utils/canvas'
import { getNodeFillColor, getNodeStrokeColor, DEFAULT_LABELS } from '../utils/canvas/nodeStyles'
import { wrapText } from '../utils/canvas/textWrap'
import { patchWorkflow } from '../api/workflows'
import { beautifyNodes } from '../utils/beautifyNodes'
import { useCanvasKeyboard } from '../hooks/useCanvasKeyboard'
import { useWheelZoom } from '../hooks/useWheelZoom'
import type { FlowNode, FlowNodeType } from '../types'

/** Convert a base64 data URL to a blob URL for reliable iframe rendering. */
function PdfPreview({ file }: { file: { id: string; name: string; dataUrl: string } }) {
  const blobUrl = useMemo(() => {
    try {
      const [header, base64] = file.dataUrl.split(',')
      const mime = header.match(/:(.*?);/)?.[1] || 'application/pdf'
      const bytes = atob(base64)
      const arr = new Uint8Array(bytes.length)
      for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
      const blob = new Blob([arr], { type: mime })
      return URL.createObjectURL(blob)
    } catch {
      return file.dataUrl // fallback to data URL
    }
  }, [file.dataUrl])

  useEffect(() => {
    return () => { if (blobUrl.startsWith('blob:')) URL.revokeObjectURL(blobUrl) }
  }, [blobUrl])

  return (
    <iframe
      className="pdf-preview"
      src={blobUrl}
      title={file.name}
    />
  )
}

export default function Canvas({ readOnly = false }: { readOnly?: boolean }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const focusCanvasContainer = useCallback(() => {
    containerRef.current?.focus()
  }, [])

  const {
    flowchart,
    setFlowchart,
    selectedNodeIds,
    selectedEdge,
    connectMode,
    connectFromId,
    selectNode,
    selectNodes,
    selectEdge,
    clearSelection,
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
    pendingFiles,
    clearPendingFiles,
    execution,  // Execution state for visual highlighting
    highlightedNodeId,  // Node pulsing from highlight_node tool
    currentAnalysis,
    currentWorkflow,
  } = useWorkflowStore()

  const {
    zoom,
    setZoom,
    zoomIn,
    zoomOut,
    resetZoom,
    // setPan removed
    canvasTab,
    setCanvasTab,
    canvasMode,
    toggleCanvasMode,
    setCanvasMode,
    trackExecution,     // Import tracking state
    setTrackExecution,  // Import tracking setter
    workspaceRevealed,
  } = useUIStore()

  // Zoom limits for wheel zoom - matches uiStore constants


  // Auto-switch to image tab when files are uploaded
  useEffect(() => {
    if (pendingFiles.length > 0) {
      setCanvasTab('image')
    }
  }, [pendingFiles, setCanvasTab])


  // Drag state
  // Track which file is shown in the multi-file preview (prev/next navigation)
  const [selectedFileIndex, setSelectedFileIndex] = useState(0)

  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number; nodeX: number; nodeY: number } | null>(null)
  const [dragNodeId, setDragNodeId] = useState<string | null>(null)

  // Pan state (for scrolling/dragging the canvas)
  const [isPanning, setIsPanning] = useState(false)
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 })
  const [panStart, setPanStart] = useState<{ x: number; y: number; panX: number; panY: number } | null>(null)

  // Drag-to-connect state
  const [dragConnection, setDragConnection] = useState<{
    fromNodeId: string
    fromDir: string
    startX: number
    startY: number
    currentX: number
    currentY: number
  } | null>(null)

  // Box selection state
  const [selectionBox, setSelectionBox] = useState<{
    startX: number
    startY: number
    currentX: number
    currentY: number
  } | null>(null)

  // Track initial positions of selected nodes for group dragging
  const [dragStartPositions, setDragStartPositions] = useState<Map<string, { x: number; y: number }> | null>(null)

  // Reset pan offset when switching workflows (SPA navigation).
  // Without this, the old workflow's pan persists and the new workflow's
  // nodes can be rendered outside the visible viewBox.
  const workflowId = currentWorkflow?.id
  useEffect(() => {
    setPanOffset({ x: 0, y: 0 })
  }, [workflowId])

  // Track last click for double-click detection on canvas
  const lastCanvasClickRef = useRef<{ time: number; x: number; y: number } | null>(null)

  // Calculate viewBox with pan offset and zoom
  // Zoom is applied via viewBox (not CSS transform) to maintain vector crispness at any zoom level
  const viewBox = calculateViewBox(flowchart.nodes)
  const viewBoxStr = `${viewBox.x - panOffset.x} ${viewBox.y - panOffset.y} ${viewBox.width / zoom} ${viewBox.height / zoom}`

  // Auto-track executing node
  useEffect(() => {
    // Only track if enabled and we have an executing node
    if (trackExecution && execution.isExecuting && execution.executingNodeId) {
      const node = flowchart.nodes.find(n => n.id === execution.executingNodeId)
      if (node) {
        // Center on the node
        // Target pan offset = viewBoxX + (viewBoxWidth / 2) - nodeX
        // Because nodeX = viewBoxX + (viewBoxWidth / 2) - panOffset

        // Use current viewbox (which is calculated from nodes)
        // Note: viewBox.width is width relative to SVG user usage units.
        // effective view width in user units = viewBox.width / zoom

        const effectiveWidth = viewBox.width / zoom
        const effectiveHeight = viewBox.height / zoom

        const targetX = viewBox.x + (effectiveWidth / 2) - node.x
        const targetY = viewBox.y + (effectiveHeight / 2) - node.y

        // Smooth transition could be handled by CSS if we applied pan via CSS, 
        // but here we use state. For now momentary jump is acceptable for "tracking".
        setPanOffset({ x: targetX, y: targetY })
      }
    }
  }, [trackExecution, execution.isExecuting, execution.executingNodeId, flowchart.nodes, zoom, viewBox.x, viewBox.y, viewBox.width, viewBox.height])

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

      if (readOnly) return

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
      focusCanvasContainer()

      if (connectMode) {
        // Complete connection
        if (connectFromId && connectFromId !== node.id) {
          completeConnect(node.id)
        }
        return
      }

      const svgCoords = screenToSVG(e.clientX, e.clientY)
      const isAlreadySelected = selectedNodeIds.includes(node.id)

      // Handle selection
      if (e.shiftKey) {
        // Shift-click: toggle in selection
        if (isAlreadySelected) {
          selectNodes(selectedNodeIds.filter(id => id !== node.id))
        } else {
          selectNodes([...selectedNodeIds, node.id])
        }
      } else if (!isAlreadySelected) {
        // Click on unselected node: select only this node
        selectNode(node.id)
      }
      // If clicking on already selected node without shift, keep current selection for group drag

      // Start drag - use all selected nodes if this node is selected
      const nodesToDrag = isAlreadySelected || e.shiftKey ? selectedNodeIds : [node.id]
      const positions = new Map<string, { x: number; y: number }>()
      flowchart.nodes.forEach(n => {
        if (nodesToDrag.includes(n.id) || n.id === node.id) {
          positions.set(n.id, { x: n.x, y: n.y })
        }
      })

      setDragNodeId(node.id)
      setDragStart({
        x: svgCoords.x,
        y: svgCoords.y,
        nodeX: node.x,
        nodeY: node.y,
      })
      setDragStartPositions(positions)
      setIsDragging(true)

      // Capture pointer on SVG for reliable tracking
      svgRef.current?.setPointerCapture(e.pointerId)
    },
    [connectMode, connectFromId, completeConnect, screenToSVG, selectNode, selectNodes, selectedNodeIds, flowchart.nodes, readOnly, focusCanvasContainer]
  )

  // Handle pointer move
  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      // Handle panning
      if (isPanning && panStart) {
        const dx = e.clientX - panStart.x
        const dy = e.clientY - panStart.y
        // Scale the pan based on zoom level
        const scale = viewBox.width / (containerRef.current?.clientWidth || 1)
        setPanOffset({
          x: panStart.panX + dx * scale,
          y: panStart.panY + dy * scale
        })
        return
      }

      const svgCoords = screenToSVG(e.clientX, e.clientY)

      // Handle box selection
      if (selectionBox) {
        setSelectionBox({
          ...selectionBox,
          currentX: svgCoords.x,
          currentY: svgCoords.y,
        })
        return
      }

      // Handle drag connection preview
      if (dragConnection) {
        setDragConnection({
          ...dragConnection,
          currentX: svgCoords.x,
          currentY: svgCoords.y,
        })
        return
      }

      // Handle node dragging (single or group)
      if (!isDragging || !dragNodeId || !dragStart) return

      const dx = svgCoords.x - dragStart.x
      const dy = svgCoords.y - dragStart.y

      // If we have multiple selected nodes and drag positions, move them all
      if (dragStartPositions && dragStartPositions.size > 1 && selectedNodeIds.length > 1) {
        // Move all selected nodes by delta from their start positions
        selectedNodeIds.forEach(nodeId => {
          const startPos = dragStartPositions.get(nodeId)
          if (startPos) {
            moveNode(nodeId, startPos.x + dx, startPos.y + dy)
          }
        })
      } else {
        // Single node drag with collision detection
        const newPos = resolveCollision(flowchart.nodes, dragNodeId, dragStart.nodeX + dx, dragStart.nodeY + dy)
        moveNode(dragNodeId, newPos.x, newPos.y)
      }
    },
    [isDragging, dragNodeId, dragStart, screenToSVG, moveNode, dragConnection, isPanning, panStart, viewBox.width, selectionBox, dragStartPositions, selectedNodeIds, flowchart.nodes]
  )

  // Handle pointer up
  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      // Handle panning end
      if (isPanning) {
        setIsPanning(false)
        setPanStart(null)
        svgRef.current?.releasePointerCapture(e.pointerId)
        return
      }

      // Handle box selection completion
      if (selectionBox) {
        const boxWidth = Math.abs(selectionBox.currentX - selectionBox.startX)
        const boxHeight = Math.abs(selectionBox.currentY - selectionBox.startY)
        const isJustClick = boxWidth < 5 && boxHeight < 5

        if (isJustClick) {
          // Just a click on empty space - clear selection (unless shift held)
          if (!e.shiftKey) {
            clearSelection()
          }
        } else {
          // Actual drag - find nodes in box
          const minX = Math.min(selectionBox.startX, selectionBox.currentX)
          const maxX = Math.max(selectionBox.startX, selectionBox.currentX)
          const minY = Math.min(selectionBox.startY, selectionBox.currentY)
          const maxY = Math.max(selectionBox.startY, selectionBox.currentY)

          // Find all nodes within the selection box
          const nodesInBox = flowchart.nodes.filter(node => {
            const size = getNodeSize(node.type)
            const halfW = size.w / 2
            const halfH = size.h / 2
            // Check if node intersects with selection box
            return (
              node.x + halfW >= minX &&
              node.x - halfW <= maxX &&
              node.y + halfH >= minY &&
              node.y - halfH <= maxY
            )
          })

          if (nodesInBox.length > 0) {
            // If shift was held, add to existing selection
            if (e.shiftKey) {
              const newIds = [...new Set([...selectedNodeIds, ...nodesInBox.map(n => n.id)])]
              selectNodes(newIds)
            } else {
              selectNodes(nodesInBox.map(n => n.id))
            }
          } else if (!e.shiftKey) {
            // Dragged box but no nodes - clear selection
            clearSelection()
          }
        }

        setSelectionBox(null)
        svgRef.current?.releasePointerCapture(e.pointerId)
        return
      }

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

        if (targetNode && !readOnly) {
          addEdge({ from: dragConnection.fromNodeId, to: targetNode.id, label: '' })
          pushHistory()
        }

        setDragConnection(null)
        svgRef.current?.releasePointerCapture(e.pointerId)
        return
      }

      // Handle node drag end
      if (isDragging && dragNodeId && !readOnly) {
        pushHistory()
      }
      setIsDragging(false)
      setDragNodeId(null)
      setDragStart(null)
      setDragStartPositions(null)
      // Release pointer capture from SVG
      svgRef.current?.releasePointerCapture(e.pointerId)
    },
    [isDragging, dragNodeId, pushHistory, dragConnection, flowchart.nodes, screenToSVG, addEdge, isPanning, selectionBox, selectedNodeIds, selectNodes, clearSelection, readOnly]
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
      if (readOnly) return
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
    [screenToSVG, addNode, readOnly]
  )

  // Handle canvas pointer down (start box selection or panning based on mode)
  const handleCanvasPointerDown = useCallback(
    (e: React.PointerEvent) => {
      // Only handle if clicking on background (svg, grid rect, or pattern elements)
      const target = e.target as SVGElement
      const isBackgroundClick =
        target === svgRef.current ||
        (target.tagName === 'rect' && !target.closest('.flow-node')) ||
        target.tagName === 'path' && target.closest('pattern')

      if (isBackgroundClick) {
        e.preventDefault()
        focusCanvasContainer()

        if (readOnly) {
          const now = Date.now()
          const lastClick = lastCanvasClickRef.current
          const isDoubleClick = lastClick &&
            (now - lastClick.time < 400) &&
            Math.abs(e.clientX - lastClick.x) < 20 &&
            Math.abs(e.clientY - lastClick.y) < 20
          lastCanvasClickRef.current = { time: now, x: e.clientX, y: e.clientY }
          if (canvasMode === 'pan' || isDoubleClick || e.button === 1) {
            setIsPanning(true)
            setPanStart({ x: e.clientX, y: e.clientY, panX: panOffset.x, panY: panOffset.y })
            svgRef.current?.setPointerCapture(e.pointerId)
          }
          return
        }

        const now = Date.now()
        const lastClick = lastCanvasClickRef.current

        // Check for double-click: within 400ms and 20px of last click
        const isDoubleClick = lastClick &&
          (now - lastClick.time < 400) &&
          Math.abs(e.clientX - lastClick.x) < 20 &&
          Math.abs(e.clientY - lastClick.y) < 20

        // Update last click tracking
        lastCanvasClickRef.current = { time: now, x: e.clientX, y: e.clientY }

        // Pan mode, double-click, or middle mouse = panning
        if (canvasMode === 'pan' || isDoubleClick || e.button === 1) {
          setIsPanning(true)
          setPanStart({
            x: e.clientX,
            y: e.clientY,
            panX: panOffset.x,
            panY: panOffset.y
          })
          // Clear any selection box that may have started
          setSelectionBox(null)
        } else {
          // Select mode: single click = box selection
          const svgCoords = screenToSVG(e.clientX, e.clientY)
          setSelectionBox({
            startX: svgCoords.x,
            startY: svgCoords.y,
            currentX: svgCoords.x,
            currentY: svgCoords.y
          })
          // Clear existing selection unless shift is held
          if (!e.shiftKey) {
            clearSelection()
          }
        }
        svgRef.current?.setPointerCapture(e.pointerId)
      }
    },
    [panOffset, screenToSVG, clearSelection, canvasMode, readOnly, focusCanvasContainer]
  )

  // Handle canvas click (just cancel connect mode, selection handled by pointer events)
  const handleCanvasClick = useCallback(
    () => {
      if (connectMode) {
        if (readOnly) return
        cancelConnect()
      }
    },
    [connectMode, cancelConnect, readOnly]
  )

  // Handle double-click to start connection
  const handleNodeDoubleClick = useCallback(
    (e: React.MouseEvent, node: FlowNode) => {
      e.stopPropagation()
      if (readOnly) return
      startConnect(node.id)
    },
    [startConnect, readOnly]
  )



  // Keyboard shortcuts (delete, undo/redo, escape, mode switch)
  useCanvasKeyboard({
    selectedNodeIds: readOnly ? [] : selectedNodeIds,
    deleteNode: readOnly ? (() => {}) : deleteNode,
    undo: readOnly ? (() => {}) : undo,
    redo: readOnly ? (() => {}) : redo,
    connectMode: readOnly ? false : connectMode,
    cancelConnect: readOnly ? (() => {}) : cancelConnect,
    clearSelection: readOnly ? (() => {}) : clearSelection,
    setCanvasMode,
  })

  // Mouse wheel zoom (centred on cursor, non-passive listener)
  useWheelZoom(svgRef, containerRef, zoom, panOffset, setZoom, setPanOffset, screenToSVG)

  // Render node
  const renderNode = (node: FlowNode) => {
    const size = getNodeSize(node.type)
    const color = getNodeColor(node.color)
    const isSelected = selectedNodeIds.includes(node.id)
    const isConnectSource = node.id === connectFromId

    // Execution state classes
    const isExecuting = execution.executingNodeId === node.id
    const isExecuted = execution.executedNodeIds.includes(node.id)

    const halfW = size.w / 2
    const halfH = size.h / 2

    // Build class name with execution state
    const classNames = [
      'flow-node',
      node.type,
      isSelected ? 'selected' : '',
      isConnectSource ? 'connect-source' : '',
      isExecuting ? 'executing' : '',
      isExecuted && !isExecuting ? 'executed' : '',  // Don't show executed while currently executing
      highlightedNodeId === node.id ? 'highlighted' : '',
    ].filter(Boolean).join(' ')

    return (
      <g
        key={node.id}
        className={classNames}
        transform={`translate(${node.x}, ${node.y})`}
        onPointerDown={(e) => handleNodePointerDown(e, node)}
        onDoubleClick={(e) => handleNodeDoubleClick(e, node)}
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
            fill={getNodeFillColor(node.type)}
            stroke={isSelected ? color : getNodeStrokeColor(node.type)}
            strokeWidth={isSelected ? 2 : 1.5}
            style={{ pointerEvents: 'none' }}
          />
        ) : (
          <rect
            x={-halfW}
            y={-halfH}
            width={size.w}
            height={size.h}
            rx={node.type === 'start' || node.type === 'end' ? 32 : 8}
            fill={getNodeFillColor(node.type)}
            stroke={isSelected ? color : getNodeStrokeColor(node.type)}
            strokeWidth={node.type === 'start' ? 3 : isSelected ? 2 : 1.5}
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
            stroke="var(--rose)"
            strokeWidth={1}
          />
        )}

        {/* Node label with word wrapping */}
        <text
          x={0}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize="13"
          fill="var(--ink)"
          style={{ pointerEvents: 'none', userSelect: 'none' }}
        >
          {wrapText(node.label, node.type === 'decision' ? 14 : 18).map((line, i, arr) => (
            <tspan
              key={i}
              x={0}
              dy={i === 0 ? `${-((arr.length - 1) * 7)}px` : '14px'}
            >
              {line}
            </tspan>
          ))}
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

    // Calculate label position along the path (closer to source for decision outputs)
    let labelX = (fromNode.x + toNode.x) / 2
    let labelY = (fromNode.y + toNode.y) / 2 - 8

    // For decision node outputs, position label closer to the source
    if (fromNode.type === 'decision' && edge.label) {
      labelX = fromNode.x + (toNode.x - fromNode.x) * 0.3
      labelY = fromNode.y + (toNode.y - fromNode.y) * 0.3 - 8
    }

    // Check if this edge is part of the execution path
    // An edge is "executed" if both its source and target have been executed (or target is currently executing)
    const fromExecuted = execution.executedNodeIds.includes(edge.from) || execution.executingNodeId === edge.from

    // Edge is "executing" if the source is executed/executing and target is currently executing
    const isEdgeExecuting = fromExecuted && execution.executingNodeId === edge.to

    // Edge is "executed" if both ends have been executed (not just executing)
    const isEdgeExecuted = execution.executedNodeIds.includes(edge.from) && execution.executedNodeIds.includes(edge.to)

    // Check if this edge is selected
    const isSelected = selectedEdge?.from === edge.from && selectedEdge?.to === edge.to

    // Check if this edge is from a decision node (for UI purposes)
    const isDecisionEdge = fromNode.type === 'decision'

    const edgeClassNames = [
      'flow-edge',
      isEdgeExecuting ? 'executing' : '',
      isEdgeExecuted && !isEdgeExecuting ? 'executed' : '',
      isSelected ? 'selected' : '',
    ].filter(Boolean).join(' ')

    // Click handler for edge selection
    const handleEdgeClick = (e: React.MouseEvent) => {
      e.stopPropagation()
      selectEdge({ from: edge.from, to: edge.to })
    }

    return (
      <g key={`${edge.from}-${edge.to}`} className={edgeClassNames} onClick={handleEdgeClick} style={{ cursor: 'pointer' }}>
        {/* Invisible wider path for easier clicking - increased from 20 to 40 */}
        <path
          d={path}
          fill="none"
          stroke="transparent"
          strokeWidth={40}
          style={{ cursor: 'pointer' }}
        />
        {/* Visible edge line - increased stroke width for better visibility */}
        <path
          className="edge-visible"
          d={path}
          fill="none"
          stroke={isSelected ? 'var(--accent)' : 'var(--ink)'}
          strokeWidth={isSelected ? 6 : 4}
          markerEnd="url(#arrowhead)"
        />
        {/* Show label for decision edges, or any edge with a label */}
        {(edge.label || isDecisionEdge) && (() => {
          // Resolve "true"/"false" into human-readable condition labels
          const variables = currentAnalysis?.variables ?? []
          const resolved = isDecisionEdge
            ? resolveDecisionEdgeLabel(fromNode, edge.label, variables)
            : null
          const labelText = resolved ?? (edge.label || (isDecisionEdge ? '?' : ''))
          // Approximate text width for background rect (8px per char at font-size 14)
          const textW = labelText.length * 8 + 10
          const textH = 20
          return (
            <>
              <rect
                x={labelX - textW / 2}
                y={labelY - textH / 2}
                width={textW}
                height={textH}
                rx={4}
                fill="var(--paper)"
              />
              <text
                x={labelX}
                y={labelY}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize="14"
                fill={isSelected ? 'var(--accent)' : 'var(--ink)'}
                fontWeight={600}
              >
                {labelText}
              </text>
            </>
          )
        })()}
      </g>
    )
  }

  // Beautify/auto-layout: reposition nodes without changing graph topology.
  // Uses the shared beautifyNodes utility which supports DAGs (nodes with
  // multiple parents). No _dup nodes, no new edges — only x,y updates.
  const beautifyFlowchart = useCallback(() => {
    if (flowchart.nodes.length === 0 || readOnly) return

    const result = beautifyNodes(flowchart.nodes, flowchart.edges)
    setFlowchart(result)
    pushHistory()

    // Sync updated positions to the backend
    const workflowId = useWorkflowStore.getState().currentWorkflow?.id
    if (workflowId) {
      patchWorkflow(workflowId, { nodes: result.nodes, edges: result.edges }).catch(() => {})
    }
  }, [flowchart, setFlowchart, pushHistory, readOnly])

  return (
    <div className="canvas-area">
      {/* Toolbar / Tabs area - Only show Source Files tab if there are files uploaded */}
      {!readOnly && workspaceRevealed && pendingFiles.length > 0 && (
        <div className="workspace-tabs">
          <button
            className={`workspace-tab ${canvasTab === 'image' ? 'active' : ''}`}
            onClick={() => setCanvasTab('image')}
          >
            Source {pendingFiles.length === 1 ? 'File' : 'Files'}
          </button>
          <button
            className={`workspace-tab ${canvasTab === 'workflow' ? 'active' : ''}`}
            onClick={() => setCanvasTab('workflow')}
          >
            Workflow
          </button>
        </div>
      )}

      {/* File preview tab — shows selected file with prev/next navigation */}
      {!readOnly && canvasTab === 'image' && pendingFiles.length > 0 && (() => {
        const idx = Math.min(selectedFileIndex, pendingFiles.length - 1)
        const currentFile = pendingFiles[idx]
        const showNav = pendingFiles.length > 1
        return (
          <div className="image-preview-container">
            <div className="image-preview-header">
              {showNav && (
                <button
                  className="file-nav-btn"
                  disabled={idx === 0}
                  onClick={() => setSelectedFileIndex(idx - 1)}
                  title="Previous file"
                >
                  &lsaquo;
                </button>
              )}
              <span className="image-name">
                {currentFile.name}
                {showNav && ` (${idx + 1}/${pendingFiles.length})`}
              </span>
              {showNav && (
                <button
                  className="file-nav-btn"
                  disabled={idx === pendingFiles.length - 1}
                  onClick={() => setSelectedFileIndex(idx + 1)}
                  title="Next file"
                >
                  &rsaquo;
                </button>
              )}
              <button
                className="clear-image-btn"
                onClick={() => {
                  clearPendingFiles()
                  setSelectedFileIndex(0)
                  setCanvasTab('workflow')
                }}
                title="Remove all files"
              >
                &times;
              </button>
            </div>
            {currentFile.type === 'image' ? (
              <div className="image-preview-content">
                <img
                  key={currentFile.id}
                  src={currentFile.dataUrl}
                  alt={currentFile.name}
                />
              </div>
            ) : (
              <PdfPreview key={currentFile.id} file={currentFile} />
            )}
          </div>
        )
      })()}

      {/* Workflow canvas tab */}
      <div
        className="canvas-container"
        id="canvasContainer"
        ref={containerRef}
        tabIndex={readOnly ? -1 : 0}
        style={{ display: canvasTab === 'workflow' ? 'block' : 'none' }}
        onDragOver={readOnly ? undefined : handleDragOver}
        onDrop={readOnly ? undefined : handleDrop}
      >
        <svg
          ref={svgRef}
          id="flowchartCanvas"
          viewBox={viewBoxStr}
          onClick={handleCanvasClick}
          onPointerDown={handleCanvasPointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          style={{
            cursor: isPanning ? 'grabbing' : (canvasMode === 'pan' ? 'grab' : 'default')
          }}
        >
          <defs>
            <marker
              id="arrowhead"
              markerUnits="userSpaceOnUse"
              markerWidth="20"
              markerHeight="14"
              refX="18"
              refY="7"
              orient="auto"
            >
              <polygon points="0 0, 20 7, 0 14" fill="var(--ink)" />
            </marker>
            <marker
              id="arrowhead-preview"
              markerUnits="userSpaceOnUse"
              markerWidth="20"
              markerHeight="14"
              refX="18"
              refY="7"
              orient="auto"
            >
              <polygon points="0 0, 20 7, 0 14" fill="var(--teal)" />
            </marker>
          </defs>

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
              className="edge-visible"
              d={`M ${dragConnection.startX} ${dragConnection.startY} L ${dragConnection.currentX} ${dragConnection.currentY}`}
              fill="none"
              stroke="var(--teal)"
              strokeWidth={4}
              strokeDasharray="8,8"
              markerEnd="url(#arrowhead-preview)"
              style={{ pointerEvents: 'none' }}
            />
          )}

          {/* Selection box */}
          {selectionBox && (
            <rect
              x={Math.min(selectionBox.startX, selectionBox.currentX)}
              y={Math.min(selectionBox.startY, selectionBox.currentY)}
              width={Math.abs(selectionBox.currentX - selectionBox.startX)}
              height={Math.abs(selectionBox.currentY - selectionBox.startY)}
              fill="rgba(31, 110, 104, 0.1)"
              stroke="var(--teal)"
              strokeWidth={1}
              strokeDasharray="4,4"
              style={{ pointerEvents: 'none' }}
            />
          )}
        </svg>

        {/* Connect mode indicator */}
        {!readOnly && workspaceRevealed && connectMode && (
          <div className="connect-mode-indicator">
            Click another node to connect, or press Escape to cancel
          </div>
        )}

        {/* Top Controls */}
        {!readOnly && workspaceRevealed && execution.isExecuting && (
          <div className="canvas-top-controls">
            <label className="track-toggle main-track-toggle" title="Track executing node">
              <input
                type="checkbox"
                checked={trackExecution}
                onChange={(e) => setTrackExecution(e.target.checked)}
              />
              <span className="track-label">Track</span>
            </label>
            <div className="canvas-status-indicator">
              <span className="pulse-dot" />
              Running
            </div>
          </div>
        )}

        {/* Mode toggle control - single button showing current mode */}
        {workspaceRevealed && (
          <button
            className="mode-toggle-btn"
            onClick={toggleCanvasMode}
            title={canvasMode === 'select' ? 'Select mode (click to switch to Pan - H)' : 'Pan mode (click to switch to Select - V)'}
          >
            {canvasMode === 'select' ? (
              /* Cursor/pointer icon for select mode */
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z" />
                <path d="M13 13l6 6" />
              </svg>
            ) : (
              /* Hand/pan icon for pan mode */
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v0" />
                <path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v6" />
                <path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8" />
                <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
              </svg>
            )}
          </button>
        )}

        {/* Zoom controls */}
        {workspaceRevealed && (
          <div className="zoom-controls">
            <button className="zoom-btn" onClick={zoomIn} title="Zoom in (+)">
              +
            </button>
            <button className="zoom-btn" onClick={() => { resetZoom(); setPanOffset({ x: 0, y: 0 }); }} title="Reset view (0)">
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
        )}

        {/* Beautify control */}
        {workspaceRevealed && (
          <div className="beautify-control">
            <button className="beautify-btn" onClick={beautifyFlowchart} title="Auto-layout (Beautify)">
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                className="flower-icon"
              >
                {/* Aura glow filter */}
                <defs>
                  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="1.5" result="coloredBlur" />
                    <feMerge>
                      <feMergeNode in="coloredBlur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <radialGradient id="petalGradient" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="var(--rose)" stopOpacity="0.9" />
                    <stop offset="100%" stopColor="var(--rose)" stopOpacity="0.6" />
                  </radialGradient>
                  <radialGradient id="centerGradient" cx="30%" cy="30%" r="70%">
                    <stop offset="0%" stopColor="var(--amber)" />
                    <stop offset="100%" stopColor="var(--rose)" />
                  </radialGradient>
                </defs>
                {/* Outer petals */}
                <ellipse className="petal petal-1" cx="12" cy="5" rx="2.5" ry="4" fill="url(#petalGradient)" />
                <ellipse className="petal petal-2" cx="17.5" cy="8" rx="2.5" ry="4" fill="url(#petalGradient)" transform="rotate(60 17.5 8)" />
                <ellipse className="petal petal-3" cx="17.5" cy="16" rx="2.5" ry="4" fill="url(#petalGradient)" transform="rotate(120 17.5 16)" />
                <ellipse className="petal petal-4" cx="12" cy="19" rx="2.5" ry="4" fill="url(#petalGradient)" />
                <ellipse className="petal petal-5" cx="6.5" cy="16" rx="2.5" ry="4" fill="url(#petalGradient)" transform="rotate(-120 6.5 16)" />
                <ellipse className="petal petal-6" cx="6.5" cy="8" rx="2.5" ry="4" fill="url(#petalGradient)" transform="rotate(-60 6.5 8)" />
                {/* Center */}
                <circle cx="12" cy="12" r="3.5" fill="url(#centerGradient)" filter="url(#glow)" />
              </svg>
            </button>
          </div>
        )}

        {/* Meta controls */}
        {workspaceRevealed && (
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
        )}
      </div>
    </div>
  )
}
