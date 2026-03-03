import type { FlowNodeType, FlowNodeColor } from '../../types'

// Backend BlockType to Frontend FlowNodeType mapping
export const BLOCK_TYPE_MAP: Record<string, FlowNodeType> = {
  input: 'process',
  output: 'end',
  workflow_ref: 'subprocess',
  // These already match
  start: 'start',
  end: 'end',
  process: 'process',
  decision: 'decision',
  subprocess: 'subprocess',
  calculation: 'calculation',
}

// Default color for each block type from backend
export const BLOCK_TYPE_COLORS: Record<string, FlowNodeColor> = {
  input: 'teal',
  output: 'green',
  workflow_ref: 'sky',
  start: 'teal',
  end: 'green',
  process: 'teal',
  decision: 'amber',
  subprocess: 'sky',
  calculation: 'purple',
}

// Node size configuration (width and height for each type)
export const NODE_SIZES: Record<FlowNodeType, { w: number; h: number }> = {
  start: { w: 160, h: 64 },
  end: { w: 160, h: 64 },
  process: { w: 180, h: 80 },
  decision: { w: 160, h: 100 },
  subprocess: { w: 200, h: 90 },
  calculation: { w: 180, h: 80 },
}

// Color hex values
export const COLOR_MAP: Record<FlowNodeColor, string> = {
  teal: '#1f6e68',
  amber: '#c98a2c',
  green: '#3e7c4d',
  slate: '#4b5563',
  rose: '#b4533d',
  sky: '#2b6cb0',
  purple: '#7c3aed',
}

// Edge routing thresholds
export const EDGE_THRESHOLDS = {
  // Minimum horizontal offset to consider target "to the side" vs "below"
  HORIZONTAL_OFFSET: 30,
  // Ratio for determining if movement is more vertical than horizontal
  VERTICAL_RATIO: 0.5,
  // Minimum segment length before turning in orthogonal paths
  MIN_SEGMENT: 25,
  // Threshold for considering points "aligned" (straight line)
  ALIGNMENT_THRESHOLD: 5,
}
