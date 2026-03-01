import { useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { listWorkflows } from '../api/workflows'
import { DecisionConditionEditor, EndNodeConfig, SubprocessConfig, CalculationConfigEditor } from './RightSidebar'
import type { FlowNode } from '../types'
import '../styles/NodePropertiesModal.css'

interface NodePropertiesModalProps {
    node: FlowNode
    onClose: () => void
}

export default function NodePropertiesModal({ node, onClose }: NodePropertiesModalProps) {
    const { updateNode, currentAnalysis, currentWorkflow, workflows, setWorkflows } = useWorkflowStore()
    const analysisInputs = currentAnalysis?.variables || []

    // Load workflows if needed for subprocess config
    useEffect(() => {
        if (node.type === 'subprocess' && workflows.length === 0) {
            listWorkflows()
                .then(setWorkflows)
                .catch((err) => console.error('Failed to load workflows for subprocess config:', err))
        }
    }, [node.type, workflows.length, setWorkflows])

    const handleUpdate = (updates: Partial<FlowNode>) => {
        updateNode(node.id, updates)
    }

    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) onClose()
    }

    // Determine node type label and icon color
    const typeConfig: Record<string, { label: string; color: string }> = {
        start: { label: 'Start Node', color: 'var(--teal)' },
        end: { label: 'Output Node', color: 'var(--green)' },
        process: { label: 'Process Node', color: 'var(--ink)' },
        decision: { label: 'Decision Node', color: 'var(--amber)' },
        subprocess: { label: 'Subflow Node', color: 'var(--rose)' },
        calculation: { label: 'Calculation Node', color: 'var(--purple)' },
    }

    const config = typeConfig[node.type] || { label: 'Node', color: 'var(--ink)' }

    return (
        <div className="node-props-overlay" onClick={handleOverlayClick}>
            <div className="node-props-modal">
                <div className="node-props-header">
                    <div className="node-props-title">
                        <div className="node-props-icon" style={{ borderColor: config.color, color: config.color }}>
                            {node.type.charAt(0).toUpperCase()}
                        </div>
                        <div>
                            <h2>{node.label}</h2>
                            <span className="node-props-type">{config.label}</span>
                        </div>
                    </div>
                    <button className="node-props-close" onClick={onClose}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 6L6 18M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div className="node-props-body">
                    {/* Label */}
                    <div className="form-group">
                        <label>Label</label>
                        <input
                            type="text"
                            value={node.label}
                            onChange={(e) => handleUpdate({ label: e.target.value })}
                            placeholder="Node label"
                        />
                        <p className="muted small">Display text for the node</p>
                    </div>

                    {/* Type-specific configuration using the full editors */}
                    {node.type === 'start' && (
                        <div className="node-props-section">
                            <p className="node-props-hint">Start nodes define the entry point of the workflow.</p>
                        </div>
                    )}

                    {node.type === 'end' && (
                        <EndNodeConfig
                            node={node}
                            analysisInputs={analysisInputs}
                            workflowOutputType={currentWorkflow?.output_type || 'string'}
                            onUpdate={(updates) => updateNode(node.id, updates)}
                        />
                    )}

                    {node.type === 'decision' && (
                        <DecisionConditionEditor
                            node={node}
                            analysisInputs={analysisInputs}
                            onUpdate={(updates) => updateNode(node.id, updates)}
                        />
                    )}

                    {node.type === 'subprocess' && (
                        <SubprocessConfig
                            node={node}
                            workflows={workflows}
                            analysisInputs={analysisInputs}
                            currentWorkflowId={currentWorkflow?.id}
                            onUpdate={(updates) => updateNode(node.id, updates)}
                        />
                    )}

                    {node.type === 'calculation' && (
                        <CalculationConfigEditor
                            node={node}
                            analysisInputs={analysisInputs}
                            onUpdate={(updates) => updateNode(node.id, updates)}
                        />
                    )}

                    {/* Position */}
                    <div className="node-props-section">
                        <h3>Position</h3>
                        <div className="node-props-row">
                            <div className="node-props-field">
                                <label>X</label>
                                <input
                                    type="number"
                                    value={Math.round(node.x)}
                                    onChange={(e) => handleUpdate({ x: Number(e.target.value) })}
                                />
                            </div>
                            <div className="node-props-field">
                                <label>Y</label>
                                <input
                                    type="number"
                                    value={Math.round(node.y)}
                                    onChange={(e) => handleUpdate({ y: Number(e.target.value) })}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
