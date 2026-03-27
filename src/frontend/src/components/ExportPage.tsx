import { useState, useCallback, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getWorkflow } from '../api/workflows'
import { useWorkflowStore } from '../stores/workflowStore'
import { exportAsJSON, exportAsJSONWithOptions, exportAsPNG, exportAsPython } from '../utils/exportUtils'
import { hydrateWorkflowDetail } from '../utils/workflowHydration'
import FlowchartPreview from './FlowchartPreview'
import '../styles/ExportPage.css'

export default function ExportPage() {
    const navigate = useNavigate()
    const { id: routeWorkflowId } = useParams<{ id?: string }>()
    const {
        currentWorkflow,
        flowchart,
        currentAnalysis,
        setCurrentWorkflow,
        setFlowchartSilent,
        setAnalysis,
        markSavedSnapshot,
    } = useWorkflowStore()
    const [exporting, setExporting] = useState<string | null>(null)
    const [lastResult, setLastResult] = useState<Record<string, string | null>>({})
    const [includeSubflowsInJson, setIncludeSubflowsInJson] = useState(false)
    const [isHydrating, setIsHydrating] = useState(false)
    const [loadError, setLoadError] = useState<string | null>(null)

    const canExport = Boolean(currentWorkflow?.id) || flowchart.nodes.length > 0 || flowchart.edges.length > 0
    const resolvedWorkflowId = routeWorkflowId || currentWorkflow?.id || null
    const workflowRoute = resolvedWorkflowId ? `/workflow/${resolvedWorkflowId}` : '/workflow'
    const isPackageContext = Boolean(currentWorkflow?.package_id)

    useEffect(() => {
        if (!routeWorkflowId && currentWorkflow?.id) {
            navigate(`/export/${currentWorkflow.id}`, { replace: true })
        }
    }, [routeWorkflowId, currentWorkflow?.id, navigate])

    useEffect(() => {
        if (!routeWorkflowId) {
            setIsHydrating(false)
            setLoadError(null)
            return
        }
        if (currentWorkflow?.id === routeWorkflowId) {
            setIsHydrating(false)
            setLoadError(null)
            return
        }

        let isActive = true
        setIsHydrating(true)
        setLoadError(null)

        const loadWorkflowFromRoute = async () => {
            try {
                const workflowData = await getWorkflow(routeWorkflowId)
                if (!isActive) return
                const hydrated = hydrateWorkflowDetail(workflowData)
                setCurrentWorkflow(hydrated.workflow)
                setFlowchartSilent(hydrated.flowchart)
                setAnalysis(hydrated.analysis)
                markSavedSnapshot()
            } catch (err) {
                if (!isActive) return
                setLoadError(err instanceof Error ? err.message : 'Failed to load workflow')
            } finally {
                if (isActive) {
                    setIsHydrating(false)
                }
            }
        }

        void loadWorkflowFromRoute()
        return () => {
            isActive = false
        }
    }, [
        currentWorkflow?.id,
        markSavedSnapshot,
        routeWorkflowId,
        setAnalysis,
        setCurrentWorkflow,
        setFlowchartSilent,
    ])

    const handleExport = useCallback(async (format: string) => {
        const ctx = { currentWorkflow, flowchart, currentAnalysis }
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
    }, [currentAnalysis, currentWorkflow, flowchart])

    const handleJsonExport = useCallback(async () => {
        const ctx = { currentWorkflow, flowchart, currentAnalysis }
        const resultKey = 'json'
        setExporting(resultKey)
        setLastResult(prev => ({ ...prev, [resultKey]: null }))
        try {
            const result = includeSubflowsInJson
                ? await exportAsJSONWithOptions(ctx, { includeSubflows: true })
                : await exportAsJSON(ctx)
            setLastResult(prev => ({
                ...prev,
                [resultKey]: result === 'cancelled' ? null : result || '✓ Downloaded successfully'
            }))
        } catch (err) {
            setLastResult(prev => ({
                ...prev,
                [resultKey]: err instanceof Error ? err.message : 'Export failed'
            }))
        } finally {
            setExporting(null)
        }
    }, [currentAnalysis, currentWorkflow, flowchart, includeSubflowsInJson])

    return (
        <div className="export-page">
            <header className="export-header">
                <div className="export-header-left">
                    <button className="ghost export-back-btn" onClick={() => navigate(workflowRoute)}>
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
                {isHydrating ? (
                    <div className="export-empty">
                        <p>Loading workflow for export...</p>
                    </div>
                ) : !canExport ? (
                    <div className="export-empty">
                        <p>{loadError || 'No workflow to export. Create or open a workflow first.'}</p>
                        <button className="primary" onClick={() => navigate(workflowRoute)}>
                            Go to Workflow Editor
                        </button>
                    </div>
                ) : (
                    <>
                    {/* Hidden off-screen SVG so exportAsPNG can find id="flowchartCanvas" */}
                    <FlowchartPreview nodes={flowchart.nodes} edges={flowchart.edges} />
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
                                {isPackageContext
                                    ? 'Export the full workflow package as a ZIP bundle, including the head workflow and package members.'
                                    : 'Export as a structured JSON file. Includes the full workflow definition, variables, and all node configurations. Can be re-imported later.'}
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
                            <label className="export-toggle" htmlFor="bundle-subflows-toggle">
                                <input
                                    id="bundle-subflows-toggle"
                                    type="checkbox"
                                    checked={isPackageContext || includeSubflowsInJson}
                                    onChange={(e) => setIncludeSubflowsInJson(e.target.checked)}
                                    disabled={isPackageContext}
                                />
                                <span>{isPackageContext ? 'Export this package' : 'Bundle subflows if encountered'}</span>
                            </label>
                            <p className="export-toggle-hint">
                                {isPackageContext
                                    ? 'Package workflows download as a `.zip` bundle.'
                                    : 'Downloads a `.zip` bundle when enabled; otherwise exports the current workflow as `.json`.'}
                            </p>
                            <button
                                className="primary export-btn"
                                onClick={handleJsonExport}
                                disabled={exporting === 'json'}
                            >
                                {exporting === 'json'
                                    ? 'Exporting...'
                                    : (isPackageContext || includeSubflowsInJson)
                                        ? 'Download Package ZIP'
                                        : 'Download JSON'}
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
                                {isPackageContext
                                    ? 'Generate one Python file for the full package using the main workflow as the entry point.'
                                    : 'Generate executable Python code from the workflow. Includes imports, docstrings, and a main entry point.'}
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
                    </>
                )}
            </main>
        </div>
    )
}
