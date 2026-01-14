import type { FlowNode, FlowNodeType, FlowNodeColor } from '../types'

// Node size configuration
export const NODE_SIZES: Record<FlowNodeType, { w: number; h: number }> = {
  start: { w: 160, h: 64 },
  end: { w: 160, h: 64 },
  process: { w: 180, h: 80 },
  decision: { w: 160, h: 100 },
  subprocess: { w: 200, h: 90 },
}

// Color map
export const COLOR_MAP: Record<FlowNodeColor, string> = {
  teal: '#1f6e68',
  amber: '#c98a2c',
  green: '#3e7c4d',
  slate: '#4b5563',
  rose: '#b4533d',
  sky: '#2b6cb0',
}

// Get node dimensions
export function getNodeSize(type: FlowNodeType): { w: number; h: number } {
  return NODE_SIZES[type] || NODE_SIZES.process
}

// Get node color
export function getNodeColor(color: FlowNodeColor): string {
  return COLOR_MAP[color] || COLOR_MAP.teal
}

// Calculate connection point on node boundary
export function getConnectionPoint(
  node: FlowNode,
  direction: 'top' | 'bottom' | 'left' | 'right'
): { x: number; y: number } {
  const size = getNodeSize(node.type)
  const cx = node.x
  const cy = node.y

  switch (direction) {
    case 'top':
      return { x: cx, y: cy - size.h / 2 }
    case 'bottom':
      return { x: cx, y: cy + size.h / 2 }
    case 'left':
      return { x: cx - size.w / 2, y: cy }
    case 'right':
      return { x: cx + size.w / 2, y: cy }
  }
}

// Calculate edge path between two nodes
export function calculateEdgePath(
  fromNode: FlowNode,
  toNode: FlowNode
): string {
  // Determine best connection points based on relative positions
  let fromDir: 'top' | 'bottom' | 'left' | 'right'
  let toDir: 'top' | 'bottom' | 'left' | 'right'

  const dx = toNode.x - fromNode.x
  const dy = toNode.y - fromNode.y

  // Prefer vertical connections (top/bottom)
  if (Math.abs(dy) > Math.abs(dx) * 0.5) {
    if (dy > 0) {
      fromDir = 'bottom'
      toDir = 'top'
    } else {
      fromDir = 'top'
      toDir = 'bottom'
    }
  } else {
    // Horizontal connections
    if (dx > 0) {
      fromDir = 'right'
      toDir = 'left'
    } else {
      fromDir = 'left'
      toDir = 'right'
    }
  }

  const fromPoint = getConnectionPoint(fromNode, fromDir)
  const toPoint = getConnectionPoint(toNode, toDir)

  // Create curved path
  const midY = (fromPoint.y + toPoint.y) / 2

  if (fromDir === 'bottom' && toDir === 'top') {
    // Vertical path with curves
    return `M ${fromPoint.x} ${fromPoint.y}
            C ${fromPoint.x} ${midY}, ${toPoint.x} ${midY}, ${toPoint.x} ${toPoint.y}`
  } else if (fromDir === 'top' && toDir === 'bottom') {
    return `M ${fromPoint.x} ${fromPoint.y}
            C ${fromPoint.x} ${midY}, ${toPoint.x} ${midY}, ${toPoint.x} ${toPoint.y}`
  } else {
    // Horizontal or diagonal - use S-curve
    const midX = (fromPoint.x + toPoint.x) / 2
    return `M ${fromPoint.x} ${fromPoint.y}
            C ${midX} ${fromPoint.y}, ${midX} ${toPoint.y}, ${toPoint.x} ${toPoint.y}`
  }
}

// Generate unique node ID
export function generateNodeId(): string {
  return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

// Calculate viewBox to fit all nodes
export function calculateViewBox(
  nodes: FlowNode[],
  padding: number = 100
): { x: number; y: number; width: number; height: number } {
  if (nodes.length === 0) {
    return { x: 0, y: 0, width: 1200, height: 800 }
  }

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity

  for (const node of nodes) {
    const size = getNodeSize(node.type)
    const left = node.x - size.w / 2
    const right = node.x + size.w / 2
    const top = node.y - size.h / 2
    const bottom = node.y + size.h / 2

    minX = Math.min(minX, left)
    minY = Math.min(minY, top)
    maxX = Math.max(maxX, right)
    maxY = Math.max(maxY, bottom)
  }

  const width = Math.max(maxX - minX + padding * 2, 1200)
  const height = Math.max(maxY - minY + padding * 2, 800)

  return {
    x: minX - padding,
    y: minY - padding,
    width,
    height,
  }
}

// Check if point is inside node
export function isPointInNode(
  x: number,
  y: number,
  node: FlowNode
): boolean {
  const size = getNodeSize(node.type)
  const halfW = size.w / 2
  const halfH = size.h / 2

  return (
    x >= node.x - halfW &&
    x <= node.x + halfW &&
    y >= node.y - halfH &&
    y <= node.y + halfH
  )
}

// Find node at point
export function findNodeAtPoint(
  x: number,
  y: number,
  nodes: FlowNode[]
): FlowNode | null {
  // Check in reverse order (top-most first)
  for (let i = nodes.length - 1; i >= 0; i--) {
    if (isPointInNode(x, y, nodes[i])) {
      return nodes[i]
    }
  }
  return null
}

// SVG path for decision diamond
export function getDecisionPath(cx: number, cy: number, w: number, h: number): string {
  const halfW = w / 2
  const halfH = h / 2
  return `M ${cx} ${cy - halfH} L ${cx + halfW} ${cy} L ${cx} ${cy + halfH} L ${cx - halfW} ${cy} Z`
}
