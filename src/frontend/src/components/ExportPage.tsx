import { useState, useCallback, useEffect, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getPackage, getWorkflow } from '../api/workflows'
import { useWorkflowStore } from '../stores/workflowStore'
import {
    exportAsJSON,
    exportAsJSONWithOptions,
    exportAsPNG,
    exportAsPython,
    exportPackageAsJSON,
    exportPackageAsPNG,
    exportPackageAsPython,
    getPackagePreviewSvgId,
    WORKFLOW_EXPORT_SVG_ID,
    type PackageExportContext,
    type WorkflowExportContext,
} from '../utils/exportUtils'
import { hydrateWorkflowDetail } from '../utils/workflowHydration'
import type { WorkflowDetailResponse, WorkflowPackage } from '../types'
import FlowchartPreview from './FlowchartPreview'
import '../styles/ExportPage.css'

const DOWNLOAD_SUCCESS_MESSAGE = '✓ Downloaded successfully'

export default function ExportPage() {
    const navigate = useNavigate()
    const { id: routeId } = useParams<{ id?: string }>()
    const routeKind = routeId?.startsWith('pkg_') ? 'package' : 'workflow'
    const {
        currentWorkflow,
        flowchart,
        currentAnalysis,
        setCurrentWorkflow,
        setFlowchartSilent,
        setAnalysis,
        markSavedSnapshot,
    } = useWorkflowStore()
    const [currentPackage, setCurrentPackage] = useState<WorkflowPackage | null>(null)
    const [packageWorkflows, setPackageWorkflows] = useState<WorkflowDetailResponse[]>([])
    const [exporting, setExporting] = useState<string | null>(null)
    const [lastResult, setLastResult] = useState<Record<string, string | null>>({})
    const [includeSubflowsInJson, setIncludeSubflowsInJson] = useState(false)
    const [isHydrating, setIsHydrating] = useState(false)
    const [loadError, setLoadError] = useState<string | null>(null)

    const workflowExportContext: WorkflowExportContext | null = useMemo(() => {
        if (routeKind !== 'workflow') return null
        return { currentWorkflow, flowchart, currentAnalysis }
    }, [currentAnalysis, currentWorkflow, flowchart, routeKind])

    const packageExportContext: PackageExportContext | null = useMemo(() => {
        if (routeKind !== 'package' || !currentPackage) return null
        return { currentPackage, workflows: packageWorkflows }
    }, [currentPackage, packageWorkflows, routeKind])

    const workflowCanExport = Boolean(currentWorkflow?.id) || flowchart.nodes.length > 0 || flowchart.edges.length > 0
    const packageCanExport = Boolean(currentPackage?.head_workflow_id) && packageWorkflows.length > 0
    const canExport = routeKind === 'package' ? packageCanExport : workflowCanExport
    const workflowRoute = routeKind === 'package'
        ? currentPackage?.head_workflow_id ? `/workflow/${currentPackage.head_workflow_id}` : '/library'
        : (routeId || currentWorkflow?.id) ? `/workflow/${routeId || currentWorkflow?.id}` : '/workflow'
    const backLabel = routeKind === 'package' ? 'Back to Head Workflow' : 'Back to Workflow'
    const pageTitle = routeKind === 'package' ? 'Export Package' : 'Export Workflow'

    useEffect(() => {
        if (!routeId && currentWorkflow?.id) {
            navigate(`/export/${currentWorkflow.id}`, { replace: true })
        }
    }, [routeId, currentWorkflow?.id, navigate])

    useEffect(() => {
        if (!routeId) {
            setCurrentPackage(null)
            setPackageWorkflows([])
            setIsHydrating(false)
            setLoadError(null)
            return
        }

        let isActive = true
        setIsHydrating(true)
        setLoadError(null)

        const loadExportTarget = async () => {
            try {
                if (routeKind === 'package') {
                    const pkg = await getPackage(routeId)
                    if (!isActive) return
                    if (!pkg.head_workflow_id) {
                        throw new Error('Package has no head workflow')
                    }
                    const workflows = await Promise.all(pkg.workflows.map(workflow => getWorkflow(workflow.id)))
                    if (!isActive) return
                    setCurrentPackage(pkg)
                    setPackageWorkflows(workflows)
                    return
                }

                setCurrentPackage(null)
                setPackageWorkflows([])
                if (currentWorkflow?.id === routeId) {
                    return
                }

                const workflowData = await getWorkflow(routeId)
                if (!isActive) return
                const hydrated = hydrateWorkflowDetail(workflowData)
                setCurrentWorkflow(hydrated.workflow)
                setFlowchartSilent(hydrated.flowchart)
                setAnalysis(hydrated.analysis)
                markSavedSnapshot()
            } catch (err) {
                if (!isActive) return
                setLoadError(err instanceof Error ? err.message : 'Failed to load export target')
            } finally {
                if (isActive) {
                    setIsHydrating(false)
                }
            }
        }

        void loadExportTarget()
        return () => {
            isActive = false
        }
    }, [
        currentWorkflow?.id,
        markSavedSnapshot,
        navigate,
        routeId,
        routeKind,
        setAnalysis,
        setCurrentWorkflow,
        setFlowchartSilent,
    ])

    const handleWorkflowExport = useCallback(async (format: 'png' | 'python') => {
        if (!workflowExportContext) return
        setExporting(format)
        setLastResult(prev => ({ ...prev, [format]: null }))
        try {
            const result = format === 'png'
                ? await exportAsPNG(workflowExportContext, WORKFLOW_EXPORT_SVG_ID)
                : await exportAsPython(workflowExportContext)
            setLastResult(prev => ({
                ...prev,
                [format]: result === 'cancelled' ? null : result || DOWNLOAD_SUCCESS_MESSAGE,
            }))
        } catch (err) {
            setLastResult(prev => ({
                ...prev,
                [format]: err instanceof Error ? err.message : 'Export failed',
            }))
        } finally {
            setExporting(null)
        }
    }, [workflowExportContext])

    const handlePackageExport = useCallback(async (format: 'json' | 'png' | 'python') => {
        if (!packageExportContext) return
        setExporting(format)
        setLastResult(prev => ({ ...prev, [format]: null }))
        try {
            let result: string | null = null
            if (format === 'json') result = await exportPackageAsJSON(packageExportContext)
            if (format === 'png') result = await exportPackageAsPNG(packageExportContext)
            if (format === 'python') result = await exportPackageAsPython(packageExportContext)
            setLastResult(prev => ({
                ...prev,
                [format]: result === 'cancelled' ? null : result || DOWNLOAD_SUCCESS_MESSAGE,
            }))
        } catch (err) {
            setLastResult(prev => ({
                ...prev,
                [format]: err instanceof Error ? err.message : 'Export failed',
            }))
        } finally {
            setExporting(null)
        }
    }, [packageExportContext])

    const handleJsonExport = useCallback(async () => {
        if (routeKind === 'package') {
            await handlePackageExport('json')
            return
        }
        if (!workflowExportContext) return

        const resultKey = 'json'
        setExporting(resultKey)
        setLastResult(prev => ({ ...prev, [resultKey]: null }))
        try {
            const result = includeSubflowsInJson
                ? await exportAsJSONWithOptions(workflowExportContext, { includeSubflows: true })
                : await exportAsJSON(workflowExportContext)
            setLastResult(prev => ({
                ...prev,
                [resultKey]: result === 'cancelled' ? null : result || DOWNLOAD_SUCCESS_MESSAGE,
            }))
        } catch (err) {
            setLastResult(prev => ({
                ...prev,
                [resultKey]: err instanceof Error ? err.message : 'Export failed',
            }))
        } finally {
            setExporting(null)
        }
    }, [handlePackageExport, includeSubflowsInJson, routeKind, workflowExportContext])

    const packageHead = currentPackage?.workflows.find(workflow => workflow.role === 'head') || null
    const validatedCount = currentPackage?.workflows.filter(workflow => workflow.is_validated).length || 0

    return (
        <div className="export-page">
            <header className="export-header">
                <div className="export-header-left">
                    <button className="ghost export-back-btn" onClick={() => navigate(workflowRoute)}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        {backLabel}
                    </button>
                    <div className="logo">
                        <span className="logo-mark">L</span>
                        <span className="logo-text">LEMON</span>
                    </div>
                </div>
                <h1 className="export-title">{pageTitle}</h1>
                <div className="export-header-right" />
            </header>

            <main className="export-body">
                {isHydrating ? (
                    <div className="export-empty">
                        <p>{routeKind === 'package' ? 'Loading package for export...' : 'Loading workflow for export...'}</p>
                    </div>
                ) : !canExport ? (
                    <div className="export-empty">
                        <p>{loadError || (routeKind === 'package'
                            ? 'No package to export. Choose a package with a head workflow first.'
                            : 'No workflow to export. Create or open a workflow first.')}</p>
                        <button className="primary" onClick={() => navigate(workflowRoute)}>
                            {routeKind === 'package' ? 'Go to Head Workflow' : 'Go to Workflow Editor'}
                        </button>
                    </div>
                ) : (
                    <>
                        {routeKind === 'workflow' && (
                            <FlowchartPreview
                                nodes={flowchart.nodes}
                                edges={flowchart.edges}
                                svgId={WORKFLOW_EXPORT_SVG_ID}
                            />
                        )}
                        {routeKind === 'package' && packageWorkflows.map(workflow => (
                            <FlowchartPreview
                                key={workflow.id}
                                nodes={workflow.nodes}
                                edges={workflow.edges}
                                svgId={getPackagePreviewSvgId(workflow.id)}
                            />
                        ))}

                        <div className="export-cards">
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
                                    {routeKind === 'package'
                                        ? 'Export the full package as a ZIP bundle, including package metadata, the head workflow, and every package member.'
                                        : 'Export as a structured JSON file. Includes the current workflow definition, variables, and all node configurations.'}
                                </p>
                                <div className="export-card-info">
                                    {routeKind === 'package' ? (
                                        <>
                                            <span>{currentPackage?.workflow_count || 0} workflows</span>
                                            <span>{validatedCount} validated</span>
                                            <span>{packageHead?.name || 'Head not set'}</span>
                                        </>
                                    ) : (
                                        <>
                                            <span>{flowchart.nodes.length} nodes</span>
                                            <span>{flowchart.edges.length} connections</span>
                                            <span>{currentAnalysis?.variables?.length || 0} variables</span>
                                        </>
                                    )}
                                </div>
                                {lastResult.json && (
                                    <div className={`export-result ${lastResult.json.startsWith('✓') ? 'success' : 'error'}`}>
                                        {lastResult.json}
                                    </div>
                                )}
                                {routeKind === 'workflow' && (
                                    <>
                                        <label className="export-toggle" htmlFor="bundle-subflows-toggle">
                                            <input
                                                id="bundle-subflows-toggle"
                                                type="checkbox"
                                                checked={includeSubflowsInJson}
                                                onChange={(e) => setIncludeSubflowsInJson(e.target.checked)}
                                            />
                                            <span>Bundle subflows if encountered</span>
                                        </label>
                                        <p className="export-toggle-hint">
                                            Downloads a `.zip` bundle when enabled; otherwise exports the current workflow as `.json`.
                                        </p>
                                    </>
                                )}
                                <button
                                    className="primary export-btn"
                                    onClick={handleJsonExport}
                                    disabled={exporting === 'json'}
                                >
                                    {exporting === 'json'
                                        ? 'Exporting...'
                                        : routeKind === 'package' || includeSubflowsInJson
                                            ? 'Download ZIP'
                                            : 'Download JSON'}
                                </button>
                            </div>

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
                                    {routeKind === 'package'
                                        ? 'Render every workflow in the package as a PNG and bundle them into a ZIP archive, with the head workflow first.'
                                        : 'Export the flowchart as a high-resolution PNG image (2x). Great for documentation, presentations, and sharing.'}
                                </p>
                                <div className="export-card-info">
                                    {routeKind === 'package' ? (
                                        <>
                                            <span>{currentPackage?.workflow_count || 0} PNGs</span>
                                            <span>ZIP archive</span>
                                        </>
                                    ) : (
                                        <>
                                            <span>2x resolution</span>
                                            <span>Transparent-compatible</span>
                                        </>
                                    )}
                                </div>
                                {lastResult.png && (
                                    <div className={`export-result ${lastResult.png.startsWith('✓') ? 'success' : 'error'}`}>
                                        {lastResult.png}
                                    </div>
                                )}
                                <button
                                    className="primary export-btn"
                                    onClick={() => routeKind === 'package' ? handlePackageExport('png') : handleWorkflowExport('png')}
                                    disabled={exporting === 'png'}
                                >
                                    {exporting === 'png'
                                        ? 'Exporting...'
                                        : routeKind === 'package'
                                            ? 'Download PNG ZIP'
                                            : 'Download PNG'}
                                </button>
                            </div>

                            <div className="export-card">
                                <div className="export-card-icon python-icon">
                                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" />
                                        <path d="M8 12l2 2 4-4" />
                                    </svg>
                                </div>
                                <h3>Python</h3>
                                <p className="export-card-desc">
                                    {routeKind === 'package'
                                        ? 'Generate one Python file for the whole package. The head workflow is the entry point, and every package member is emitted as a function.'
                                        : 'Generate executable Python code from the current workflow. Includes imports, docstrings, and a main entry point.'}
                                </p>
                                <div className="export-card-info">
                                    {routeKind === 'package' ? (
                                        <>
                                            <span>Head entry point</span>
                                            <span>All members included</span>
                                        </>
                                    ) : (
                                        <>
                                            <span>Includes imports</span>
                                            <span>Ready to run</span>
                                        </>
                                    )}
                                </div>
                                {lastResult.python && (
                                    <div className={`export-result ${lastResult.python.startsWith('✓') ? 'success' : 'error'}`}>
                                        {lastResult.python}
                                    </div>
                                )}
                                <button
                                    className="primary export-btn"
                                    onClick={() => routeKind === 'package' ? handlePackageExport('python') : handleWorkflowExport('python')}
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
