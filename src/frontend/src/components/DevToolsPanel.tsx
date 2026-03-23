import { useState, useEffect, useCallback } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useChatStore } from '../stores/chatStore'
import { listTools, executeTool } from '../api/tools'
import { getWorkflow } from '../api/workflows'
import type { DevToolExecutionContext, DevToolOpenTab, ToolDefinition } from '../api/tools'
import { hydrateWorkflowDetail } from '../utils/workflowHydration'

function schemaTypeLabel(schema: { type?: string; oneOf?: unknown[]; anyOf?: unknown[] } | undefined): string {
    if (!schema) return 'string'
    if (schema.type) return schema.type
    if (schema.oneOf) return 'oneOf'
    if (schema.anyOf) return 'anyOf'
    return 'string'
}

function exampleValueForSchema(schema: { type?: string } | undefined): string {
    switch (schema?.type) {
        case 'object':
            return '{\n  \n}'
        case 'array':
            return '[\n  \n]'
        default:
            return ''
    }
}

/**
 * Execution Log Button - opens the ExecutionLogModal to view detailed logs
 */
function ExecutionLogButton({ logCount }: { logCount: number }) {
    const { setExecutionLogModalOpen } = useUIStore()

    return (
        <button
            className="devtools-log-btn"
            onClick={() => setExecutionLogModalOpen(true)}
        >
            <span>📋</span>
            <span>Execution Log</span>
            {logCount > 0 && (
                <span className="log-badge">{logCount}</span>
            )}
        </button>
    )
}

/**
 * Developer Tools Panel - shown in left sidebar when devMode is on.
 * Provides tools for debugging and testing:
 * - State Inspector: View current workflow/analysis state
 * - Message Log: View all chat messages with tool calls
 * - Tools: Browse and execute available tools
 */
export default function DevToolsPanel() {
    const { devMode } = useUIStore()
    const [activeSection, setActiveSection] = useState<'state' | 'messages' | 'tools'>('state')
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set(['workflow', 'analysis']))
    const [tools, setTools] = useState<ToolDefinition[]>([])
    const [loadingTools, setLoadingTools] = useState(false)
    const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(null)
    const [toolsError, setToolsError] = useState<string | null>(null)

    const workflowStore = useWorkflowStore()
    const chatStore = useChatStore()
    // Read messages from the active workflow's conversation
    const activeWfId = chatStore.activeWorkflowId
    const chatMessages = activeWfId ? (chatStore.conversations[activeWfId]?.messages ?? []) : []

    const loadTools = useCallback(async () => {
        setLoadingTools(true)
        setToolsError(null)
        try {
            const toolList = await listTools()
            setTools(toolList)
        } catch (err) {
            console.error('Failed to load tools:', err)
            const message = err instanceof Error ? err.message : 'Failed to load tools'
            setToolsError(message)
        } finally {
            setLoadingTools(false)
        }
    }, [])

    // Load tools when Tools tab is selected
    useEffect(() => {
        if (activeSection === 'tools' && tools.length === 0 && !loadingTools) {
            void loadTools()
        }
    }, [activeSection, loadTools, loadingTools, tools.length])

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

            {/* Execution Log Button */}
            <ExecutionLogButton logCount={workflowStore.execution.executionLogs.length} />

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
                <button
                    className={`devtools-tab ${activeSection === 'tools' ? 'active' : ''}`}
                    onClick={() => setActiveSection('tools')}
                >
                    Tools
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
                    </div>
                )}

                {activeSection === 'messages' && (
                    <div className="message-inspector">
                        {chatMessages.length === 0 ? (
                            <p className="empty-state">No messages yet</p>
                        ) : (
                            chatMessages.map((msg, idx) => (
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

                {activeSection === 'tools' && (
                    <div className="tools-inspector">
                        {loadingTools ? (
                            <p className="loading-state">Loading tools...</p>
                        ) : toolsError ? (
                            <div className="error-state">
                                <p>{toolsError}</p>
                                <button onClick={loadTools} className="retry-btn">Retry</button>
                            </div>
                        ) : tools.length === 0 ? (
                            <p className="empty-state">No tools available</p>
                        ) : (
                            <div className="tool-list">
                                {tools.map(tool => (
                                    <div
                                        key={tool.name}
                                        className={`tool-item ${selectedTool?.name === tool.name ? 'selected' : ''}`}
                                        onClick={() => setSelectedTool(tool)}
                                    >
                                        <div className="tool-item-name">{tool.name}</div>
                                        <div className="tool-item-desc">{tool.description?.slice(0, 60) || 'No description'}...</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Tool Executor Modal */}
            {selectedTool && (
                <ToolExecutorModal
                    tool={selectedTool}
                    onClose={() => setSelectedTool(null)}
                />
            )}
        </div>
    )
}

/**
 * Tool Executor Modal - displays tool schema and allows execution
 */
function ToolExecutorModal({ tool, onClose }: { tool: ToolDefinition; onClose: () => void }) {
    const [args, setArgs] = useState<Record<string, string>>({})
    const [rawMode, setRawMode] = useState(false)
    const [rawArgs, setRawArgs] = useState('{}')
    const [executing, setExecuting] = useState(false)
    const [result, setResult] = useState<unknown>(null)
    const [error, setError] = useState<string | null>(null)
    const workflowStore = useWorkflowStore()
    const chatStore = useChatStore()
    const { setCurrentWorkflow, setFlowchartSilent, setAnalysis, markSavedSnapshot } = workflowStore

    const buildExecutionContext = (): DevToolExecutionContext => {
        const currentWorkflowId = workflowStore.currentWorkflow?.id || chatStore.activeWorkflowId || undefined
        const currentWorkflow = workflowStore.currentWorkflow
        const flowchart = workflowStore.flowchart
        const analysis = workflowStore.currentAnalysis

        const openTabs: DevToolOpenTab[] = currentWorkflowId ? [{
            workflow_id: currentWorkflowId,
            title: currentWorkflow?.metadata?.name || 'New Workflow',
            node_count: flowchart.nodes.length,
            edge_count: flowchart.edges.length,
            is_active: true,
        }] : []

        return {
            current_workflow_id: currentWorkflowId,
            workflow: currentWorkflowId ? {
                nodes: flowchart.nodes,
                edges: flowchart.edges,
                variables: analysis?.variables || [],
                outputs: analysis?.outputs || [],
                output_type: currentWorkflow?.output_type || 'string',
            } : undefined,
            analysis,
            open_tabs: openTabs,
        }
    }

    const buildParsedArgs = (): Record<string, unknown> => {
        if (rawMode) {
            let parsed: unknown
            try {
                parsed = JSON.parse(rawArgs)
            } catch {
                throw new Error('Raw JSON mode requires valid JSON')
            }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                throw new Error('Raw JSON arguments must be a JSON object')
            }
            return parsed as Record<string, unknown>
        }

        const parsedArgs: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(args)) {
            if (!value.trim()) continue
            const propSchema = tool.inputSchema.properties?.[key]
            if (propSchema?.type === 'number' || propSchema?.type === 'integer') {
                const parsedNumber = Number(value)
                if (Number.isNaN(parsedNumber)) {
                    throw new Error(`${key} must be a valid number`)
                }
                parsedArgs[key] = parsedNumber
            } else if (propSchema?.type === 'boolean') {
                parsedArgs[key] = value.toLowerCase() === 'true'
            } else if (propSchema?.type === 'object' || propSchema?.type === 'array' || propSchema?.type === 'any' || propSchema?.oneOf || propSchema?.anyOf) {
                try {
                    parsedArgs[key] = JSON.parse(value)
                } catch {
                    throw new Error(`${key} must be valid JSON`)
                }
            } else {
                parsedArgs[key] = value
            }
        }
        return parsedArgs
    }

    const handleExecute = async () => {
        setExecuting(true)
        setError(null)
        setResult(null)
        try {
            const response = await executeTool(tool.name, buildParsedArgs(), buildExecutionContext())
            if (response.success) {
                setResult(response.result)
                const workflowId =
                    response.result && typeof response.result === 'object' && 'workflow_id' in response.result
                        ? String(response.result.workflow_id || '')
                        : ''
                if (workflowId && workflowStore.currentWorkflow?.id === workflowId) {
                    const fresh = await getWorkflow(workflowId)
                    const hydrated = hydrateWorkflowDetail(fresh)
                    setCurrentWorkflow(hydrated.workflow)
                    setFlowchartSilent(hydrated.flowchart)
                    setAnalysis(hydrated.analysis)
                    markSavedSnapshot()
                }
            } else {
                setResult(response.result)
                const resultError =
                    response.result && typeof response.result === 'object' && 'error' in response.result
                        ? String(response.result.error || '')
                        : ''
                setError(response.error || resultError || 'Execution failed')
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error')
        } finally {
            setExecuting(false)
        }
    }

    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            onClose()
        }
    }

    const properties = tool.inputSchema.properties || {}
    const requiredFields = tool.inputSchema.required || []

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="tool-executor-modal">
                <div className="tool-executor-header">
                    <h3>🔧 {tool.name}</h3>
                    <button className="modal-close" onClick={onClose}>×</button>
                </div>

                <div className="tool-executor-content">
                    <p className="tool-description">{tool.description || 'No description'}</p>

                    <div className="devtools-tabs">
                        <button
                            className={`devtools-tab ${!rawMode ? 'active' : ''}`}
                            onClick={() => setRawMode(false)}
                            type="button"
                        >
                            Form
                        </button>
                        <button
                            className={`devtools-tab ${rawMode ? 'active' : ''}`}
                            onClick={() => setRawMode(true)}
                            type="button"
                        >
                            Raw JSON
                        </button>
                    </div>

                    <div className="tool-args">
                        <h4>Arguments</h4>
                        {rawMode ? (
                            <div className="arg-field">
                                <label>args <span className="arg-type">(object)</span></label>
                                <p className="arg-description">Enter the full tool argument object as JSON.</p>
                                <textarea
                                    value={rawArgs}
                                    onChange={(e) => setRawArgs(e.target.value)}
                                    rows={14}
                                    spellCheck={false}
                                />
                            </div>
                        ) : Object.keys(properties).length === 0 ? (
                            <p className="no-args">No arguments required</p>
                        ) : (
                            Object.entries(properties).map(([name, schema]) => (
                                <div key={name} className="arg-field">
                                    <label>
                                        {name}
                                        {requiredFields.includes(name) && <span className="required">*</span>}
                                        <span className="arg-type">({schemaTypeLabel(schema)})</span>
                                    </label>
                                    {schema.description && (
                                        <p className="arg-description">{schema.description}</p>
                                    )}
                                    {(schema.oneOf || schema.anyOf) && (
                                        <p className="arg-description">Accepts multiple JSON shapes; use Raw JSON mode if easier.</p>
                                    )}
                                    {schema.enum ? (
                                        <select
                                            value={args[name] || ''}
                                            onChange={(e) => setArgs(prev => ({ ...prev, [name]: e.target.value }))}
                                        >
                                            <option value="">Select...</option>
                                            {schema.enum.map(opt => (
                                                <option key={opt} value={opt}>{opt}</option>
                                            ))}
                                        </select>
                                    ) : schema.type === 'object' || schema.type === 'array' || schema.type === 'any' || schema.oneOf || schema.anyOf ? (
                                        <textarea
                                            value={args[name] || ''}
                                            onChange={(e) => setArgs(prev => ({ ...prev, [name]: e.target.value }))}
                                            placeholder={exampleValueForSchema(schema)}
                                            rows={schema.type === 'array' ? 8 : 6}
                                            spellCheck={false}
                                        />
                                    ) : (
                                        <input
                                            type="text"
                                            value={args[name] || ''}
                                            onChange={(e) => setArgs(prev => ({ ...prev, [name]: e.target.value }))}
                                            placeholder={schema.type || 'Enter value...'}
                                        />
                                    )}
                                </div>
                            ))
                        )}
                    </div>

                    <button
                        className="execute-btn"
                        onClick={handleExecute}
                        disabled={executing}
                    >
                        {executing ? 'Executing...' : '▶ Execute'}
                    </button>

                    {error && (
                        <div className="tool-error">
                            <strong>Error:</strong> {error}
                        </div>
                    )}

                    {result !== null && (
                        <div className="tool-result">
                            <h4>Result</h4>
                            <pre>{JSON.stringify(result, null, 2)}</pre>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
