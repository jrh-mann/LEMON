import { useMemo } from 'react'
import { beautifyNodes } from '../utils/beautifyNodes'
import { getNodeSize, getDecisionPath, calculateViewBox, calculateEdgePath, getNodeFillColor, getNodeStrokeColor, wrapText } from '../utils/canvas'
import type { FlowNode, FlowEdge, WorkflowVariable, WorkflowOutput } from '../types'

/**
 * Hidden off-screen SVG renderer for "Annotated PNG" export.
 * Renders the flowchart with side panels listing input variables (left)
 * and workflow outputs (right), plus a title header.
 * Uses id="flowchartCanvasAnnotated" so exportAsPNG can target it
 * without colliding with the plain FlowchartPreview's id="flowchartCanvas".
 */

// --- Layout constants ---
const PANEL_WIDTH = 260
const PANEL_GAP = 60      // gap between panel and flowchart
const CARD_HEIGHT = 46
const CARD_GAP = 6
const CARD_PADDING_X = 12
const TITLE_HEIGHT = 60
const ACCENT_WIDTH = 3
const PANEL_PADDING_TOP = 36  // space for "INPUTS"/"OUTPUTS" eyebrow
const PANEL_PADDING_BOTTOM = 12


/**
 * Build a short subtitle string for a variable card.
 * E.g. "Enum: low, med, high" or "Number (0–100)".
 */
function variableSubtitle(v: WorkflowVariable): string {
    if (v.type === 'enum' && v.enum_values?.length) {
        const vals = v.enum_values.join(', ')
        return vals.length > 30 ? vals.slice(0, 27) + '...' : vals
    }
    if (v.type === 'number' && v.range) {
        const parts: string[] = []
        if (v.range.min !== undefined) parts.push(String(v.range.min))
        if (v.range.max !== undefined) parts.push(String(v.range.max))
        if (parts.length === 2) return `Number (${parts[0]}–${parts[1]})`
        if (parts.length === 1) return `Number (${v.range.min !== undefined ? '≥' : '≤'}${parts[0]})`
    }
    // Capitalise type name as fallback
    return v.type.charAt(0).toUpperCase() + v.type.slice(1)
}

interface FlowchartPreviewAnnotatedProps {
    nodes: FlowNode[]
    edges: FlowEdge[]
    variables: WorkflowVariable[]
    outputs: WorkflowOutput[]
    workflowName: string
    workflowDescription: string
}

export default function FlowchartPreviewAnnotated({
    nodes,
    edges,
    variables,
    outputs,
    workflowName,
    workflowDescription,
}: FlowchartPreviewAnnotatedProps) {
    // Re-layout nodes for clean export
    const layout = useMemo(() => beautifyNodes(nodes, edges), [nodes, edges])
    const chartViewBox = useMemo(() => calculateViewBox(layout.nodes), [layout.nodes])

    // Only input-sourced variables appear in the left panel
    const inputVars = useMemo(() => variables.filter(v => v.source === 'input'), [variables])

    // Compute panel heights based on item count
    const leftPanelContentH = PANEL_PADDING_TOP + inputVars.length * (CARD_HEIGHT + CARD_GAP) + PANEL_PADDING_BOTTOM
    const rightPanelContentH = PANEL_PADDING_TOP + outputs.length * (CARD_HEIGHT + CARD_GAP) + PANEL_PADDING_BOTTOM
    const panelH = Math.max(leftPanelContentH, rightPanelContentH, chartViewBox.height)

    // Total canvas dimensions
    const totalWidth =
        PANEL_WIDTH + PANEL_GAP + chartViewBox.width + PANEL_GAP + PANEL_WIDTH
    const totalHeight = TITLE_HEIGHT + Math.max(panelH, chartViewBox.height) + 40 // 40 = bottom padding

    // X positions for left panel, flowchart, right panel
    const leftPanelX = 0
    const chartOffsetX = PANEL_WIDTH + PANEL_GAP
    const rightPanelX = PANEL_WIDTH + PANEL_GAP + chartViewBox.width + PANEL_GAP

    // Y offset: title area pushes everything down
    const contentY = TITLE_HEIGHT

    // Centre flowchart vertically if shorter than panels
    const chartOffsetY = contentY + Math.max(0, (panelH - chartViewBox.height) / 2)

    if (layout.nodes.length === 0) return null

    return (
        <svg
            id="flowchartCanvasAnnotated"
            viewBox={`0 0 ${totalWidth} ${totalHeight}`}
            preserveAspectRatio="xMidYMid meet"
            style={{ position: 'absolute', left: -9999, top: -9999, width: 1, height: 1 }}
        >
            {/* Arrow marker — separate id to avoid DOM conflict with FlowchartPreview */}
            <defs>
                <marker id="arrowhead-ann" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="var(--edge)" />
                </marker>
            </defs>

            {/* ── Title area ── */}
            <text
                x={totalWidth / 2}
                y={22}
                textAnchor="middle"
                fontSize="18"
                fontWeight="bold"
                fill="var(--ink)"
            >
                {workflowName || 'Untitled Workflow'}
            </text>
            {workflowDescription && (
                <text
                    x={totalWidth / 2}
                    y={40}
                    textAnchor="middle"
                    fontSize="10"
                    fill="var(--muted)"
                >
                    {workflowDescription.length > 80
                        ? workflowDescription.slice(0, 77) + '...'
                        : workflowDescription}
                </text>
            )}
            {/* Separator line */}
            <line x1={20} y1={TITLE_HEIGHT - 8} x2={totalWidth - 20} y2={TITLE_HEIGHT - 8} stroke="var(--edge)" strokeWidth={1} />

            {/* ── Left panel: Inputs ── */}
            {inputVars.length > 0 && (
                <g transform={`translate(${leftPanelX}, ${contentY})`}>
                    {/* Panel background */}
                    <rect
                        x={0} y={0}
                        width={PANEL_WIDTH}
                        height={leftPanelContentH}
                        rx={8}
                        fill="var(--cream)"
                        stroke="var(--edge)"
                        strokeWidth={1}
                    />
                    {/* Eyebrow header */}
                    <text x={CARD_PADDING_X} y={24} fontSize="10" fontWeight="bold" fill="var(--teal)" letterSpacing="1">
                        INPUTS
                    </text>
                    {/* Variable cards */}
                    {inputVars.map((v, i) => {
                        const cardY = PANEL_PADDING_TOP + i * (CARD_HEIGHT + CARD_GAP)
                        return (
                            <g key={v.id} transform={`translate(${CARD_PADDING_X}, ${cardY})`}>
                                {/* Card background */}
                                <rect
                                    x={0} y={0}
                                    width={PANEL_WIDTH - CARD_PADDING_X * 2}
                                    height={CARD_HEIGHT}
                                    rx={4}
                                    fill="var(--paper)"
                                    stroke="var(--edge)"
                                    strokeWidth={0.5}
                                />
                                {/* Teal left accent */}
                                <rect x={0} y={4} width={ACCENT_WIDTH} height={CARD_HEIGHT - 8} rx={1.5} fill="var(--teal)" />
                                {/* Variable name */}
                                <text x={ACCENT_WIDTH + 8} y={20} fontSize="11" fontWeight="bold" fill="var(--ink)">
                                    {v.name}
                                </text>
                                {/* Type / subtitle */}
                                <text x={ACCENT_WIDTH + 8} y={36} fontSize="9" fill="var(--muted)">
                                    {variableSubtitle(v)}
                                </text>
                            </g>
                        )
                    })}
                </g>
            )}

            {/* ── Right panel: Outputs ── */}
            {outputs.length > 0 && (
                <g transform={`translate(${rightPanelX}, ${contentY})`}>
                    {/* Panel background */}
                    <rect
                        x={0} y={0}
                        width={PANEL_WIDTH}
                        height={rightPanelContentH}
                        rx={8}
                        fill="var(--cream)"
                        stroke="var(--edge)"
                        strokeWidth={1}
                    />
                    {/* Eyebrow header */}
                    <text x={CARD_PADDING_X} y={24} fontSize="10" fontWeight="bold" fill="var(--green)" letterSpacing="1">
                        OUTPUTS
                    </text>
                    {/* Output cards */}
                    {outputs.map((o, i) => {
                        const cardY = PANEL_PADDING_TOP + i * (CARD_HEIGHT + CARD_GAP)
                        return (
                            <g key={o.name} transform={`translate(${CARD_PADDING_X}, ${cardY})`}>
                                {/* Card background */}
                                <rect
                                    x={0} y={0}
                                    width={PANEL_WIDTH - CARD_PADDING_X * 2}
                                    height={CARD_HEIGHT}
                                    rx={4}
                                    fill="var(--paper)"
                                    stroke="var(--edge)"
                                    strokeWidth={0.5}
                                />
                                {/* Green left accent */}
                                <rect x={0} y={4} width={ACCENT_WIDTH} height={CARD_HEIGHT - 8} rx={1.5} fill="var(--green)" />
                                {/* Output name */}
                                <text x={ACCENT_WIDTH + 8} y={20} fontSize="11" fontWeight="bold" fill="var(--ink)">
                                    {o.name}
                                </text>
                                {/* Output type */}
                                <text x={ACCENT_WIDTH + 8} y={36} fontSize="9" fill="var(--muted)">
                                    {o.type.charAt(0).toUpperCase() + o.type.slice(1)}
                                </text>
                            </g>
                        )
                    })}
                </g>
            )}

            {/* ── Flowchart (centre) ── */}
            <g transform={`translate(${chartOffsetX - chartViewBox.x}, ${chartOffsetY - chartViewBox.y})`}>
                {/* Edges */}
                {layout.edges.map((edge, idx) => {
                    const fromNode = layout.nodes.find(n => n.id === edge.from)
                    const toNode = layout.nodes.find(n => n.id === edge.to)
                    if (!fromNode || !toNode) return null
                    const path = calculateEdgePath(fromNode, toNode)
                    return (
                        <g key={`edge-${idx}`}>
                            <path d={path} fill="none" stroke="var(--edge)" strokeWidth={1.5} markerEnd="url(#arrowhead-ann)" />
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
            </g>
        </svg>
    )
}
