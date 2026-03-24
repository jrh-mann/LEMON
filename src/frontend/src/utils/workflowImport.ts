import type {
  FlowEdge,
  FlowNode,
  FlowNodeType,
  Workflow,
  WorkflowAnalysis,
  WorkflowMetadata,
} from '../types'

export interface ImportedWorkflowData {
  workflow: Workflow
  flowchart: {
    nodes: FlowNode[]
    edges: FlowEdge[]
  }
  analysis: WorkflowAnalysis
}

function createImportedMetadata(metadata: Partial<WorkflowMetadata> | undefined): WorkflowMetadata {
  const now = new Date().toISOString()
  return {
    name: metadata?.name || 'Imported Workflow',
    description: metadata?.description || '',
    domain: metadata?.domain,
    tags: Array.isArray(metadata?.tags) ? metadata.tags : [],
    creator_id: metadata?.creator_id,
    created_at: metadata?.created_at || now,
    updated_at: metadata?.updated_at || now,
    confidence: metadata?.confidence || 'none',
    is_validated: Boolean(metadata?.is_validated),
  }
}

export function parseImportedWorkflowJson(jsonString: string): ImportedWorkflowData {
  const parsed = JSON.parse(jsonString) as Record<string, unknown>

  if (!parsed.flowchart || typeof parsed.flowchart !== 'object') {
    throw new Error('Invalid format: JSON must have a "flowchart" object')
  }

  const flowchart = parsed.flowchart as Record<string, unknown>
  if (!Array.isArray(flowchart.nodes)) {
    throw new Error('Invalid format: JSON must have a "flowchart.nodes" array')
  }

  const nodes = flowchart.nodes as unknown[]
  const edges = Array.isArray(flowchart.edges) ? flowchart.edges as Array<Record<string, unknown>> : []
  const variables = Array.isArray(parsed.variables)
    ? parsed.variables
    : Array.isArray(flowchart.variables)
      ? flowchart.variables
      : []
  const outputs = Array.isArray(parsed.outputs)
    ? parsed.outputs
    : Array.isArray(flowchart.outputs)
      ? flowchart.outputs
      : []

  const validatedNodes: FlowNode[] = nodes.map((n: unknown, i: number) => {
    const node = n as Record<string, unknown>
    return {
      id: (node.id as string) || `node_${i}`,
      type: (node.type as FlowNodeType) || 'process',
      label: (node.label as string) || `Node ${i + 1}`,
      x: typeof node.x === 'number' ? node.x : 400,
      y: typeof node.y === 'number' ? node.y : 100 + i * 120,
      color: (node.color as FlowNode['color']) || 'teal',
      condition: node.condition as FlowNode['condition'],
      subworkflow_id: node.subworkflow_id as string | undefined,
      input_mapping: node.input_mapping as Record<string, string> | undefined,
      output_variable: node.output_variable as string | undefined,
      output_type: node.output_type as string | undefined,
      output_template: node.output_template as string | undefined,
      output_value: node.output_value,
      calculation: node.calculation as FlowNode['calculation'],
    }
  })

  const validatedEdges: FlowEdge[] = edges.map((edge, index) => ({
    id: edge.id ? String(edge.id) : `edge_${index}`,
    from: String(edge.from || ''),
    to: String(edge.to || ''),
    label: typeof edge.label === 'string' ? edge.label : '',
  }))

  const metadata = createImportedMetadata(parsed.metadata as Partial<WorkflowMetadata> | undefined)
  const workflow: Workflow = {
    id: '',
    output_type: typeof parsed.output_type === 'string' ? parsed.output_type : 'string',
    metadata,
  }

  return {
    workflow,
    flowchart: {
      nodes: validatedNodes,
      edges: validatedEdges,
    },
    analysis: {
      variables: variables as WorkflowAnalysis['variables'],
      outputs: outputs as WorkflowAnalysis['outputs'],
    },
  }
}
