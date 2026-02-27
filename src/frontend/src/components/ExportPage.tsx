import { useState, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { exportAsJSON, exportAsPNG, exportAsPython } from '../utils/exportUtils'
import '../styles/ExportPage.css'

export default function ExportPage() {
    const { currentWorkflow, flowchart, currentAnalysis } = useWorkflowStore()
    const [exporting, setExporting] = useState<string | null>(null)
    const [lastResult, setLastResult] = useState<Record<string, string | null>>({})

    const canExport = currentWorkflow || flowchart.nodes.length > 0

    const ctx = { currentWorkflow, flowchart, currentAnalysis }

    const handleExport = useCallback(async (format: string) => {
        setExporting(format)
        setLastResult(prev => ({ ...prev, [format]: null }))
        try {
            let result: string | null = null
            switch (format) {
                case 'json':
                    result = await exportAsJSON(ctx)
                    break
                case 'png':
                    result = await exportAsPNG(ctx)
                    break
                case 'python':
                    result = await exportAsPython(ctx)
                    break
            }
            setLastResult(prev => ({
                ...prev,
                [format]: result === 'cancelled' ? null : result || '✓ Downloaded successfully'
            }))
        } catch (err) {
            setLastResult(prev => ({
                ...prev,
                [format]: err instanceof Error ? err.message : 'Export failed'
            }))
        } finally {
            setExporting(null)
        }
    }, [ctx])

    return (
        <div className="export-page">
            <header className="export-header">
                <div className="export-header-left">
                    <button className="ghost export-back-btn" onClick={() => { window.location.hash = '#/workflow' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        Back to Workflow
                    </button>
                    <div className="logo">
                        <span className="logo-mark">L</span>
                        <span className="logo-text">LEMON</span>
                    </div>
                </div>
                <h1 className="export-title">Export Workflow</h1>
                <div className="export-header-right" />
            </header>

            <main className="export-body">
                {!canExport ? (
                    <div className="export-empty">
                        <p>No workflow to export. Create or open a workflow first.</p>
                        <button className="primary" onClick={() => { window.location.hash = '#/workflow' }}>
                            Go to Workflow Editor
                        </button>
                    </div>
                ) : (
                    <div className="export-cards">
                        {/* JSON Export */}
                        <div className="export-card">
                            <div className="export-card-icon json-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                                    <polyline points="14 2 14 8 20 8" />
                                    <path d="M8 13h2M8 17h2M14 13h2M14 17h2" />
                                </svg>
                            </div>
                            <h3>JSON</h3>
                            <p className="export-card-desc">
                                Export as a structured JSON file. Includes the full workflow definition,
                                variables, and all node configurations. Can be re-imported later.
                            </p>
                            <div className="export-card-info">
                                <span>{flowchart.nodes.length} nodes</span>
                                <span>{flowchart.edges.length} connections</span>
                                <span>{currentAnalysis?.variables?.length || 0} variables</span>
                            </div>
                            {lastResult.json && (
                                <div className={`export-result ${lastResult.json.startsWith('✓') ? 'success' : 'error'}`}>
                                    {lastResult.json}
                                </div>
                            )}
                            <button
                                className="primary export-btn"
                                onClick={() => handleExport('json')}
                                disabled={exporting === 'json'}
                            >
                                {exporting === 'json' ? 'Exporting...' : 'Download JSON'}
                            </button>
                        </div>

                        {/* PNG Export */}
                        <div className="export-card">
                            <div className="export-card-icon png-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                                    <circle cx="8.5" cy="8.5" r="1.5" />
                                    <polyline points="21 15 16 10 5 21" />
                                </svg>
                            </div>
                            <h3>PNG Image</h3>
                            <p className="export-card-desc">
                                Export the flowchart as a high-resolution PNG image (2x).
                                Great for documentation, presentations, and sharing.
                            </p>
                            <div className="export-card-info">
                                <span>2x resolution</span>
                                <span>Transparent-compatible</span>
                            </div>
                            {lastResult.png && (
                                <div className={`export-result ${lastResult.png.startsWith('✓') ? 'success' : 'error'}`}>
                                    {lastResult.png}
                                </div>
                            )}
                            <button
                                className="primary export-btn"
                                onClick={() => handleExport('png')}
                                disabled={exporting === 'png'}
                            >
                                {exporting === 'png' ? 'Exporting...' : 'Download PNG'}
                            </button>
                        </div>

                        {/* Python Export */}
                        <div className="export-card">
                            <div className="export-card-icon python-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" />
                                    <path d="M8 12l2 2 4-4" />
                                </svg>
                            </div>
                            <h3>Python</h3>
                            <p className="export-card-desc">
                                Generate executable Python code from the workflow.
                                Includes imports, docstrings, and a main entry point.
                            </p>
                            <div className="export-card-info">
                                <span>Includes imports</span>
                                <span>Ready to run</span>
                            </div>
                            {lastResult.python && (
                                <div className={`export-result ${lastResult.python.startsWith('✓') ? 'success' : 'error'}`}>
                                    {lastResult.python}
                                </div>
                            )}
                            <button
                                className="primary export-btn"
                                onClick={() => handleExport('python')}
                                disabled={exporting === 'python'}
                            >
                                {exporting === 'python' ? 'Exporting...' : 'Download Python'}
                            </button>
                        </div>
                    </div>
                )}
            </main>
        </div>
    )
}
