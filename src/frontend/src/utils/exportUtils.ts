/**
 * Export utility functions for workflow and package export.
 */

import JSZip from 'jszip'
import {
    validateWorkflow,
    compileToPython,
    compilePackageToPython,
    exportWorkflowJson,
    exportWorkflowBundleWithWarnings,
    exportPackageBundleWithWarnings,
} from '../api/workflows'
import type {
    Flowchart,
    Workflow,
    WorkflowAnalysis,
    WorkflowDetailResponse,
    WorkflowPackage,
} from '../types'

export interface WorkflowExportContext {
    currentWorkflow: Workflow | null
    flowchart: Flowchart
    currentAnalysis: WorkflowAnalysis | null
}

export interface PackageExportContext {
    currentPackage: WorkflowPackage
    workflows: WorkflowDetailResponse[]
}

export const WORKFLOW_EXPORT_SVG_ID = 'flowchartCanvas'

export function getPackagePreviewSvgId(workflowId: string): string {
    return `package-flowchart-${workflowId}`
}

function sanitizeFilename(value: string | null | undefined, fallback: string): string {
    const sanitized = (value || fallback)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
    return sanitized || fallback
}

function triggerDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
}

function getWorkflowValidationMessage(errors: Array<{ code: string; message: string; node_id?: string }>): string {
    return errors
        .map(e => `• ${e.code}: ${e.message}${e.node_id ? ` (Node: ${e.node_id})` : ''}`)
        .join('\n')
}

function confirmWarnings(title: string, warnings: string[], prompt: string): boolean {
    return confirm(
        `${title}\n\n${warnings.map(w => `• ${w}`).join('\n')}\n\n${prompt}`
    )
}

function replaceCssVars(svgElement: SVGSVGElement): SVGSVGElement {
    const computedStyle = getComputedStyle(document.documentElement)
    const cssVars: Record<string, string> = {
        '--ink': computedStyle.getPropertyValue('--ink').trim() || '#1f2422',
        '--paper': computedStyle.getPropertyValue('--paper').trim() || '#faf8f4',
        '--cream': computedStyle.getPropertyValue('--cream').trim() || '#f5f1e8',
        '--edge': computedStyle.getPropertyValue('--edge').trim() || '#e4d9c7',
        '--muted': computedStyle.getPropertyValue('--muted').trim() || '#8a8577',
        '--teal': computedStyle.getPropertyValue('--teal').trim() || '#1f6e68',
        '--teal-light': computedStyle.getPropertyValue('--teal-light').trim() || 'rgba(31, 110, 104, 0.12)',
        '--amber': computedStyle.getPropertyValue('--amber').trim() || '#c98a2c',
        '--amber-light': computedStyle.getPropertyValue('--amber-light').trim() || 'rgba(201, 138, 44, 0.15)',
        '--green': computedStyle.getPropertyValue('--green').trim() || '#3e7c4d',
        '--green-light': computedStyle.getPropertyValue('--green-light').trim() || 'rgba(62, 124, 77, 0.15)',
        '--rose': computedStyle.getPropertyValue('--rose').trim() || '#c25d6a',
        '--rose-light': computedStyle.getPropertyValue('--rose-light').trim() || 'rgba(194, 93, 106, 0.15)',
        '--sky': computedStyle.getPropertyValue('--sky').trim() || '#4a90a4',
        '--sky-light': computedStyle.getPropertyValue('--sky-light').trim() || 'rgba(74, 144, 164, 0.15)',
        '--purple': computedStyle.getPropertyValue('--purple').trim() || '#7c3aed',
        '--purple-light': computedStyle.getPropertyValue('--purple-light').trim() || 'rgba(124, 58, 237, 0.15)',
    }

    const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement
    clonedSvg.removeAttribute('style')
    const connectionPorts = clonedSvg.querySelectorAll('.connection-port')
    connectionPorts.forEach(port => port.remove())

    const replaceVars = (str: string): string => {
        let result = str
        for (const [varName, value] of Object.entries(cssVars)) {
            result = result.replace(new RegExp(`var\\(${varName}\\)`, 'g'), value)
        }
        return result
    }

    const processElement = (el: Element) => {
        if (el instanceof SVGElement || el instanceof HTMLElement) {
            const style = el.getAttribute('style')
            if (style) el.setAttribute('style', replaceVars(style))
        }
        const attrs = ['fill', 'stroke', 'stop-color', 'flood-color', 'lighting-color']
        for (const attr of attrs) {
            const value = el.getAttribute(attr)
            if (value && value.includes('var(')) {
                el.setAttribute(attr, replaceVars(value))
            }
        }
        for (const child of el.children) processElement(child)
    }

    processElement(clonedSvg)

    const viewBox = svgElement.viewBox.baseVal
    const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bgRect.setAttribute('x', String(viewBox.x))
    bgRect.setAttribute('y', String(viewBox.y))
    bgRect.setAttribute('width', String(viewBox.width))
    bgRect.setAttribute('height', String(viewBox.height))
    bgRect.setAttribute('fill', cssVars['--cream'])
    clonedSvg.insertBefore(bgRect, clonedSvg.firstChild)

    return clonedSvg
}

async function svgToPngBlob(svgElement: SVGSVGElement): Promise<Blob> {
    const clonedSvg = replaceCssVars(svgElement)
    const viewBox = svgElement.viewBox.baseVal
    const scale = 2
    const width = viewBox.width * scale
    const height = viewBox.height * scale

    clonedSvg.setAttribute('width', String(width))
    clonedSvg.setAttribute('height', String(height))

    const serializer = new XMLSerializer()
    const svgString = serializer.serializeToString(clonedSvg)
    const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
    const svgUrl = URL.createObjectURL(svgBlob)

    return new Promise((resolve, reject) => {
        const img = new window.Image()
        img.onload = () => {
            const canvas = document.createElement('canvas')
            canvas.width = width
            canvas.height = height
            const ctx2d = canvas.getContext('2d')
            if (!ctx2d) {
                URL.revokeObjectURL(svgUrl)
                reject(new Error('Failed to create canvas context'))
                return
            }
            ctx2d.drawImage(img, 0, 0, width, height)
            canvas.toBlob((blob) => {
                URL.revokeObjectURL(svgUrl)
                if (!blob) {
                    reject(new Error('Failed to render PNG blob'))
                    return
                }
                resolve(blob)
            }, 'image/png')
        }
        img.onerror = () => {
            URL.revokeObjectURL(svgUrl)
            reject(new Error('Failed to load SVG for PNG export'))
        }
        img.src = svgUrl
    })
}

function getRequiredSvg(svgId: string): SVGSVGElement {
    const svgElement = document.getElementById(svgId) as SVGSVGElement | null
    if (!svgElement) {
        throw new Error('Flowchart canvas not found')
    }
    return svgElement
}

export async function exportAsJSON(ctx: WorkflowExportContext): Promise<string | null> {
    return exportAsJSONWithOptions(ctx, { includeSubflows: false })
}

export async function exportAsJSONWithOptions(
    ctx: WorkflowExportContext,
    options: { includeSubflows: boolean }
): Promise<string | null> {
    const { currentWorkflow, flowchart, currentAnalysis } = ctx

    if (!currentWorkflow && flowchart.nodes.length === 0) {
        return 'No workflow to export'
    }

    const validationResult = await validateWorkflow({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],
    })

    if (!validationResult.valid) {
        const proceed = confirm(
            `Workflow validation failed\n\n${getWorkflowValidationMessage(validationResult.errors || [])}\n\nDo you want to export anyway?`
        )
        if (!proceed) return 'cancelled'
    }

    if (!currentWorkflow?.id) {
        return 'Save workflow before exporting'
    }

    let blob: Blob
    let warnings: string[] = []
    if (options.includeSubflows) {
        const bundleResult = await exportWorkflowBundleWithWarnings(currentWorkflow.id)
        blob = bundleResult.blob
        warnings = bundleResult.warnings
    } else {
        blob = await exportWorkflowJson(currentWorkflow.id)
    }

    if (warnings.length > 0) {
        const proceed = confirmWarnings(
            'Export warnings',
            warnings,
            'Do you want to download anyway?'
        )
        if (!proceed) return 'cancelled'
    }

    const baseName = sanitizeFilename(currentWorkflow.metadata?.name, 'workflow')
    triggerDownload(blob, `${baseName}.${options.includeSubflows ? 'zip' : 'json'}`)
    return null
}

export async function exportPackageAsJSON(ctx: PackageExportContext): Promise<string | null> {
    const bundleResult = await exportPackageBundleWithWarnings(ctx.currentPackage.id)
    if (bundleResult.warnings.length > 0) {
        const proceed = confirmWarnings(
            'Export warnings',
            bundleResult.warnings,
            'Do you want to download anyway?'
        )
        if (!proceed) return 'cancelled'
    }

    const baseName = sanitizeFilename(ctx.currentPackage.name, 'workflow_package')
    triggerDownload(bundleResult.blob, `${baseName}.zip`)
    return null
}

export async function exportAsPNG(
    ctx: WorkflowExportContext,
    svgId = WORKFLOW_EXPORT_SVG_ID
): Promise<string | null> {
    const { currentWorkflow } = ctx
    const blob = await svgToPngBlob(getRequiredSvg(svgId))
    const workflowName = sanitizeFilename(currentWorkflow?.metadata?.name, 'workflow')
    triggerDownload(blob, `${workflowName}.png`)
    return null
}

export async function exportPackageAsPNG(ctx: PackageExportContext): Promise<string | null> {
    if (ctx.workflows.length === 0) {
        return 'No package workflows to export'
    }

    const zip = new JSZip()
    const orderedWorkflows = [...ctx.workflows].sort((a, b) => {
        if (a.id === ctx.currentPackage.head_workflow_id) return -1
        if (b.id === ctx.currentPackage.head_workflow_id) return 1
        return a.metadata.name.localeCompare(b.metadata.name)
    })

    for (const workflow of orderedWorkflows) {
        const svgElement = getRequiredSvg(getPackagePreviewSvgId(workflow.id))
        const pngBlob = await svgToPngBlob(svgElement)
        const filename = sanitizeFilename(workflow.metadata?.name, workflow.id)
        zip.file(`${filename}.png`, pngBlob)
    }

    const archiveName = sanitizeFilename(ctx.currentPackage.name, 'workflow_package')
    const zipBlob = await zip.generateAsync({ type: 'blob' })
    triggerDownload(zipBlob, `${archiveName}_pngs.zip`)
    return null
}

export async function exportAsPython(ctx: WorkflowExportContext): Promise<string | null> {
    const { currentWorkflow, flowchart, currentAnalysis } = ctx
    const result = await compileToPython({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],
        outputs: currentAnalysis?.outputs || [],
        name: currentWorkflow?.metadata?.name || 'workflow',
        include_imports: true,
        include_docstring: true,
        include_main: true,
    })

    if (!result.success || !result.code) {
        return result.error || 'Failed to generate Python code'
    }

    const criticalWarnings = (result.warnings || []).filter(w =>
        w.includes('Could not compile condition') ||
        w.includes('Unknown variable') ||
        w.includes('not defined') ||
        w.includes('requires manual implementation') ||
        w.includes('Recursive subflow cycle detected')
    )

    if (criticalWarnings.length > 0) {
        const proceed = confirmWarnings(
            'Python export warnings',
            criticalWarnings,
            'Do you want to download anyway?'
        )
        if (!proceed) return 'cancelled'
    }

    const blob = new Blob([result.code], { type: 'text/x-python' })
    const workflowName = sanitizeFilename(currentWorkflow?.metadata?.name, 'workflow')
    triggerDownload(blob, `${workflowName}.py`)
    return null
}

export async function exportPackageAsPython(ctx: PackageExportContext): Promise<string | null> {
    let packageResult = await compilePackageToPython(ctx.currentPackage.id, {
        include_imports: true,
        include_docstring: true,
        include_main: true,
        include_external_subflows: false,
    })

    if (!packageResult.success && packageResult.requires_confirmation && (packageResult.external_subflow_ids || []).length > 0) {
        const externalList = (packageResult.external_subflow_ids || []).map(id => `• ${id}`).join('\n')
        const proceedWithExternal = confirm(
            `External subflows detected\n\nThis package references subflows outside package membership:\n\n${externalList}\n\nDo you want to export Python and include these external subflows?`
        )
        if (!proceedWithExternal) return 'cancelled'

        packageResult = await compilePackageToPython(ctx.currentPackage.id, {
            include_imports: true,
            include_docstring: true,
            include_main: true,
            include_external_subflows: true,
        })
    }

    if (!packageResult.success || !packageResult.code) {
        return packageResult.error || 'Failed to generate package Python code'
    }

    const criticalWarnings = (packageResult.warnings || []).filter(w =>
        w.includes('Could not compile condition') ||
        w.includes('Unknown variable') ||
        w.includes('not defined') ||
        w.includes('requires manual implementation') ||
        w.includes('Recursive subflow cycle detected') ||
        w.includes('could not be compiled') ||
        w.includes('outside package membership')
    )

    if (criticalWarnings.length > 0) {
        const proceed = confirmWarnings(
            'Python export warnings',
            criticalWarnings,
            'Do you want to download anyway?'
        )
        if (!proceed) return 'cancelled'
    }

    const blob = new Blob([packageResult.code], { type: 'text/x-python' })
    const packageName = sanitizeFilename(ctx.currentPackage.name, 'workflow_package')
    triggerDownload(blob, `${packageName}.py`)
    return null
}
