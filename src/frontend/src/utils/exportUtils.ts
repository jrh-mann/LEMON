/**
 * Export utility functions for workflow export.
 * Extracted from Header.tsx for reuse in ExportPage.
 */

import { validateWorkflow, compileToPython } from '../api/workflows'
import type { Flowchart, WorkflowAnalysis, Workflow } from '../types'

interface ExportContext {
    currentWorkflow: Workflow | null
    flowchart: Flowchart
    currentAnalysis: WorkflowAnalysis | null
}

/**
 * Export workflow as JSON file.
 * Returns null on success, or an error string.
 */
export async function exportAsJSON(ctx: ExportContext): Promise<string | null> {
    const { currentWorkflow, flowchart, currentAnalysis } = ctx

    if (!currentWorkflow && flowchart.nodes.length === 0) {
        return 'No workflow to export'
    }

    // Validate workflow first
    const validationResult = await validateWorkflow({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],
    })

    if (!validationResult.valid) {
        const errorMessages = validationResult.errors
            ?.map(e => `• ${e.code}: ${e.message}${e.node_id ? ` (Node: ${e.node_id})` : ''}`)
            .join('\n')

        const proceed = confirm(
            `⚠️ Workflow Validation Failed\n\n${errorMessages}\n\nDo you want to export anyway?`
        )
        if (!proceed) return 'cancelled'
    }

    const exportData = {
        id: currentWorkflow?.id || 'draft',
        metadata: currentWorkflow?.metadata || {
            name: 'Draft Workflow',
            description: '',
            tags: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            validation_score: 0,
            validation_count: 0,
            is_validated: false,
        },
        flowchart,
        variables: currentAnalysis?.variables || [],
        outputs: currentAnalysis?.outputs || [],
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${exportData.metadata?.name || 'workflow'}.json`
    a.click()
    URL.revokeObjectURL(url)
    return null
}

/**
 * Export workflow as PNG image.
 * Returns null on success, or an error string.
 */
export async function exportAsPNG(ctx: ExportContext): Promise<string | null> {
    const { currentWorkflow } = ctx

    const svgElement = document.getElementById('flowchartCanvas') as unknown as SVGSVGElement
    if (!svgElement) {
        return 'Flowchart canvas not found'
    }

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
    }

    const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement
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
    const scale = 2
    const width = viewBox.width * scale
    const height = viewBox.height * scale

    clonedSvg.setAttribute('width', String(width))
    clonedSvg.setAttribute('height', String(height))

    const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bgRect.setAttribute('width', '100%')
    bgRect.setAttribute('height', '100%')
    bgRect.setAttribute('fill', cssVars['--cream'])
    clonedSvg.insertBefore(bgRect, clonedSvg.firstChild)

    const serializer = new XMLSerializer()
    const svgString = serializer.serializeToString(clonedSvg)
    const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
    const svgUrl = URL.createObjectURL(svgBlob)

    return new Promise((resolve) => {
        const img = new window.Image()
        img.onload = () => {
            const canvas = document.createElement('canvas')
            canvas.width = width
            canvas.height = height
            const ctx2d = canvas.getContext('2d')
            if (!ctx2d) {
                URL.revokeObjectURL(svgUrl)
                resolve('Failed to create canvas context')
                return
            }
            ctx2d.drawImage(img, 0, 0, width, height)
            const pngUrl = canvas.toDataURL('image/png')
            const a = document.createElement('a')
            a.href = pngUrl
            const workflowName = currentWorkflow?.metadata?.name || 'workflow'
            a.download = `${workflowName}.png`
            a.click()
            URL.revokeObjectURL(svgUrl)
            resolve(null)
        }
        img.onerror = () => {
            URL.revokeObjectURL(svgUrl)
            resolve('Failed to load SVG for PNG export')
        }
        img.src = svgUrl
    })
}

/**
 * Export workflow as Python code.
 * Returns null on success, or an error string.
 */
export async function exportAsPython(ctx: ExportContext): Promise<string | null> {
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
        w.includes('requires manual implementation')
    )

    if (criticalWarnings.length > 0) {
        const proceed = confirm(
            `⚠️ Python Export Warnings\n\n` +
            `The generated code may not work correctly:\n\n` +
            criticalWarnings.map(w => `• ${w}`).join('\n') +
            `\n\nDo you want to download anyway?`
        )
        if (!proceed) return 'cancelled'
    }

    const blob = new Blob([result.code], { type: 'text/x-python' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const workflowName = currentWorkflow?.metadata?.name || 'workflow'
    const filename = workflowName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_+$/, '')
    a.download = `${filename || 'workflow'}.py`
    a.click()
    URL.revokeObjectURL(url)
    return null
}
