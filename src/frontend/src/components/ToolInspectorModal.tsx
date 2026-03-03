import { useUIStore } from '../stores/uiStore'

/**
 * Modal that displays detailed tool call information for debugging.
 * Shows the exact parameters passed to the tool and the result returned.
 * Only accessible when dev mode is enabled.
 */
export default function ToolInspectorModal() {
    const { selectedToolCall, setSelectedToolCall, devMode } = useUIStore()

    // Don't render if no tool selected or dev mode is off
    if (!selectedToolCall || !devMode) return null

    const handleClose = () => {
        setSelectedToolCall(null)
    }

    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            handleClose()
        }
    }

    const formatJSON = (data: unknown): string => {
        try {
            return JSON.stringify(data, null, 2)
        } catch {
            return String(data)
        }
    }

    const copyToClipboard = (text: string, label: string) => {
        navigator.clipboard.writeText(text).then(() => {
            // Could add a toast notification here
            console.log(`Copied ${label} to clipboard`)
        })
    }

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="tool-inspector-modal">
                <div className="tool-inspector-header">
                    <h3>🔧 Tool Inspector</h3>
                    <button className="modal-close" onClick={handleClose}>×</button>
                </div>

                <div className="tool-inspector-content">
                    {/* Tool Name */}
                    <div className="inspector-section">
                        <div className="inspector-label">Tool Name</div>
                        <div className="inspector-value tool-name-display">
                            {selectedToolCall.tool}
                        </div>
                    </div>

                    {/* Arguments */}
                    <div className="inspector-section">
                        <div className="inspector-label-row">
                            <span className="inspector-label">Arguments</span>
                            <button
                                className="copy-btn"
                                onClick={() => copyToClipboard(
                                    formatJSON(selectedToolCall.arguments),
                                    'arguments'
                                )}
                                title="Copy arguments"
                            >
                                📋 Copy
                            </button>
                        </div>
                        <pre className="inspector-code">
                            {selectedToolCall.arguments
                                ? formatJSON(selectedToolCall.arguments)
                                : '(no arguments)'}
                        </pre>
                    </div>

                    {/* Result */}
                    <div className="inspector-section">
                        <div className="inspector-label-row">
                            <span className="inspector-label">Result</span>
                            <button
                                className="copy-btn"
                                onClick={() => copyToClipboard(
                                    formatJSON(selectedToolCall.result),
                                    'result'
                                )}
                                title="Copy result"
                            >
                                📋 Copy
                            </button>
                        </div>
                        <pre className="inspector-code result">
                            {selectedToolCall.result
                                ? formatJSON(selectedToolCall.result)
                                : '(no result recorded)'}
                        </pre>
                    </div>
                </div>

                <div className="tool-inspector-footer">
                    <button className="ghost" onClick={handleClose}>Close</button>
                </div>
            </div>
        </div>
    )
}
