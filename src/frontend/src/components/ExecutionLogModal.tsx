import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import type { ExecutionLogEntry, DecisionLogEntry, CalculationLogEntry, SubflowLogEntry, SubflowStepLogEntry, SubflowCompleteLogEntry, StartLogEntry, EndLogEntry } from '../types'

/**
 * Modal component for displaying detailed execution logs.
 * Shows decision evaluations, calculation results, and other execution details.
 * Only visible when devMode is enabled.
 */
export function ExecutionLogModal() {
    const { execution, clearExecutionLogs } = useWorkflowStore()
    const { executionLogModalOpen, setExecutionLogModalOpen, devMode } = useUIStore()

    // Don't render if not in dev mode or modal not open
    if (!devMode || !executionLogModalOpen) {
        return null
    }

    const logs = execution.executionLogs

    const handleClose = () => {
        setExecutionLogModalOpen(false)
    }

    const handleClear = () => {
        clearExecutionLogs()
    }

    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            handleClose()
        }
    }

    const formatValue = (value: unknown): string => {
        if (value === null) return 'null'
        if (value === undefined) return 'undefined'
        if (typeof value === 'boolean') return value ? 'true' : 'false'
        if (typeof value === 'number') return String(value)
        if (typeof value === 'string') return `"${value}"`
        return JSON.stringify(value)
    }

    const renderDecisionLog = (log: DecisionLogEntry) => (
        <div className="execution-log-entry decision">
            <div className="log-header">
                <span className="log-icon">🔀</span>
                <span className="log-type">Decision</span>
                <span className="log-node">{log.node_label}</span>
            </div>
            <div className="log-details">
                <div className="log-row">
                    <span className="log-label">Condition:</span>
                    <span className="log-value code">{log.condition_expression}</span>
                </div>
                <div className="log-row">
                    <span className="log-label">Input:</span>
                    <span className="log-value">
                        {log.input_name} = {formatValue(log.input_value)}
                    </span>
                </div>
                <div className="log-row">
                    <span className="log-label">Compare:</span>
                    <span className="log-value">
                        {log.comparator} {formatValue(log.compare_value)}
                        {log.compare_value2 !== undefined && ` to ${formatValue(log.compare_value2)}`}
                    </span>
                </div>
                <div className="log-row result">
                    <span className="log-label">Result:</span>
                    <span className={`log-value branch-${log.branch_taken}`}>
                        {log.result ? '✓ TRUE' : '✗ FALSE'} → {log.branch_taken} branch
                    </span>
                </div>
            </div>
        </div>
    )

    const renderCalculationLog = (log: CalculationLogEntry) => (
        <div className="execution-log-entry calculation">
            <div className="log-header">
                <span className="log-icon">🧮</span>
                <span className="log-type">Calculation</span>
                <span className="log-node">{log.node_label}</span>
            </div>
            <div className="log-details">
                <div className="log-row">
                    <span className="log-label">Formula:</span>
                    <span className="log-value code">{log.formula}</span>
                </div>
                <div className="log-row">
                    <span className="log-label">Operator:</span>
                    <span className="log-value">{log.operator}</span>
                </div>
                <div className="log-row">
                    <span className="log-label">Operands:</span>
                    <span className="log-value">
                        {log.operands.map((op, i) => (
                            <span key={i} className="operand">
                                {op.name}={op.value}
                                {i < log.operands.length - 1 && ', '}
                            </span>
                        ))}
                    </span>
                </div>
                <div className="log-row result">
                    <span className="log-label">Result:</span>
                    <span className="log-value result-value">
                        {log.output_name} = {log.result}
                    </span>
                </div>
            </div>
        </div>
    )

    const renderStartLog = (log: StartLogEntry) => (
        <div className="execution-log-entry start">
            <div className="log-header">
                <span className="log-icon">▶</span>
                <span className="log-type">Start</span>
                <span className="log-node">{log.node_label}</span>
            </div>
            {log.inputs && Object.keys(log.inputs).length > 0 && (
                <div className="log-details">
                    <div className="log-row">
                        <span className="log-label">Inputs:</span>
                        <span className="log-value">
                            {Object.entries(log.inputs).map(([key, val], i) => (
                                <span key={key} className="operand">
                                    {key}={formatValue(val)}
                                    {i < Object.keys(log.inputs!).length - 1 && ', '}
                                </span>
                            ))}
                        </span>
                    </div>
                </div>
            )}
        </div>
    )

    const renderEndLog = (log: EndLogEntry) => (
        <div className="execution-log-entry end">
            <div className="log-header">
                <span className="log-icon">🏁</span>
                <span className="log-type">End</span>
                <span className="log-node">{log.node_label}</span>
            </div>
            <div className="log-details">
                <div className="log-row result">
                    <span className="log-label">Output:</span>
                    <span className="log-value result-value">
                        {formatValue(log.output_value)}
                    </span>
                </div>
            </div>
        </div>
    )

    const renderSubflowLog = (log: SubflowLogEntry) => (
        <div className="execution-log-entry subflow">
            <div className="log-header">
                <span className="log-icon">📦</span>
                <span className="log-type">Entering Subflow</span>
                <span className="log-node">{log.subworkflow_name}</span>
            </div>
        </div>
    )

    const renderSubflowStepLog = (log: SubflowStepLogEntry) => (
        <div className="execution-log-entry subflow-step">
            <div className="log-header">
                <span className="log-icon">↳</span>
                <span className="log-type">{log.node_type}</span>
                <span className="log-node">{log.node_label}</span>
            </div>
        </div>
    )

    const renderSubflowCompleteLog = (log: SubflowCompleteLogEntry) => (
        <div className="execution-log-entry subflow-complete">
            <div className="log-header">
                <span className="log-icon">{log.success ? '✓' : '✗'}</span>
                <span className="log-type">Exiting Subflow</span>
                <span className="log-node">{log.subworkflow_name}</span>
            </div>
            {log.error && (
                <div className="log-details">
                    <div className="log-row error">
                        <span className="log-label">Error:</span>
                        <span className="log-value">{log.error}</span>
                    </div>
                </div>
            )}
        </div>
    )

    const renderLogEntry = (log: ExecutionLogEntry) => {
        // Prepare content
        let content: React.ReactNode = null;

        switch (log.log_type) {
            case 'decision':
                content = renderDecisionLog(log as DecisionLogEntry)
                break
            case 'calculation':
                content = renderCalculationLog(log as CalculationLogEntry)
                break
            case 'start':
                content = renderStartLog(log as StartLogEntry)
                break
            case 'end':
                content = renderEndLog(log as EndLogEntry)
                break
            case 'subflow_start':
                content = renderSubflowLog(log as SubflowLogEntry)
                break
            case 'subflow_step':
                content = renderSubflowStepLog(log as SubflowStepLogEntry)
                break
            case 'subflow_complete':
                content = renderSubflowCompleteLog(log as SubflowCompleteLogEntry)
                break
            default:
                content = (
                    <div className="execution-log-entry generic">
                        <div className="log-header">
                            <span className="log-type">{log.log_type}</span>
                            <span className="log-node">{log.node_label}</span>
                        </div>
                    </div>
                )
        }

        // Apply visual indentation based on nesting stack
        // Wraps the content in .subflow-indented for each level of depth
        const stack = log.subworkflow_stack ||
            (log.subworkflow_id && log.log_type !== 'subflow_start' && log.log_type !== 'subflow_complete' ? [log.subworkflow_id] : []);

        let result = content;

        if (stack && stack.length > 0) {
            for (let i = 0; i < stack.length; i++) {
                result = (
                    <div className="execution-log-entry subflow-indented">
                        {result}
                    </div>
                )
            }
        }

        return result;

        return content
    }

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="execution-log-modal">
                <div className="execution-log-header">
                    <h3>📋 Execution Log</h3>
                    <div className="header-actions">
                        <button className="clear-btn" onClick={handleClear} disabled={logs.length === 0}>
                            Clear
                        </button>
                        <button className="modal-close" onClick={handleClose}>×</button>
                    </div>
                </div>

                <div className="execution-log-content">
                    {logs.length === 0 ? (
                        <div className="empty-logs">
                            <p>No execution logs yet.</p>
                            <p className="hint">Run a workflow to see detailed execution information here.</p>
                        </div>
                    ) : (
                        <div className="log-list">
                            {logs.map((log) => (
                                <div key={log.id}>
                                    {renderLogEntry(log)}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="execution-log-footer">
                    <span className="log-count">{logs.length} log entries</span>
                </div>
            </div>
        </div>
    )
}
