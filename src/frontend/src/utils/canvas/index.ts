// Canvas utilities - re-exports from all modules

// Constants
export { NODE_SIZES, COLOR_MAP, BLOCK_TYPE_MAP, BLOCK_TYPE_COLORS, EDGE_THRESHOLDS } from './constants'

// Geometry - node sizes, connection points, hit testing
export {
  getNodeSize,
  getNodeColor,
  getConnectionPoint,
  getDecisionConnectionPoint,
  calculateViewBox,
  isPointInNode,
  findNodeAtPoint,
  getDecisionPath,
  generateNodeId,
} from './geometry'
export type { Direction, DecisionPosition, Point } from './geometry'

// Edges - path calculation
export { calculateEdgePath } from './edges'

// Transform - backend to frontend data conversion
export { transformFlowchartFromBackend, transformNodeFromBackend } from './transform'

// Layout - auto-layout algorithm
export { autoLayoutFlowchart } from './layout'
