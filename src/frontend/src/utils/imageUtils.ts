/**
 * Image utility functions for compression and processing.
 * Extracted from Header.tsx for reuse across components.
 */

export function estimateDataUrlBytes(dataUrl: string): number {
    const comma = dataUrl.indexOf(',')
    const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
    let padding = 0
    if (b64.endsWith('==')) padding = 2
    else if (b64.endsWith('=')) padding = 1
    return Math.max(0, Math.floor((b64.length * 3) / 4) - padding)
}

export async function loadImage(dataUrl: string): Promise<HTMLImageElement> {
    return await new Promise((resolve, reject) => {
        const img = new Image()
        img.onload = () => resolve(img)
        img.onerror = () => reject(new Error('Failed to load image for resizing'))
        img.src = dataUrl
    })
}

export async function compressDataUrl(
    dataUrl: string,
    opts: {
        maxBytes: number
        maxDimension: number
    }
): Promise<{ dataUrl: string; didChange: boolean; bytes: number }> {
    const { maxBytes, maxDimension } = opts
    const originalBytes = estimateDataUrlBytes(dataUrl)
    if (originalBytes <= maxBytes) {
        return { dataUrl, didChange: false, bytes: originalBytes }
    }

    const img = await loadImage(dataUrl)
    const w = img.naturalWidth || img.width
    const h = img.naturalHeight || img.height
    const scale = Math.min(1, maxDimension / Math.max(w, h))
    const outW = Math.max(1, Math.round(w * scale))
    const outH = Math.max(1, Math.round(h * scale))

    const canvas = document.createElement('canvas')
    canvas.width = outW
    canvas.height = outH
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Failed to create canvas context for image resizing')

    ctx.drawImage(img, 0, 0, outW, outH)

    // Default to JPEG for large payloads
    let quality = 0.9
    let next = canvas.toDataURL('image/jpeg', quality)
    let nextBytes = estimateDataUrlBytes(next)

    while (nextBytes > maxBytes && quality > 0.6) {
        quality = Math.max(0.6, quality - 0.05)
        next = canvas.toDataURL('image/jpeg', quality)
        nextBytes = estimateDataUrlBytes(next)
    }

    return { dataUrl: next, didChange: true, bytes: nextBytes }
}

/** Maximum payload size for image upload */
export const MAX_IMAGE_BYTES = 7 * 1024 * 1024
/** Maximum image dimension (px) after compression */
export const MAX_IMAGE_DIMENSION = 2000
