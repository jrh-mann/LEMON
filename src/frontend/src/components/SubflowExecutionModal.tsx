import { useMemo, useEffect, useState, useRef } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import type { SubflowExecutionState } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { getNodeSize, calculateEdgePath, getDecisionPath } from '../utils/canvas'
import type { FlowNode, FlowNodeType } from '../types'

// Stacked subflow visualization modals
// Each level in the stack renders as a progressively smaller overlay

// Get fill color based on node type
const getNodeFillColor = (type: FlowNodeType): string => {
    switch (type) {
        case 'start': return 'var(--teal-light)'
        case 'decision': return 'var(--amber-light)'
        case 'end': return 'var(--green-light)'
        case 'subprocess': return 'var(--rose-light)'
        case 'calculation': return 'var(--purple-light)'
        case 'process': return 'var(--paper)'
        default: return 'var(--paper)'
    }
}

// Get stroke color based on node type
const getNodeStrokeColor = (type: FlowNodeType): string => {
    switch (type) {
        case 'start': return 'var(--teal)'
        case 'decision': return 'var(--amber)'
        case 'end': return 'var(--green)'
        case 'subprocess': return 'var(--rose)'
        case 'calculation': return 'var(--purple)'
        case 'process': return 'var(--edge)'
        default: return 'var(--edge)'
    }
}

// Word wrap helper
function wrapText(text: string, maxChars: number): string[] {
    if (!text || text.length <= maxChars) return [text || '']
    const words = text.split(' ')
    const lines: string[] = []
    let currentLine = ''
    for (const word of words) {
        if ((currentLine + ' ' + word).trim().length <= maxChars) {
            currentLine = (currentLine + ' ' + word).trim()
        } else {
            if (currentLine) lines.push(currentLine)
            currentLine = word
        }
    }
    if (currentLine) lines.push(currentLine)
    return lines.length > 0 ? lines : ['']
}

// Calculate viewBox centered on a node (for tracking)
function calculateTrackedViewBox(
    node: FlowNode | undefined,
    defaultViewBox: { x: number; y: number; width: number; height: number }
): { x: number; y: number; width: number; height: number } {
    if (!node) return defaultViewBox

    // Zoom in to show ~400x300 area centered on the node
    const viewWidth = 500
    const viewHeight = 400
    return {
        x: node.x - viewWidth / 2,
        y: node.y - viewHeight / 2,
        width: viewWidth,
        height: viewHeight,
    }
}

// Calculate full viewBox from all nodes
function calculateFullViewBox(nodes: FlowNode[]): { x: number; y: number; width: number; height: number } {
    if (!nodes || nodes.length === 0) {
        return { x: 0, y: 0, width: 400, height: 300 }
    }
    const validNodes = nodes.filter(n => typeof n.x === 'number' && typeof n.y === 'number')
    if (validNodes.length === 0) {
        return { x: 0, y: 0, width: 400, height: 300 }
    }

    const padding = 80
    const minX = Math.min(...validNodes.map(n => n.x)) - padding
    const maxX = Math.max(...validNodes.map(n => n.x)) + padding
    const minY = Math.min(...validNodes.map(n => n.y)) - padding
    const maxY = Math.max(...validNodes.map(n => n.y)) + padding

    return {
        x: minX,
        y: minY,
        width: Math.max(400, maxX - minX),
        height: Math.max(300, maxY - minY),
    }
}

// Single subflow modal component
function SubflowModal({
    subflow,
    level,
}: {
    subflow: SubflowExecutionState
    level: number  // 0 = bottom, higher = on top
}) {
    const { trackExecution, setTrackExecution } = useUIStore()
    const [animatedViewBox, setAnimatedViewBox] = useState<{ x: number; y: number; width: number; height: number } | null>(null)
    const svgRef = useRef<SVGSVGElement>(null)

    const { nodes, edges, executingNodeId, executedNodeIds, subworkflowName } = subflow

    // Calculate full viewBox
    const fullViewBox = useMemo(() => calculateFullViewBox(nodes), [nodes])

    // Calculate tracked viewBox centered on executing node
    const executingNode = useMemo(() =>
        nodes.find(n => n.id === executingNodeId),
        [nodes, executingNodeId]
    )

    // Animate viewBox when tracking
    useEffect(() => {
        if (trackExecution && executingNode) {
            const tracked = calculateTrackedViewBox(executingNode, fullViewBox)
            setAnimatedViewBox(tracked)
        } else {
            setAnimatedViewBox(null)
        }
    }, [trackExecution, executingNode, fullViewBox])

    const viewBox = animatedViewBox || fullViewBox
    const viewBoxStr = `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`

    // Calculate size based on level (smaller for nested, larger offset from edge)
    const sizePercent = Math.max(50, 80 - (level * 8))
    const offsetPercent = (100 - sizePercent) / 2

    // Render a single node
    const renderNode = (node: FlowNode) => {
        const size = getNodeSize(node.type)
        const halfW = size.w / 2
        const halfH = size.h / 2
        const isExecuting = executingNodeId === node.id
        const isExecuted = executedNodeIds.includes(node.id)

        const classNames = [
            'subflow-node',
            node.type,
            isExecuting ? 'executing' : '',
            isExecuted && !isExecuting ? 'executed' : '',
        ].filter(Boolean).join(' ')

        return (
            <g key={node.id} className={classNames} transform={`translate(${node.x}, ${node.y})`}>
                {node.type === 'decision' ? (
                    <path
                        d={getDecisionPath(0, 0, size.w, size.h)}
                        fill={getNodeFillColor(node.type)}
                        stroke={getNodeStrokeColor(node.type)}
                        strokeWidth={isExecuting ? 3 : 1.5}
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
                        strokeWidth={isExecuting ? 3 : 1.5}
                    />
                )}
                <text x={0} textAnchor="middle" fontSize="11" fill="var(--ink)" style={{ pointerEvents: 'none', userSelect: 'none' }}>
                    {wrapText(node.label, 12).map((line, i, arr) => (
                        <tspan key={i} x={0} dy={i === 0 ? `${-((arr.length - 1) * 6)}px` : '12px'}>{line}</tspan>
                    ))}
                </text>
            </g>
        )
    }

    return (
        <div
            className="subflow-modal-overlay"
            style={{
                zIndex: 1000 + level,
            }}
        >
            <div
                className="subflow-modal"
                style={{
                    width: `${sizePercent}%`,
                    height: `${sizePercent}%`,
                    left: `${offsetPercent}%`,
                    top: `${offsetPercent}%`,
                }}
            >
                <div className="subflow-modal-header">
                    <div className="subflow-modal-title">
                        <span className="subflow-icon">↻</span>
                        {level > 0 && <span className="subflow-level">L{level + 1}</span>}
                        Executing: <strong>{subworkflowName}</strong>
                    </div>
                    <div className="subflow-modal-controls">
                        <label className="track-toggle" title="Track executing node">
                            <input
                                type="checkbox"
                                checked={trackExecution}
                                onChange={(e) => setTrackExecution(e.target.checked)}
                            />
                            <span className="track-label">Track</span>
                        </label>
                        <div className="subflow-modal-status">
                            <span className="pulse-dot" />
                            Running...
                        </div>
                    </div>
                </div>

                <div className="subflow-modal-canvas">
                    <svg
                        ref={svgRef}
                        viewBox={viewBoxStr}
                        preserveAspectRatio="xMidYMid meet"
                        className="subflow-svg"
                        style={{ transition: trackExecution ? 'viewBox 0.3s ease-out' : 'none' }}
                    >
                        {/* Grid pattern */}
                        <defs>
                            <pattern id={`subflow-grid-${level}`} width="20" height="20" patternUnits="userSpaceOnUse">
                                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--border)" strokeWidth="0.5" opacity="0.3" />
                            </pattern>
                        </defs>

                        <rect x={viewBox.x} y={viewBox.y} width={viewBox.width} height={viewBox.height} fill={`url(#subflow-grid-${level})`} />

                        {/* Edges */}
                        {edges.map((edge, idx) => {
                            const fromNode = nodes.find(n => n.id === edge.from)
                            const toNode = nodes.find(n => n.id === edge.to)
                            if (!fromNode || !toNode) return null

                            const path = calculateEdgePath(fromNode, toNode)
                            return (
                                <g key={`edge-${idx}`}>
                                    <path d={path} fill="none" stroke="var(--edge)" strokeWidth={1.5} markerEnd={`url(#subflow-arrowhead-${level})`} />
                                    {edge.label && (
                                        <text x={(fromNode.x + toNode.x) / 2} y={(fromNode.y + toNode.y) / 2 - 8} textAnchor="middle" fontSize="10" fill="var(--muted)">{edge.label}</text>
                                    )}
                                </g>
                            )
                        })}

                        {/* Arrow marker */}
                        <defs>
                            <marker id={`subflow-arrowhead-${level}`} markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                                <polygon points="0 0, 10 3.5, 0 7" fill="var(--edge)" />
                            </marker>
                        </defs>

                        {/* Nodes */}
                        {nodes.map(renderNode)}
                    </svg>
                </div>
            </div>
        </div>
    )
}

// Main component - renders stacked modals
export default function SubflowExecutionModal() {
    const { subflowStack } = useWorkflowStore()

    // Don't render if no subflows
    if (subflowStack.length === 0) return null

    return (
        <>
            {subflowStack.map((subflow, index) => (
                <SubflowModal
                    key={subflow.subworkflowId || index}
                    subflow={subflow}
                    level={index}
                />
            ))}
        </>
    )
}
