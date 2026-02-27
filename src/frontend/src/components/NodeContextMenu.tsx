import { useEffect, useRef, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { generateNodeId } from '../utils/canvas'
import '../styles/ContextMenu.css'

interface NodeContextMenuProps {
    x: number
    y: number
    nodeId: string
    onClose: () => void
    onOpenProperties: (nodeId: string) => void
}

export default function NodeContextMenu({ x, y, nodeId, onClose, onOpenProperties }: NodeContextMenuProps) {
    const menuRef = useRef<HTMLDivElement>(null)
    const { flowchart, addNode, deleteNode, startConnect, pushHistory } = useWorkflowStore()

    const node = flowchart.nodes.find(n => n.id === nodeId)

    // Close on click outside
    useEffect(() => {
        const handleClick = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                onClose()
            }
        }
        const handleEsc = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose()
        }
        document.addEventListener('mousedown', handleClick)
        document.addEventListener('keydown', handleEsc)
        return () => {
            document.removeEventListener('mousedown', handleClick)
            document.removeEventListener('keydown', handleEsc)
        }
    }, [onClose])

    // Duplicate node
    const handleDuplicate = useCallback(() => {
        if (!node) return
        addNode({
            id: generateNodeId(),
            type: node.type,
            label: `${node.label} (copy)`,
            x: node.x + 120,
            y: node.y + 80,
            color: node.color,
            condition: node.condition,
            subworkflow_id: node.subworkflow_id,
            input_mapping: node.input_mapping ? { ...node.input_mapping } : undefined,
            output_variable: node.output_variable,
            output_type: node.output_type,
            output_template: node.output_template,
            calculation: node.calculation ? { ...node.calculation } : undefined,
        })
        pushHistory()
        onClose()
    }, [node, addNode, pushHistory, onClose])

    // Connect
    const handleConnect = useCallback(() => {
        startConnect(nodeId)
        onClose()
    }, [startConnect, nodeId, onClose])

    // Delete
    const handleDelete = useCallback(() => {
        deleteNode(nodeId)
        pushHistory()
        onClose()
    }, [deleteNode, nodeId, pushHistory, onClose])

    // Properties
    const handleProperties = useCallback(() => {
        onOpenProperties(nodeId)
    }, [onOpenProperties, nodeId])

    if (!node) return null

    // Adjust position to keep menu in viewport
    const adjustedX = Math.min(x, window.innerWidth - 240)
    const adjustedY = Math.min(y, window.innerHeight - 280)

    return (
        <div
            ref={menuRef}
            className="context-menu"
            style={{ left: adjustedX, top: adjustedY }}
        >
            <div className="context-menu-header">
                <span className="context-menu-node-label">{node.label}</span>
                <span className="context-menu-node-type">{node.type}</span>
            </div>
            <div className="context-menu-divider" />

            <button className="context-menu-item" onClick={handleProperties}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
                </svg>
                Properties
            </button>

            <button className="context-menu-item" onClick={handleConnect}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
                Connect
            </button>

            <button className="context-menu-item" onClick={handleDuplicate}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                </svg>
                Duplicate
            </button>

            <div className="context-menu-divider" />

            <button className="context-menu-item danger" onClick={handleDelete}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                </svg>
                Delete
            </button>
        </div>
    )
}
