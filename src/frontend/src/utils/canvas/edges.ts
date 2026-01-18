import type { FlowNode } from '../../types'
import { EDGE_THRESHOLDS } from './constants'
import {
  type Direction,
  type Point,
  getConnectionPoint,
  getDecisionConnectionPoint,
} from './geometry'

const { HORIZONTAL_OFFSET, VERTICAL_RATIO, MIN_SEGMENT, ALIGNMENT_THRESHOLD } = EDGE_THRESHOLDS

// Determine the exit direction from a node toward a target
function getExitDirection(fromNode: FlowNode, toNode: FlowNode): Direction {
  const dx = toNode.x - fromNode.x
  const dy = toNode.y - fromNode.y

  if (fromNode.type === 'decision') {
    // Decision nodes use position-based routing
    if (dy > 0) {
      if (dx < -HORIZONTAL_OFFSET) return 'left'
      if (dx > HORIZONTAL_OFFSET) return 'right'
      return 'bottom'
    }
    return 'top'
  }

  // Normal nodes: prefer vertical if mostly vertical movement
  if (Math.abs(dy) > Math.abs(dx) * VERTICAL_RATIO) {
    return dy > 0 ? 'bottom' : 'top'
  }
  return dx > 0 ? 'right' : 'left'
}

// Determine the entry direction into a node from a source
function getEntryDirection(fromNode: FlowNode, toNode: FlowNode): Direction {
  // Decision nodes always entered from top
  if (toNode.type === 'decision') {
    return 'top'
  }

  const dx = toNode.x - fromNode.x
  const dy = toNode.y - fromNode.y

  if (Math.abs(dy) > Math.abs(dx) * VERTICAL_RATIO) {
    return dy > 0 ? 'top' : 'bottom'
  }
  return dx > 0 ? 'left' : 'right'
}

// Get the exit point from a node
function getExitPoint(node: FlowNode, direction: Direction, toNode: FlowNode): Point {
  if (node.type === 'decision') {
    const dx = toNode.x - node.x
    const dy = toNode.y - node.y

    if (dy > 0) {
      if (dx < -HORIZONTAL_OFFSET) {
        return getDecisionConnectionPoint(node, 'bottom-left')
      }
      if (dx > HORIZONTAL_OFFSET) {
        return getDecisionConnectionPoint(node, 'bottom-right')
      }
      return getDecisionConnectionPoint(node, 'bottom')
    }
    return getDecisionConnectionPoint(node, 'top')
  }

  return getConnectionPoint(node, direction)
}

// Get the entry point into a node
function getEntryPoint(node: FlowNode, direction: Direction): Point {
  if (node.type === 'decision') {
    return getDecisionConnectionPoint(node, 'top')
  }
  return getConnectionPoint(node, direction)
}

// Check if two points are approximately aligned (for straight lines)
function areAligned(a: number, b: number): boolean {
  return Math.abs(a - b) < ALIGNMENT_THRESHOLD
}

// Build orthogonal path (right angles only) between two points
function buildOrthogonalPath(
  from: Point,
  to: Point,
  fromDir: Direction,
  toDir: Direction
): Point[] {
  const points: Point[] = [from]

  // Straight vertical path
  if (fromDir === 'bottom' && toDir === 'top') {
    if (areAligned(from.x, to.x)) {
      points.push(to)
    } else {
      const midY = (from.y + to.y) / 2
      points.push({ x: from.x, y: midY })
      points.push({ x: to.x, y: midY })
      points.push(to)
    }
    return points
  }

  // Straight vertical path (upward)
  if (fromDir === 'top' && toDir === 'bottom') {
    if (areAligned(from.x, to.x)) {
      points.push(to)
    } else {
      const midY = (from.y + to.y) / 2
      points.push({ x: from.x, y: midY })
      points.push({ x: to.x, y: midY })
      points.push(to)
    }
    return points
  }

  // Horizontal exit to vertical entry
  if ((fromDir === 'left' || fromDir === 'right') && toDir === 'top') {
    const extendX = fromDir === 'left' ? from.x - MIN_SEGMENT : from.x + MIN_SEGMENT
    points.push({ x: extendX, y: from.y })
    points.push({ x: extendX, y: to.y - MIN_SEGMENT })
    points.push({ x: to.x, y: to.y - MIN_SEGMENT })
    points.push(to)
    return points
  }

  // Vertical exit to horizontal entry
  if (fromDir === 'bottom' && (toDir === 'left' || toDir === 'right')) {
    const extendY = from.y + MIN_SEGMENT
    const extendX = toDir === 'left' ? to.x - MIN_SEGMENT : to.x + MIN_SEGMENT
    points.push({ x: from.x, y: extendY })
    points.push({ x: extendX, y: extendY })
    points.push({ x: extendX, y: to.y })
    points.push(to)
    return points
  }

  // Horizontal to horizontal
  if ((fromDir === 'left' || fromDir === 'right') && (toDir === 'left' || toDir === 'right')) {
    const midX = (from.x + to.x) / 2
    points.push({ x: midX, y: from.y })
    points.push({ x: midX, y: to.y })
    points.push(to)
    return points
  }

  // Fallback: simple L-shape
  if (Math.abs(from.y - to.y) > Math.abs(from.x - to.x)) {
    points.push({ x: from.x, y: to.y })
  } else {
    points.push({ x: to.x, y: from.y })
  }
  points.push(to)

  return points
}

// Convert points array to SVG path string
function pointsToPath(points: Point[]): string {
  if (points.length === 0) return ''

  let path = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length; i++) {
    path += ` L ${points[i].x} ${points[i].y}`
  }
  return path
}

// Main function: calculate edge path between two nodes
export function calculateEdgePath(
  fromNode: FlowNode,
  toNode: FlowNode,
  _edgeLabel?: string,  // Kept for API compatibility, but not used (position-based now)
  _edgeIndex?: number,  // Kept for API compatibility, but not used
  _pathOffset: number = 0  // Kept for API compatibility
): string {
  // 1. Determine directions
  const fromDir = getExitDirection(fromNode, toNode)
  const toDir = getEntryDirection(fromNode, toNode)

  // 2. Calculate connection points
  const fromPoint = getExitPoint(fromNode, fromDir, toNode)
  const toPoint = getEntryPoint(toNode, toDir)

  // 3. Build orthogonal path
  const points = buildOrthogonalPath(fromPoint, toPoint, fromDir, toDir)

  // 4. Convert to SVG path
  return pointsToPath(points)
}
