import type { FlowNode, FlowNodeType, FlowNodeColor, Flowchart } from '../types'

// Backend BlockType to Frontend FlowNodeType mapping
const BLOCK_TYPE_MAP: Record<string, FlowNodeType> = {
  input: 'process',
  output: 'end',
  workflow_ref: 'subprocess',
  // These already match
  start: 'start',
  end: 'end',
  process: 'process',
  decision: 'decision',
  subprocess: 'subprocess',
}

// Default color for each block type from backend
const BLOCK_TYPE_COLORS: Record<string, FlowNodeColor> = {
  input: 'teal',
  output: 'green',
  workflow_ref: 'sky',
  start: 'teal',
  end: 'green',
  process: 'teal',
  decision: 'amber',
  subprocess: 'sky',
}

// Sanitize labels - remove JSON artifacts, clean up text
function sanitizeLabel(label: string | undefined | null): string {
  if (!label) return 'Node'

  let clean = String(label)

  // Remove JSON-like patterns
  clean = clean.replace(/^\{.*\}$/s, '')
  clean = clean.replace(/^\[.*\]$/s, '')
  clean = clean.replace(/^["']|["']$/g, '')

  // Trim and fallback
  clean = clean.trim()
  return clean || 'Node'
}

// Transform a single node from backend format to frontend format
// Backend sends TOP-LEFT coordinates, frontend expects CENTER
function transformNode(rawNode: Record<string, unknown>): FlowNode {
  const type = rawNode.type as string
  const size = NODE_SIZES[BLOCK_TYPE_MAP[type] || 'process'] || NODE_SIZES.process

  // Convert TOP-LEFT to CENTER coordinates
  const x = (rawNode.x as number) + size.w / 2
  const y = (rawNode.y as number) + size.h / 2

  return {
    id: rawNode.id as string,
    type: BLOCK_TYPE_MAP[type] || 'process',
    label: sanitizeLabel(rawNode.label as string),
    x,
    y,
    color: (rawNode.color as FlowNodeColor) || BLOCK_TYPE_COLORS[type] || 'teal',
  }
}

// Check if nodes need auto-layout (all at same position or overlapping)
function needsAutoLayout(nodes: FlowNode[]): boolean {
  if (nodes.length <= 1) return false

  // Check if all nodes are at the same position (or very close)
  const positions = new Set<string>()
  for (const node of nodes) {
    const key = `${Math.round(node.x / 50)},${Math.round(node.y / 50)}`
    positions.add(key)
  }

  // If most nodes share the same position bucket, we need layout
  return positions.size < nodes.length / 2
}

// Apply DAG auto-layout to flowchart nodes
export function autoLayoutFlowchart(flowchart: Flowchart): Flowchart {
  const { nodes, edges } = flowchart
  if (nodes.length === 0) return flowchart

  // Build level map using BFS propagation
  const levels: Record<string, number> = {}
  nodes.forEach((n) => { levels[n.id] = 0 })

  // Propagate levels: for each edge, to must be at least from+1
  for (let i = 0; i < nodes.length; i++) {
    let changed = false
    for (const edge of edges) {
      if (levels[edge.from] !== undefined && levels[edge.to] !== undefined) {
        const nextLevel = levels[edge.from] + 1
        if (levels[edge.to] < nextLevel) {
          levels[edge.to] = nextLevel
          changed = true
        }
      }
    }
    if (!changed) break
  }

  // Group nodes by level
  const maxLevel = Math.max(...Object.values(levels), 0)
  const levelGroups: FlowNode[][] = Array.from({ length: maxLevel + 1 }, () => [])
  const nodeById: Record<string, FlowNode> = {}

  for (const node of nodes) {
    nodeById[node.id] = node
    const lvl = levels[node.id] ?? 0
    levelGroups[lvl].push(node)
  }

  // Build incoming edges map
  const incoming: Record<string, string[]> = {}
  nodes.forEach((n) => { incoming[n.id] = [] })
  for (const edge of edges) {
    if (incoming[edge.to]) {
      incoming[edge.to].push(edge.from)
    }
  }

  // Sort nodes within each level
  const orderIndex: Record<string, number> = {}
  for (let levelIdx = 0; levelIdx < levelGroups.length; levelIdx++) {
    const group = levelGroups[levelIdx]
    if (levelIdx === 0) {
      group.sort((a, b) => a.label.localeCompare(b.label))
    } else {
      group.sort((a, b) => {
        const parentsA = incoming[a.id] || []
        const parentsB = incoming[b.id] || []
        const avgA = parentsA.length === 0 ? 0 : parentsA.reduce((s, p) => s + (orderIndex[p] ?? 0), 0) / parentsA.length
        const avgB = parentsB.length === 0 ? 0 : parentsB.reduce((s, p) => s + (orderIndex[p] ?? 0), 0) / parentsB.length
        return avgA - avgB
      })
    }
    group.forEach((node, idx) => { orderIndex[node.id] = idx })
  }

  // Position nodes
  const spacingX = 240
  const spacingY = 150
  const paddingX = 120
  const paddingY = 80

  const maxGroupSize = Math.max(...levelGroups.map((g) => g.length), 1)
  const canvasWidth = Math.max(1200, paddingX * 2 + (maxGroupSize - 1) * spacingX)

  const layoutedNodes: FlowNode[] = []
  for (let levelIdx = 0; levelIdx < levelGroups.length; levelIdx++) {
    const group = levelGroups[levelIdx]
    const groupWidth = (group.length - 1) * spacingX
    const startX = Math.max(paddingX, (canvasWidth - groupWidth) / 2)
    const y = paddingY + levelIdx * spacingY

    for (let idx = 0; idx < group.length; idx++) {
      const node = group[idx]
      const size = NODE_SIZES[node.type] || NODE_SIZES.process
      // Position as CENTER coordinates
      layoutedNodes.push({
        ...node,
        x: startX + idx * spacingX + size.w / 2,
        y: y + size.h / 2,
      })
    }
  }

  return { nodes: layoutedNodes, edges }
}

// Transform raw backend flowchart data to frontend format
export function transformFlowchartFromBackend(
  data: { nodes?: unknown[]; edges?: unknown[] }
): Flowchart {
  const nodes: FlowNode[] = (data.nodes || []).map((rawNode) =>
    transformNode(rawNode as Record<string, unknown>)
  )

  const edges = (data.edges || []).map((rawEdge) => {
    const edge = rawEdge as Record<string, unknown>
    return {
      from: edge.from as string,
      to: edge.to as string,
      label: sanitizeLabel(edge.label as string) || '',
      id: edge.id as string | undefined,
    }
  })

  let flowchart: Flowchart = { nodes, edges }

  // Apply auto-layout if positions are all overlapping
  if (needsAutoLayout(nodes)) {
    flowchart = autoLayoutFlowchart(flowchart)
  }

  return flowchart
}

// Transform a single node from backend format (exported for add_block events)
export function transformNodeFromBackend(rawNode: Record<string, unknown>): FlowNode {
  return transformNode(rawNode)
}

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

// Get connection point on decision diamond
// Diamond points: top, right, bottom, left (clockwise from top)
export function getDecisionConnectionPoint(
  node: FlowNode,
  position: 'top' | 'bottom' | 'bottom-left' | 'bottom-right'
): { x: number; y: number } {
  const size = getNodeSize(node.type)
  const cx = node.x
  const cy = node.y
  const halfW = size.w / 2
  const halfH = size.h / 2

  switch (position) {
    case 'top':
      // Top point of diamond
      return { x: cx, y: cy - halfH }
    case 'bottom':
      // Bottom point of diamond
      return { x: cx, y: cy + halfH }
    case 'bottom-left':
      // Halfway down the left diagonal edge (between left point and bottom point)
      return { x: cx - halfW / 2, y: cy + halfH / 2 }
    case 'bottom-right':
      // Halfway down the right diagonal edge (between right point and bottom point)
      return { x: cx + halfW / 2, y: cy + halfH / 2 }
  }
}

// Calculate edge path between two nodes
// edgeLabel: used for decision nodes to determine output position (Yes/No/other)
// edgeIndex: the index of this edge among all edges from the same source (0-based)
export function calculateEdgePath(
  fromNode: FlowNode,
  toNode: FlowNode,
  edgeLabel?: string,
  edgeIndex?: number
): string {
  let fromPoint: { x: number; y: number }
  let toPoint: { x: number; y: number }

  // Special handling for decision nodes
  if (fromNode.type === 'decision') {
    // Decision output: Yes = bottom-left, No = bottom-right, 3rd = bottom center
    const label = (edgeLabel || '').toLowerCase().trim()

    if (label === 'yes' || label === 'y' || edgeIndex === 0) {
      fromPoint = getDecisionConnectionPoint(fromNode, 'bottom-left')
    } else if (label === 'no' || label === 'n' || edgeIndex === 1) {
      fromPoint = getDecisionConnectionPoint(fromNode, 'bottom-right')
    } else {
      // Third option or unlabeled - use bottom center
      fromPoint = getDecisionConnectionPoint(fromNode, 'bottom')
    }
  } else {
    // Normal node - determine exit point based on relative position
    const dx = toNode.x - fromNode.x
    const dy = toNode.y - fromNode.y

    let fromDir: 'top' | 'bottom' | 'left' | 'right'
    if (Math.abs(dy) > Math.abs(dx) * 0.5) {
      fromDir = dy > 0 ? 'bottom' : 'top'
    } else {
      fromDir = dx > 0 ? 'right' : 'left'
    }
    fromPoint = getConnectionPoint(fromNode, fromDir)
  }

  // Special handling for entering decision nodes - always enter from top
  if (toNode.type === 'decision') {
    toPoint = getDecisionConnectionPoint(toNode, 'top')
  } else {
    // Normal node - determine entry point based on relative position
    const dx = toNode.x - fromNode.x
    const dy = toNode.y - fromNode.y

    let toDir: 'top' | 'bottom' | 'left' | 'right'
    if (Math.abs(dy) > Math.abs(dx) * 0.5) {
      toDir = dy > 0 ? 'top' : 'bottom'
    } else {
      toDir = dx > 0 ? 'left' : 'right'
    }
    toPoint = getConnectionPoint(toNode, toDir)
  }

  // Create curved path
  const midY = (fromPoint.y + toPoint.y) / 2
  const midX = (fromPoint.x + toPoint.x) / 2

  // Determine if this is primarily vertical or horizontal
  const dx = Math.abs(toPoint.x - fromPoint.x)
  const dy = Math.abs(toPoint.y - fromPoint.y)

  if (dy > dx * 0.3) {
    // Primarily vertical - use vertical bezier
    return `M ${fromPoint.x} ${fromPoint.y}
            C ${fromPoint.x} ${midY}, ${toPoint.x} ${midY}, ${toPoint.x} ${toPoint.y}`
  } else {
    // Primarily horizontal - use S-curve
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
