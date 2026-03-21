import type { Workflow, WorkflowAnalysis, WorkflowDetailResponse } from '../types'
import { autoLayoutFlowchart, transformFlowchartFromBackend } from './canvas'


export function hydrateWorkflowDetail(workflowData: WorkflowDetailResponse): {
  workflow: Workflow
  flowchart: ReturnType<typeof transformFlowchartFromBackend>
  analysis: WorkflowAnalysis
} {
  let flowchart = transformFlowchartFromBackend({
    nodes: workflowData.nodes || [],
    edges: workflowData.edges || [],
  })

  const needsLayout = flowchart.nodes.length > 1 &&
    (flowchart.nodes.every((n) => n.x === 0 && n.y === 0) ||
      new Set(flowchart.nodes.map((n) => `${n.x},${n.y}`)).size < flowchart.nodes.length / 2)

  if (needsLayout) {
    flowchart = autoLayoutFlowchart(flowchart)
  }

  const workflow: Workflow = {
    id: workflowData.id,
    output_type: workflowData.output_type,
    metadata: workflowData.metadata,
    blocks: [],
    connections: [],
  }

  const analysis: WorkflowAnalysis = {
    variables: workflowData.variables || [],
    outputs: workflowData.outputs || [],
  }

  return { workflow, flowchart, analysis }
}
