import { useRef, useEffect, useCallback, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import ImageAnnotator from './ImageAnnotator'
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
  calculation: 'Calculate',
}

// Get fill color based on node type
const getNodeFillColor = (type: FlowNodeType): string => {
  switch (type) {
    case 'start': return 'var(--teal-light)'
    case 'decision': return 'var(--amber-light)'
    case 'end': return 'var(--green-light)'
    case 'subprocess': return 'var(--rose-light)'
    case 'calculation': return 'var(--purple-light)'
    case 'process': return 'var(--paper)'
    default: return 'var(--paper)'
  }
}

// Get stroke color based on node type
const getNodeStrokeColor = (type: FlowNodeType): string => {
  switch (type) {
    case 'start': return 'var(--teal)'
    case 'decision': return 'var(--amber)'
    case 'end': return 'var(--green)'
    case 'subprocess': return 'var(--rose)'
    case 'calculation': return 'var(--purple)'
    case 'process': return 'var(--edge)'
    default: return 'var(--edge)'
  }
}

export default function Canvas() {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const {
    flowchart,
    setFlowchart,
    selectedNodeId: _selectedNodeId,
    selectedNodeIds,
    selectedEdge,
    connectMode,
    connectFromId,
    selectNode,
    selectNodes,
    selectEdge,
    clearSelection,
    moveNode,
    moveNodes,
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
    pendingAnnotations,
    setPendingAnnotations,
    clearPendingFiles,
    execution,  // Execution state for visual highlighting
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
  } = useUIStore()

  // Zoom limits for wheel zoom - matches uiStore constants
  const MIN_ZOOM = 0.25
  const MAX_ZOOM = 8

  // Index of the currently displayed file in the Source Files tab
  const [selectedFileIndex, setSelectedFileIndex] = useState(0)

  // Auto-switch to image tab when files are uploaded (only for images),
  // and reset the file index so we start from the first file.
  useEffect(() => {
    const hasImage = pendingFiles.some(f => f.type === 'image')
    if (hasImage) {
      setCanvasTab('image')
    }
    setSelectedFileIndex(0)
  }, [pendingFiles, setCanvasTab])


  // Drag state
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
    [connectMode, connectFromId, completeConnect, screenToSVG, selectNode, selectNodes, selectedNodeIds, flowchart.nodes]
  )

  // Check if position collides with any node
  const hasCollision = useCallback(
    (nodeId: string, x: number, y: number, nodeType: string): boolean => {
      const draggingSize = getNodeSize(nodeType as any)
      const padding = 20

      for (const other of flowchart.nodes) {
        if (other.id === nodeId) continue

        const otherSize = getNodeSize(other.type)
        const minDistX = draggingSize.w / 2 + otherSize.w / 2 + padding
        const minDistY = draggingSize.h / 2 + otherSize.h / 2 + padding

        if (Math.abs(x - other.x) < minDistX && Math.abs(y - other.y) < minDistY) {
          return true
        }
      }
      return false
    },
    [flowchart.nodes]
  )

  // Find valid position that doesn't collide - allows sliding along edges
  const checkCollision = useCallback(
    (nodeId: string, newX: number, newY: number): { x: number; y: number } => {
      const draggingNode = flowchart.nodes.find(n => n.id === nodeId)
      if (!draggingNode) return { x: newX, y: newY }

      // If no collision at target, allow it
      if (!hasCollision(nodeId, newX, newY, draggingNode.type)) {
        return { x: newX, y: newY }
      }

      // There's a collision - try sliding along each axis independently
      const startX = draggingNode.x
      const startY = draggingNode.y

      // Try X movement only (horizontal slide)
      let finalX = startX
      if (!hasCollision(nodeId, newX, startY, draggingNode.type)) {
        finalX = newX
      } else {
        // Binary search for X
        let lo = 0, hi = 1
        const dx = newX - startX
        for (let i = 0; i < 10; i++) {
          const mid = (lo + hi) / 2
          const testX = startX + dx * mid
          if (hasCollision(nodeId, testX, startY, draggingNode.type)) {
            hi = mid
          } else {
            lo = mid
          }
        }
        finalX = startX + dx * lo
      }

      // Try Y movement only (vertical slide)
      let finalY = startY
      if (!hasCollision(nodeId, finalX, newY, draggingNode.type)) {
        finalY = newY
      } else {
        // Binary search for Y
        let lo = 0, hi = 1
        const dy = newY - startY
        for (let i = 0; i < 10; i++) {
          const mid = (lo + hi) / 2
          const testY = startY + dy * mid
          if (hasCollision(nodeId, finalX, testY, draggingNode.type)) {
            hi = mid
          } else {
            lo = mid
          }
        }
        finalY = startY + dy * lo
      }

      return { x: finalX, y: finalY }
    },
    [flowchart.nodes, hasCollision]
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
        const newPos = checkCollision(dragNodeId, dragStart.nodeX + dx, dragStart.nodeY + dy)
        moveNode(dragNodeId, newPos.x, newPos.y)
      }
    },
    [isDragging, dragNodeId, dragStart, screenToSVG, moveNode, moveNodes, dragConnection, checkCollision, isPanning, panStart, viewBox.width, selectionBox, dragStartPositions, selectedNodeIds]
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

        if (targetNode) {
          // Create edge
          addEdge({ from: dragConnection.fromNodeId, to: targetNode.id, label: '' })
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
      setDragStartPositions(null)
      // Release pointer capture from SVG
      svgRef.current?.releasePointerCapture(e.pointerId)
    },
    [isDragging, dragNodeId, pushHistory, dragConnection, flowchart.nodes, screenToSVG, addEdge, isPanning, selectionBox, selectedNodeIds, selectNodes, clearSelection]
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
    [panOffset, screenToSVG, clearSelection, canvasMode]
  )

  // Handle canvas click (just cancel connect mode, selection handled by pointer events)
  const handleCanvasClick = useCallback(
    (_e: React.MouseEvent) => {
      if (connectMode) {
        cancelConnect()
      }
    },
    [connectMode, cancelConnect]
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
      // Ignore shortcuts when typing in input fields
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }

      // Delete selected nodes
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeIds.length > 0) {
        // Delete all selected nodes
        selectedNodeIds.forEach(nodeId => deleteNode(nodeId))
      }

      // Undo/Redo
      if (e.key === 'z' && (e.metaKey || e.ctrlKey)) {
        if (e.shiftKey) {
          redo()
        } else {
          undo()
        }
      }

      // Cancel connect mode or clear selection
      if (e.key === 'Escape') {
        if (connectMode) {
          cancelConnect()
        } else if (selectedNodeIds.length > 0) {
          clearSelection()
        }
      }

      // Canvas mode shortcuts (V for select, H for pan/hand)
      if (e.key === 'v' || e.key === 'V') {
        setCanvasMode('select')
      }
      if (e.key === 'h' || e.key === 'H') {
        setCanvasMode('pan')
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNodeIds, deleteNode, undo, redo, connectMode, cancelConnect, clearSelection, setCanvasMode])

  // Mouse wheel zoom handler - zooms centered on cursor position
  // Wheel up = zoom in, wheel down = zoom out
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      // Prevent default scroll behavior on the canvas
      e.preventDefault()

      const svg = svgRef.current
      const container = containerRef.current
      if (!svg || !container) return

      // Calculate zoom factor based on wheel delta
      // Smaller factor for smoother zooming
      const zoomFactor = 0.1
      const delta = e.deltaY > 0 ? -zoomFactor : zoomFactor

      // Calculate new zoom level with clamping
      const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom + delta))

      // If zoom didn't change (at limits), don't update
      if (newZoom === zoom) return

      // Get cursor position in SVG coordinates before zoom
      const cursorSVG = screenToSVG(e.clientX, e.clientY)

      // Calculate the ratio of zoom change
      const zoomRatio = zoom / newZoom

      // Adjust pan offset to keep cursor position fixed
      // The formula ensures that the point under the cursor stays in place
      // newPan = oldPan + cursorSVG * (1 - zoomRatio)
      // This compensates for the viewBox width/height change when zooming
      const newPanX = panOffset.x + cursorSVG.x * (1 - zoomRatio)
      const newPanY = panOffset.y + cursorSVG.y * (1 - zoomRatio)

      // Apply the new zoom and pan offset
      setZoom(newZoom)
      setPanOffset({ x: newPanX, y: newPanY })
    },
    [zoom, panOffset, screenToSVG, setZoom]
  )

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
    ].filter(Boolean).join(' ')

    return (
      <g
        key={node.id}
        className={classNames}
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
          x={node.type === 'start' || node.type === 'end' ? 8 : 0}
          textAnchor="middle"
          fontSize="13"
          fill="var(--ink)"
          style={{ pointerEvents: 'none', userSelect: 'none' }}
        >
          {wrapText(node.label, node.type === 'decision' ? 14 : 18).map((line, i, arr) => (
            <tspan
              key={i}
              x={node.type === 'start' || node.type === 'end' ? 8 : 0}
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
  const renderEdge = (edge: { from: string; to: string; label: string }, _edgeIndex: number) => {
    const fromNode = flowchart.nodes.find((n) => n.id === edge.from)
    const toNode = flowchart.nodes.find((n) => n.id === edge.to)

    if (!fromNode || !toNode) return null

    // Calculate index of this edge among all edges from the same source
    const edgesFromSameSource = flowchart.edges.filter(e => e.from === edge.from)
    const indexFromSource = edgesFromSameSource.findIndex(e => e.from === edge.from && e.to === edge.to)

    const path = calculateEdgePath(fromNode, toNode, edge.label, indexFromSource)

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
        {/* Invisible wider path for easier clicking - increased from 12 to 20 */}
        <path
          d={path}
          fill="none"
          stroke="transparent"
          strokeWidth={20}
          style={{ cursor: 'pointer' }}
        />
        {/* Visible edge line - increased stroke width for better visibility */}
        <path
          d={path}
          fill="none"
          stroke={isSelected ? 'var(--accent)' : 'var(--ink)'}
          strokeWidth={isSelected ? 3 : 2}
          markerEnd="url(#arrowhead)"
        />
        {/* Show label for decision edges, or any edge with a label */}
        {(edge.label || isDecisionEdge) && (
          <text
            x={labelX}
            y={labelY}
            textAnchor="middle"
            fontSize="11"
            fill={isSelected ? 'var(--accent)' : 'var(--muted)'}
            fontWeight={isSelected ? 600 : 400}
          >
            {edge.label || (isDecisionEdge ? '?' : '')}
          </text>
        )}
      </g>
    )
  }

  // Wrap text into multiple lines, breaking on spaces
  function wrapText(text: string, maxCharsPerLine: number): string[] {
    if (text.length <= maxCharsPerLine) return [text]

    const words = text.split(' ')
    const lines: string[] = []
    let currentLine = ''

    for (const word of words) {
      if (currentLine.length === 0) {
        currentLine = word
      } else if (currentLine.length + 1 + word.length <= maxCharsPerLine) {
        currentLine += ' ' + word
      } else {
        lines.push(currentLine)
        currentLine = word
      }
    }
    if (currentLine) lines.push(currentLine)

    // Limit to 3 lines max, truncate last line if needed
    if (lines.length > 3) {
      lines.length = 3
      lines[2] = lines[2].slice(0, maxCharsPerLine - 1) + 'â€¦'
    }

    return lines
  }

  // Beautify/auto-layout the flowchart - hierarchical tree with node duplication
  const beautifyFlowchart = useCallback(() => {
    if (flowchart.nodes.length === 0) return

    // De-dupe nodes/edges to keep layout stable across repeated runs.
    const nodeById = new Map(flowchart.nodes.map((node) => [node.id, node]))
    const nodes = Array.from(nodeById.values())
    const edgeKeys = new Set<string>()
    const edges = flowchart.edges.filter((edge) => {
      const key = `${edge.from}->${edge.to}:${edge.label || ''}`
      if (edgeKeys.has(key)) return false
      edgeKeys.add(key)
      return nodeById.has(edge.from) && nodeById.has(edge.to)
    })

    // Build adjacency list for outgoing edges with labels
    const outgoing = new Map<string, { to: string; label: string }[]>()
    const incoming = new Map<string, string[]>()
    nodes.forEach(n => {
      outgoing.set(n.id, [])
      incoming.set(n.id, [])
    })
    edges.forEach(e => {
      outgoing.get(e.from)?.push({ to: e.to, label: e.label })
      incoming.get(e.to)?.push(e.from)
    })

    // Remove orphan nodes (no connections at all) - they don't belong in the flowchart
    const orphanNodeIds = new Set(
      flowchart.nodes
        .filter(n => (incoming.get(n.id)?.length ?? 0) === 0 && (outgoing.get(n.id)?.length ?? 0) === 0)
        .map(n => n.id)
    )

    // Start nodes: no incoming edges but have outgoing, or type 'start'
    let startNodes = nodes.filter(n =>
      !orphanNodeIds.has(n.id) &&
      (((incoming.get(n.id)?.length ?? 0) === 0 && (outgoing.get(n.id)?.length ?? 0) > 0) ||
        n.type === 'start')
    )

    // If no start nodes found, use first connected node
    if (startNodes.length === 0) {
      const connectedNodes = nodes.filter(n => !orphanNodeIds.has(n.id))
      if (connectedNodes.length > 0) {
        startNodes = [connectedNodes[0]]
      } else {
        // All nodes are orphans - nothing to beautify
        return
      }
    }

    // Tree traversal with duplication for shared nodes
    interface TreeNode {
      id: string           // new unique id (may have _dup suffix)
      originalId: string   // original node id
      layer: number
      children: TreeNode[]
      parentId: string | null
      edgeLabel: string
    }

    const newNodes: FlowNode[] = []
    const newEdges: { from: string; to: string; label: string }[] = []
    const visited = new Set<string>()
    let dupCounter = 0

    // Layout constants - increased spacing
    const layerSpacing = 160
    const nodeSpacing = 220
    const startY = 100

    // Skip orphan placement - they're removed
    orphanNodeIds.forEach(id => {
      visited.add(id) // Mark as visited so they won't be added later
    })

    // Start tree at top (no orphan row)
    const treeStartY = startY

    // Build tree structure via BFS
    const roots: TreeNode[] = []
    const queue: TreeNode[] = []

    // Use actual start nodes as roots (no synthetic entry point).
    startNodes.forEach(node => {
      if (visited.has(node.id)) return
      const treeNode: TreeNode = {
        id: node.id,
        originalId: node.id,
        layer: 0,
        children: [],
        parentId: null,
        edgeLabel: ''
      }
      roots.push(treeNode)
      queue.push(treeNode)
      visited.add(node.id)
    })

    while (queue.length > 0) {
      const current = queue.shift()!
      const children = outgoing.get(current.originalId) || []

      children.forEach(({ to, label }) => {
        let childId: string
        if (visited.has(to)) {
          // Already visited - duplicate this node
          dupCounter++
          childId = `${to}_dup${dupCounter}`
        } else {
          childId = to
          visited.add(to)
        }

        const childTreeNode: TreeNode = {
          id: childId,
          originalId: to,
          layer: current.layer + 1,
          children: [],
          parentId: current.id,
          edgeLabel: label
        }
        current.children.push(childTreeNode)
        queue.push(childTreeNode)
      })
    }

    // Handle any remaining disconnected nodes (connected to each other but not to start)
    nodes.forEach(n => {
      if (!visited.has(n.id)) {
        const treeNode: TreeNode = {
          id: n.id,
          originalId: n.id,
          layer: 0,
          children: [],
          parentId: null,
          edgeLabel: ''
        }
        roots.push(treeNode)
        visited.add(n.id)
      }
    })

    // Calculate subtree width - ensures minimum spacing for each node
    const getSubtreeWidth = (node: TreeNode): number => {
      if (node.children.length === 0) return 1
      // Sum of children's widths, but ensure at least 1 per child for spacing
      const childrenWidth = node.children.reduce((sum, child) => sum + getSubtreeWidth(child), 0)
      // Ensure minimum width accounts for number of direct children
      return Math.max(childrenWidth, node.children.length)
    }

    // Count total descendants in a subtree
    const getDescendantCount = (node: TreeNode): number => {
      if (node.children.length === 0) return 0
      return node.children.reduce((sum, child) => sum + 1 + getDescendantCount(child), 0)
    }

    // Order node children: most descendants in center (straight down)
    // Uses consistent descendant-based ordering for all multi-child nodes
    const orderNodeChildren = (node: TreeNode) => {
      if (node.children.length >= 2) {
        // Calculate descendant count for all children
        const childrenWithCounts = node.children.map(child => ({
          child,
          descendants: getDescendantCount(child)
        }))

        // Sort by descendant count descending (most descendants first)
        childrenWithCounts.sort((a, b) => b.descendants - a.descendants)

        if (node.children.length === 2) {
          // Two children: keep larger on right (tends to look better with downward flow)
          // Smaller on left, larger on right
          const [larger, smaller] = childrenWithCounts.map(c => c.child)
          node.children = [smaller, larger]
        } else if (node.children.length === 3) {
          // Three children: most descendants in middle
          const [largest, second, third] = childrenWithCounts.map(c => c.child)
          node.children = [second, largest, third]
        } else {
          // More than 3: most descendants in middle, distribute others around
          const sorted = childrenWithCounts.map(c => c.child)
          const middle = sorted[0] // most descendants
          const others = sorted.slice(1)
          const left = others.filter((_, i) => i % 2 === 0)
          const right = others.filter((_, i) => i % 2 === 1)
          node.children = [...left, middle, ...right]
        }
      }

      // Recursively apply to all children
      node.children.forEach(orderNodeChildren)
    }

    // Apply node ordering
    roots.forEach(orderNodeChildren)

    // Assign positions recursively - children evenly spaced under parent
    const siblingGap = 40 // extra gap between siblings
    const assignPositions = (node: TreeNode, leftX: number): number => {
      const subtreeWidth = getSubtreeWidth(node)
      // Width includes sibling gaps for nodes with children
      const numGaps = node.children.length > 1 ? node.children.length - 1 : 0
      const myWidth = subtreeWidth * nodeSpacing + numGaps * siblingGap

      if (node.children.length === 0) {
        // Leaf node - place in center of allocated space
        const nodeX = leftX + myWidth / 2

        const originalNode = nodes.find(n => n.id === node.originalId)!
        newNodes.push({
          ...originalNode,
          id: node.id,
          x: nodeX,
          y: treeStartY + node.layer * layerSpacing
        })

        if (node.parentId) {
          newEdges.push({ from: node.parentId, to: node.id, label: node.edgeLabel })
        }

        return myWidth
      }

      // Position children first, evenly distributed with sibling gap
      let childX = leftX
      node.children.forEach((child, idx) => {
        const childWidth = assignPositions(child, childX)
        childX += childWidth
        // Add sibling gap between children (not after last)
        if (idx < node.children.length - 1) {
          childX += siblingGap
        }
      })

      // Position this node centered over its children
      const firstChild = newNodes.find(n => n.id === node.children[0].id)!
      const lastChild = newNodes.find(n => n.id === node.children[node.children.length - 1].id)!
      const nodeX = (firstChild.x + lastChild.x) / 2

      const originalNode = nodes.find(n => n.id === node.originalId)
      if (originalNode) {
        newNodes.push({
          ...originalNode,
          id: node.id,
          x: nodeX,
          y: treeStartY + node.layer * layerSpacing
        })
      }

      if (node.parentId) {
        newEdges.push({ from: node.parentId, to: node.id, label: node.edgeLabel })
      }

      return myWidth
    }

    // Assign positions for all tree roots
    let currentX = 0
    roots.forEach(root => {
      const width = assignPositions(root, currentX)
      currentX += width + nodeSpacing // gap between trees
    })

    // Center the entire layout around x=400
    if (newNodes.length > 0) {
      const minX = Math.min(...newNodes.map(n => n.x))
      const maxX = Math.max(...newNodes.map(n => n.x))
      const centerOffset = 400 - (minX + maxX) / 2

      newNodes.forEach(n => {
        n.x += centerOffset
      })
    }

    // Auto-assign Yes/No labels to decision node outputs that don't have labels
    const decisionNodes = newNodes.filter(n => n.type === 'decision')
    decisionNodes.forEach(decNode => {
      const outEdges = newEdges.filter(e => e.from === decNode.id)
      if (outEdges.length >= 2) {
        // Assign Yes/No to first two edges if they don't have labels
        if (!outEdges[0].label) outEdges[0].label = 'Yes'
        if (!outEdges[1].label) outEdges[1].label = 'No'
      }
    })

    setFlowchart({ nodes: newNodes, edges: newEdges })
    pushHistory()
  }, [flowchart, setFlowchart, pushHistory])

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
        {pendingFiles.length > 0 && (
          <button
            className={`workspace-tab ${canvasTab === 'image' ? 'active' : ''}`}
            onClick={() => setCanvasTab('image')}
          >
            Source {pendingFiles.length === 1 ? 'File' : 'Files'}
          </button>
        )}
      </div>

      {/* File preview tab — shows selected file with prev/next navigation */}
      {canvasTab === 'image' && pendingFiles.length > 0 && (() => {
        // Clamp index in case files were removed
        const idx = Math.min(selectedFileIndex, pendingFiles.length - 1)
        const currentFile = pendingFiles[idx]
        const showNav = pendingFiles.length > 1
        return (
          <div className="image-preview-container">
            <div className="image-preview-header">
              {/* Prev button — only when multiple files */}
              {showNav && (
                <button
                  className="file-nav-btn"
                  disabled={idx === 0}
                  onClick={() => setSelectedFileIndex(idx - 1)}
                  title="Previous file"
                >
                  ‹
                </button>
              )}
              <span className="image-name">
                {currentFile.name}
                {showNav && ` (${idx + 1}/${pendingFiles.length})`}
              </span>
              {/* Next button — only when multiple files */}
              {showNav && (
                <button
                  className="file-nav-btn"
                  disabled={idx === pendingFiles.length - 1}
                  onClick={() => setSelectedFileIndex(idx + 1)}
                  title="Next file"
                >
                  ›
                </button>
              )}
              <button
                className="clear-image-btn"
                onClick={() => {
                  clearPendingFiles()
                  setCanvasTab('workflow')
                }}
                title="Remove all files"
              >
                ×
              </button>
            </div>
            {currentFile.type === 'image' ? (
              <ImageAnnotator
                key={currentFile.id}
                imageSrc={currentFile.dataUrl}
                annotations={pendingAnnotations}
                onChange={setPendingAnnotations}
              />
            ) : (
              <div className="pdf-placeholder">
                <p className="muted">{currentFile.name} (PDF) — preview not available</p>
              </div>
            )}
          </div>
        )
      })()}

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
          onPointerDown={handleCanvasPointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onWheel={handleWheel}
          style={{
            cursor: isPanning ? 'grabbing' : (canvasMode === 'pan' ? 'grab' : 'default')
          }}
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
          <rect width="100%" height="100%" fill="url(#grid)" style={{ pointerEvents: 'all' }} />

          {/* Edges layer */}
          <g id="edgeLayer">
            {flowchart.edges.map((edge, idx) => renderEdge(edge, idx))}
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

        {/* Mode toggle control - single button showing current mode */}
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

        {/* Zoom controls */}
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

          <div style={{ width: 1, height: 16, background: 'var(--edge)', margin: '0 4px' }} />

          <button
            className={`zoom-btn ${trackExecution ? 'active' : ''}`}
            onClick={() => setTrackExecution(!trackExecution)}
            title="Track execution"
            style={trackExecution ? { color: 'var(--rose)', borderColor: 'var(--rose)', background: 'var(--rose-light)' } : {}}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="3" fill="currentColor" />
            </svg>
          </button>
        </div>

        {/* Beautify control */}
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
