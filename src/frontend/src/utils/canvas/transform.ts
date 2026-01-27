import type { FlowNode, FlowNodeColor, Flowchart, DecisionCondition } from '../../types'
import { BLOCK_TYPE_MAP, BLOCK_TYPE_COLORS, NODE_SIZES } from './constants'
import { autoLayoutFlowchart } from './layout'

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
  const nodeType = BLOCK_TYPE_MAP[type] || 'process'
  const size = NODE_SIZES[nodeType] || NODE_SIZES.process

  // Convert TOP-LEFT to CENTER coordinates
  const x = (rawNode.x as number) + size.w / 2
  const y = (rawNode.y as number) + size.h / 2

  const node: FlowNode = {
    id: rawNode.id as string,
    type: nodeType,
    label: sanitizeLabel(rawNode.label as string),
    x,
    y,
    color: (rawNode.color as FlowNodeColor) || BLOCK_TYPE_COLORS[type] || 'teal',
  }

  // Preserve input_ref if present
  if (rawNode.input_ref) {
    node.input_ref = rawNode.input_ref as string
  }

  // Preserve decision condition if present (for decision nodes)
  if (rawNode.condition) {
    node.condition = rawNode.condition as DecisionCondition
  }

  // Preserve output configuration if present
  if (rawNode.output_type) {
    node.output_type = rawNode.output_type as string
  }
  if (rawNode.output_template) {
    node.output_template = rawNode.output_template as string
  }
  if (rawNode.output_value !== undefined) {
    node.output_value = rawNode.output_value
  }

  // Preserve subprocess configuration if present
  if (rawNode.subworkflow_id) {
    node.subworkflow_id = rawNode.subworkflow_id as string
  }
  if (rawNode.input_mapping) {
    node.input_mapping = rawNode.input_mapping as Record<string, string>
  }
  if (rawNode.output_variable) {
    node.output_variable = rawNode.output_variable as string
  }

  return node
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
