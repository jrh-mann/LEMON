import type { FlowNode, Flowchart } from '../../types'
import { NODE_SIZES } from './constants'

// Layout configuration
const LAYOUT_CONFIG = {
  SPACING_X: 240,
  SPACING_Y: 150,
  PADDING_X: 120,
  PADDING_Y: 80,
  MIN_CANVAS_WIDTH: 1200,
}

// Apply DAG auto-layout to flowchart nodes
export function autoLayoutFlowchart(flowchart: Flowchart): Flowchart {
  const { nodes, edges } = flowchart
  if (nodes.length === 0) return flowchart

  // Build level map using BFS propagation
  const levels: Record<string, number> = {}
  nodes.forEach((n) => { levels[n.id] = 0 })

  // Propagate levels: for each edge, target must be at least source+1
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

  // Build incoming edges map for sorting
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
      // First level: sort alphabetically
      group.sort((a, b) => a.label.localeCompare(b.label))
    } else {
      // Other levels: sort by average parent position
      group.sort((a, b) => {
        const parentsA = incoming[a.id] || []
        const parentsB = incoming[b.id] || []
        const avgA = parentsA.length === 0
          ? 0
          : parentsA.reduce((s, p) => s + (orderIndex[p] ?? 0), 0) / parentsA.length
        const avgB = parentsB.length === 0
          ? 0
          : parentsB.reduce((s, p) => s + (orderIndex[p] ?? 0), 0) / parentsB.length
        return avgA - avgB
      })
    }

    group.forEach((node, idx) => { orderIndex[node.id] = idx })
  }

  // Position nodes
  const { SPACING_X, SPACING_Y, PADDING_X, PADDING_Y, MIN_CANVAS_WIDTH } = LAYOUT_CONFIG
  const maxGroupSize = Math.max(...levelGroups.map((g) => g.length), 1)
  const canvasWidth = Math.max(MIN_CANVAS_WIDTH, PADDING_X * 2 + (maxGroupSize - 1) * SPACING_X)

  const layoutedNodes: FlowNode[] = []

  for (let levelIdx = 0; levelIdx < levelGroups.length; levelIdx++) {
    const group = levelGroups[levelIdx]
    const groupWidth = (group.length - 1) * SPACING_X
    const startX = Math.max(PADDING_X, (canvasWidth - groupWidth) / 2)
    const y = PADDING_Y + levelIdx * SPACING_Y

    for (let idx = 0; idx < group.length; idx++) {
      const node = group[idx]
      const size = NODE_SIZES[node.type] || NODE_SIZES.process

      // Position as CENTER coordinates
      layoutedNodes.push({
        ...node,
        x: startX + idx * SPACING_X + size.w / 2,
        y: y + size.h / 2,
      })
    }
  }

  return { nodes: layoutedNodes, edges }
}
