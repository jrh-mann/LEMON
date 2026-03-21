// Node visual style helpers — default labels, fill colors, stroke colors.
// Fill and stroke are re-exported from nodeColors.ts for a unified import path.

import type { FlowNodeType } from '../../types'
export { getNodeFillColor, getNodeStrokeColor } from './nodeColors'

/** Default display label for each node type (shown when no label is set). */
export const DEFAULT_LABELS: Record<FlowNodeType, string> = {
  start: 'Input',
  end: 'Result',
  process: 'Process',
  decision: 'Condition?',
  subprocess: 'Workflow',
  calculation: 'Calculate',
}
