import type { FlowNode, FlowNodeType, FlowNodeColor } from '../../types'
import { NODE_SIZES, COLOR_MAP } from './constants'

// Types for geometry calculations
export type Direction = 'top' | 'bottom' | 'left' | 'right'
export type DecisionPosition = 'top' | 'bottom' | 'bottom-left' | 'bottom-right'
export interface Point { x: number; y: number }

// Get node dimensions by type
export function getNodeSize(type: FlowNodeType): { w: number; h: number } {
  return NODE_SIZES[type] || NODE_SIZES.process
}

// Get node color hex value
export function getNodeColor(color: FlowNodeColor): string {
  return COLOR_MAP[color] || COLOR_MAP.teal
}

// Calculate connection point on rectangular node boundary
export function getConnectionPoint(node: FlowNode, direction: Direction): Point {
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
export function getDecisionConnectionPoint(node: FlowNode, position: DecisionPosition): Point {
  const size = getNodeSize(node.type)
  const cx = node.x
  const cy = node.y
  const halfW = size.w / 2
  const halfH = size.h / 2

  switch (position) {
    case 'top':
      return { x: cx, y: cy - halfH }
    case 'bottom':
      return { x: cx, y: cy + halfH }
    case 'bottom-left':
      // Halfway down the left diagonal edge
      return { x: cx - halfW / 2, y: cy + halfH / 2 }
    case 'bottom-right':
      // Halfway down the right diagonal edge
      return { x: cx + halfW / 2, y: cy + halfH / 2 }
  }
}

// Calculate viewBox to fit all nodes with padding
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

// Check if point is inside node bounding box
export function isPointInNode(x: number, y: number, node: FlowNode): boolean {
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

// Find node at point (checks in reverse order for top-most)
export function findNodeAtPoint(x: number, y: number, nodes: FlowNode[]): FlowNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    if (isPointInNode(x, y, nodes[i])) {
      return nodes[i]
    }
  }
  return null
}

// SVG path for decision diamond shape
export function getDecisionPath(cx: number, cy: number, w: number, h: number): string {
  const halfW = w / 2
  const halfH = h / 2
  return `M ${cx} ${cy - halfH} L ${cx + halfW} ${cy} L ${cx} ${cy + halfH} L ${cx - halfW} ${cy} Z`
}

// Generate unique node ID
export function generateNodeId(): string {
  return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}
