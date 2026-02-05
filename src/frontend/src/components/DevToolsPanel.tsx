import { useState } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useChatStore } from '../stores/chatStore'

/**
 * Developer Tools Panel - shown in left sidebar when devMode is on.
 * Provides tools for debugging and testing:
 * - State Inspector: View current workflow/analysis state
 * - Message Log: View all chat messages with tool calls
 */
export default function DevToolsPanel() {
    const { devMode } = useUIStore()
    const [activeSection, setActiveSection] = useState<'state' | 'messages'>('state')
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set(['workflow', 'analysis']))

    const workflowStore = useWorkflowStore()
    const chatStore = useChatStore()

    if (!devMode) return null

    const toggleExpand = (key: string) => {
        setExpandedKeys(prev => {
            const next = new Set(prev)
            if (next.has(key)) {
                next.delete(key)
            } else {
                next.add(key)
            }
            return next
        })
    }

    const formatValue = (value: unknown): string => {
        if (value === null) return 'null'
        if (value === undefined) return 'undefined'
        if (typeof value === 'string') return `"${value.slice(0, 100)}${value.length > 100 ? '...' : ''}"`
        if (typeof value === 'number' || typeof value === 'boolean') return String(value)
        if (Array.isArray(value)) return `Array(${value.length})`
        if (typeof value === 'object') return `Object(${Object.keys(value).length})`
        return String(value)
    }

    const renderStateSection = (label: string, key: string, data: unknown) => {
        const isExpanded = expandedKeys.has(key)
        return (
            <div className="state-section" key={key}>
                <div
                    className="state-header"
                    onClick={() => toggleExpand(key)}
                >
                    <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                    <span className="state-label">{label}</span>
                    <span className="state-preview">{formatValue(data)}</span>
                </div>
                {isExpanded && (
                    <pre className="state-content">
                        {JSON.stringify(data, null, 2)}
                    </pre>
                )}
            </div>
        )
    }

    return (
        <div className="devtools-panel">
            <div className="devtools-header">
                <span className="devtools-badge">🔧 DEV</span>
            </div>

            <div className="devtools-tabs">
                <button
                    className={`devtools-tab ${activeSection === 'state' ? 'active' : ''}`}
                    onClick={() => setActiveSection('state')}
                >
                    State
                </button>
                <button
                    className={`devtools-tab ${activeSection === 'messages' ? 'active' : ''}`}
                    onClick={() => setActiveSection('messages')}
                >
                    Messages
                </button>
            </div>

            <div className="devtools-content">
                {activeSection === 'state' && (
                    <div className="state-inspector">
                        {renderStateSection('Current Workflow', 'workflow', {
                            id: workflowStore.currentWorkflow?.id,
                            name: workflowStore.currentWorkflow?.metadata?.name,
                            nodeCount: workflowStore.flowchart.nodes.length,
                            edgeCount: workflowStore.flowchart.edges.length,
                        })}
                        {renderStateSection('Analysis', 'analysis', {
                            variables: workflowStore.currentAnalysis?.variables?.length || 0,
                            outputs: workflowStore.currentAnalysis?.outputs?.length || 0,
                        })}
                        {renderStateSection('Variables', 'variables', workflowStore.currentAnalysis?.variables)}
                        {renderStateSection('Execution', 'execution', workflowStore.execution)}
                        {renderStateSection('Tabs', 'tabs', workflowStore.tabs.map(t => ({
                            id: t.id.slice(0, 8),
                            title: t.title,
                            nodes: t.flowchart.nodes.length,
                        })))}
                    </div>
                )}

                {activeSection === 'messages' && (
                    <div className="message-inspector">
                        {chatStore.messages.length === 0 ? (
                            <p className="empty-state">No messages yet</p>
                        ) : (
                            chatStore.messages.map((msg, idx) => (
                                <div key={msg.id} className="message-item">
                                    <div className="message-meta">
                                        <span className={`role-badge role-${msg.role}`}>{msg.role}</span>
                                        <span className="msg-index">#{idx + 1}</span>
                                    </div>
                                    <div className="message-preview">
                                        {msg.content.slice(0, 80)}{msg.content.length > 80 ? '...' : ''}
                                    </div>
                                    {msg.tool_calls.length > 0 && (
                                        <div className="tool-count">
                                            🔧 {msg.tool_calls.length} tool{msg.tool_calls.length !== 1 ? 's' : ''}
                                        </div>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
