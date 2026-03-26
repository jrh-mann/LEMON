import { useMemo } from 'react'
import { calculateEdgePath, calculateViewBox, getDecisionPath, getNodeColor, getNodeSize, resolveDecisionEdgeLabel } from '../utils/canvas'
import { getNodeFillColor, getNodeStrokeColor, DEFAULT_LABELS } from '../utils/canvas/nodeStyles'
import { wrapText } from '../utils/canvas/textWrap'
import type { FlowEdge, FlowNode } from '../types'

interface Props {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export default function ReadOnlyWorkflowCanvas({ nodes, edges }: Props) {
  const viewBox = useMemo(() => calculateViewBox(nodes), [nodes])
  const viewBoxStr = `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`

  return (
    <div className="canvas-panel" style={{ minHeight: 420 }}>
      <svg className="flow-svg" viewBox={viewBoxStr} preserveAspectRatio="xMidYMid meet">
        <defs>
          <marker id="arrowhead-readonly-preview" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill="rgba(255,255,255,0.45)" />
          </marker>
        </defs>

        {edges.map(edge => {
          const from = nodes.find(n => n.id === edge.from)
          const to = nodes.find(n => n.id === edge.to)
          if (!from || !to) return null
          const path = from.type === 'decision'
            ? getDecisionPath(from.x, from.y, to.x, to.y, edge.label)
            : calculateEdgePath(from.x, from.y, to.x, to.y)
          const label = resolveDecisionEdgeLabel(edge.label)
          return (
            <g key={edge.id || `${edge.from}-${edge.to}`}>
              <path d={path} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth={2} markerEnd="url(#arrowhead-readonly-preview)" />
              {label && (
                <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 10} textAnchor="middle" fill="rgba(255,255,255,0.72)" fontSize={14}>
                  {label}
                </text>
              )}
            </g>
          )
        })}

        {nodes.map(node => {
          const size = getNodeSize(node.type)
          const fill = getNodeFillColor(node.type, node.color || getNodeColor(node.type))
          const stroke = getNodeStrokeColor(node.type, node.color || getNodeColor(node.type))
          const lines = wrapText(node.label || DEFAULT_LABELS[node.type] || node.type, size.w - 24, 16)
          return (
            <g key={node.id} transform={`translate(${node.x - size.w / 2}, ${node.y - size.h / 2})`}>
              {node.type === 'decision' ? (
                <polygon
                  points={`${size.w / 2},0 ${size.w},${size.h / 2} ${size.w / 2},${size.h} 0,${size.h / 2}`}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={2.5}
                />
              ) : (
                <rect width={size.w} height={size.h} rx={20} fill={fill} stroke={stroke} strokeWidth={2.5} />
              )}
              {lines.map((line, idx) => (
                <text
                  key={`${node.id}-${idx}`}
                  x={size.w / 2}
                  y={size.h / 2 - ((lines.length - 1) * 9) + idx * 18}
                  textAnchor="middle"
                  fill="white"
                  fontSize={14}
                  fontWeight={600}
                >
                  {line}
                </text>
              ))}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
