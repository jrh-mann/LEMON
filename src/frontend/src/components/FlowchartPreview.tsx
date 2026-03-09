import { useMemo } from 'react'
import { beautifyNodes } from '../utils/beautifyNodes'
import { getNodeSize, getDecisionPath, calculateViewBox, calculateEdgePath, getNodeFillColor, getNodeStrokeColor, wrapText } from '../utils/canvas'
import type { FlowNode, FlowEdge } from '../types'

/**
 * Hidden off-screen SVG renderer for PNG export.
 * Renders a static flowchart with id="flowchartCanvas" so exportAsPNG()
 * can find it via document.getElementById. Positioned off-screen
 * (not display:none) so the SVG is measurable for cloneNode/viewBox.
 */

interface FlowchartPreviewProps {
    nodes: FlowNode[]
    edges: FlowEdge[]
}

export default function FlowchartPreview({ nodes, edges }: FlowchartPreviewProps) {
    // Re-layout nodes for a clean export regardless of editor state
    const layout = useMemo(() => beautifyNodes(nodes, edges), [nodes, edges])
    const viewBox = useMemo(() => calculateViewBox(layout.nodes), [layout.nodes])
    const viewBoxStr = `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`

    if (layout.nodes.length === 0) return null

    return (
        <svg
            id="flowchartCanvas"
            viewBox={viewBoxStr}
            preserveAspectRatio="xMidYMid meet"
            style={{ position: 'absolute', left: -9999, top: -9999, width: 1, height: 1 }}
        >
            {/* Arrow marker — id="arrowhead" matches what exportAsPNG expects */}
            <defs>
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="var(--edge)" />
                </marker>
            </defs>

            {/* Edges */}
            {layout.edges.map((edge, idx) => {
                const fromNode = layout.nodes.find(n => n.id === edge.from)
                const toNode = layout.nodes.find(n => n.id === edge.to)
                if (!fromNode || !toNode) return null
                const path = calculateEdgePath(fromNode, toNode)
                return (
                    <g key={`edge-${idx}`}>
                        <path d={path} fill="none" stroke="var(--edge)" strokeWidth={1.5} markerEnd="url(#arrowhead)" />
                        {edge.label && (
                            <text
                                x={(fromNode.x + toNode.x) / 2}
                                y={(fromNode.y + toNode.y) / 2 - 8}
                                textAnchor="middle"
                                fontSize="10"
                                fill="var(--muted)"
                            >
                                {edge.label}
                            </text>
                        )}
                    </g>
                )
            })}

            {/* Nodes */}
            {layout.nodes.map(node => {
                const size = getNodeSize(node.type)
                const halfW = size.w / 2
                const halfH = size.h / 2
                return (
                    <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
                        {node.type === 'decision' ? (
                            <path
                                d={getDecisionPath(0, 0, size.w, size.h)}
                                fill={getNodeFillColor(node.type)}
                                stroke={getNodeStrokeColor(node.type)}
                                strokeWidth={1.5}
                            />
                        ) : (
                            <rect
                                x={-halfW}
                                y={-halfH}
                                width={size.w}
                                height={size.h}
                                rx={node.type === 'start' || node.type === 'end' ? 24 : 6}
                                fill={getNodeFillColor(node.type)}
                                stroke={getNodeStrokeColor(node.type)}
                                strokeWidth={1.5}
                            />
                        )}
                        <text x={0} textAnchor="middle" fontSize="11" fill="var(--ink)" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                            {wrapText(node.label, 12).map((line, i, arr) => (
                                <tspan key={i} x={0} dy={i === 0 ? `${-((arr.length - 1) * 6)}px` : '12px'}>{line}</tspan>
                            ))}
                        </text>
                    </g>
                )
            })}
        </svg>
    )
}
