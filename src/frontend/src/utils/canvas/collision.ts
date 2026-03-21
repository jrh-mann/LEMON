// Collision detection for dragging nodes on the canvas.
// Pure functions — no React dependencies.

import type { FlowNode, FlowNodeType } from '../../types'
import { getNodeSize } from './geometry'

/**
 * Check whether placing a node at (x, y) would overlap any other node.
 * Uses axis-aligned bounding boxes with an extra `padding` gap.
 */
export function hasCollision(
  nodes: FlowNode[],
  nodeId: string,
  x: number,
  y: number,
  nodeType: FlowNodeType,
  padding: number = 20,
): boolean {
  const draggingSize = getNodeSize(nodeType)

  for (const other of nodes) {
    if (other.id === nodeId) continue

    const otherSize = getNodeSize(other.type)
    const minDistX = draggingSize.w / 2 + otherSize.w / 2 + padding
    const minDistY = draggingSize.h / 2 + otherSize.h / 2 + padding

    if (Math.abs(x - other.x) < minDistX && Math.abs(y - other.y) < minDistY) {
      return true
    }
  }
  return false
}

/**
 * Find a valid position for `nodeId` that doesn't collide with other nodes.
 * Attempts the full move first; if blocked, slides along each axis
 * independently using a binary search to find the closest free position.
 */
export function resolveCollision(
  nodes: FlowNode[],
  nodeId: string,
  newX: number,
  newY: number,
): { x: number; y: number } {
  const draggingNode = nodes.find(n => n.id === nodeId)
  if (!draggingNode) return { x: newX, y: newY }

  // If no collision at target, allow it
  if (!hasCollision(nodes, nodeId, newX, newY, draggingNode.type)) {
    return { x: newX, y: newY }
  }

  // There's a collision — try sliding along each axis independently
  const startX = draggingNode.x
  const startY = draggingNode.y

  // Try X movement only (horizontal slide)
  let finalX = startX
  if (!hasCollision(nodes, nodeId, newX, startY, draggingNode.type)) {
    finalX = newX
  } else {
    // Binary search for X
    let lo = 0, hi = 1
    const dx = newX - startX
    for (let i = 0; i < 10; i++) {
      const mid = (lo + hi) / 2
      const testX = startX + dx * mid
      if (hasCollision(nodes, nodeId, testX, startY, draggingNode.type)) {
        hi = mid
      } else {
        lo = mid
      }
    }
    finalX = startX + dx * lo
  }

  // Try Y movement only (vertical slide)
  let finalY = startY
  if (!hasCollision(nodes, nodeId, finalX, newY, draggingNode.type)) {
    finalY = newY
  } else {
    // Binary search for Y
    let lo = 0, hi = 1
    const dy = newY - startY
    for (let i = 0; i < 10; i++) {
      const mid = (lo + hi) / 2
      const testY = startY + dy * mid
      if (hasCollision(nodes, nodeId, finalX, testY, draggingNode.type)) {
        hi = mid
      } else {
        lo = mid
      }
    }
    finalY = startY + dy * lo
  }

  return { x: finalX, y: finalY }
}
