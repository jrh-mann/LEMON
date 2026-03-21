// Shared node color helpers used by Canvas, FlowchartPreview,
// FlowchartPreviewAnnotated, and SubflowExecutionModal.

import type { FlowNodeType } from '../../types'

/** Background fill color for a given node type. */
export const getNodeFillColor = (type: FlowNodeType): string => {
    switch (type) {
        case 'start': return 'var(--teal-light)'
        case 'decision': return 'var(--amber-light)'
        case 'end': return 'var(--green-light)'
        case 'subprocess': return 'var(--rose-light)'
        case 'calculation': return 'var(--purple-light)'
        case 'process': return 'var(--paper)'
        default: return 'var(--paper)'
    }
}

/** Border/stroke color for a given node type. */
export const getNodeStrokeColor = (type: FlowNodeType): string => {
    switch (type) {
        case 'start': return 'var(--teal)'
        case 'decision': return 'var(--amber)'
        case 'end': return 'var(--green)'
        case 'subprocess': return 'var(--rose)'
        case 'calculation': return 'var(--purple)'
        case 'process': return 'var(--edge)'
        default: return 'var(--edge)'
    }
}

/**
 * Word-wrap text into lines of at most `maxChars` characters.
 * Splits on word boundaries. Returns at least one (possibly empty) line.
 */
export function wrapText(text: string, maxChars: number): string[] {
    if (!text || text.length <= maxChars) return [text || '']
    const words = text.split(' ')
    const lines: string[] = []
    let currentLine = ''
    for (const word of words) {
        if ((currentLine + ' ' + word).trim().length <= maxChars) {
            currentLine = (currentLine + ' ' + word).trim()
        } else {
            if (currentLine) lines.push(currentLine)
            currentLine = word
        }
    }
    if (currentLine) lines.push(currentLine)
    return lines.length > 0 ? lines : ['']
}
