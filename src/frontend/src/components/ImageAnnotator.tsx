import { useState, useRef, useEffect, useCallback } from 'react'

// ─── Data model ──────────────────────────────────────

export interface Annotation {
    type: 'label'
    dotX: number   // native image-px
    dotY: number
    text: string
}

// ─── Component ───────────────────────────────────────

interface Props {
    imageSrc: string
    annotations: Annotation[]
    onChange: (annotations: Annotation[]) => void
}

const DOT_RADIUS = 7          // screen-px
const DOT_HIT_RADIUS = 14     // screen-px
const DOT_COLOR = '#e6b800'
const DOT_COLOR_ACTIVE = '#ffd633'

export default function ImageAnnotator({ imageSrc, annotations, onChange }: Props) {
    const containerRef = useRef<HTMLDivElement>(null)
    const viewportRef = useRef<HTMLDivElement>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const imageRef = useRef<HTMLImageElement | null>(null)
    const [imageLoaded, setImageLoaded] = useState(false)

    // Viewport state
    const [zoom, setZoom] = useState(1)
    const [pan, setPan] = useState({ x: 0, y: 0 })
    const [fitScale, setFitScale] = useState(1)
    const [canvasW, setCanvasW] = useState(0)
    const [canvasH, setCanvasH] = useState(0)
    const [centerOffset, setCenterOffset] = useState({ x: 0, y: 0 })

    // Interaction
    const [isPanning, setIsPanning] = useState(false)
    const panStartRef = useRef({ screenX: 0, screenY: 0, panX: 0, panY: 0 })

    // Modal state
    const [editingIdx, setEditingIdx] = useState<number | null>(null)
    const [editText, setEditText] = useState('')

    // Cursor
    const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null)

    // ─── Image loading ──────────────────────────────
    useEffect(() => {
        const img = new Image()
        img.onload = () => {
            imageRef.current = img
            setImageLoaded(true)
        }
        img.src = imageSrc
    }, [imageSrc])

    // ─── Canvas sizing (from container Rect) ────────
    useEffect(() => {
        const viewport = viewportRef.current
        if (!viewport) return

        let frameId: number
        const ro = new ResizeObserver((entries) => {
            if (!entries || !entries.length) return
            const rect = entries[0].contentRect
            const w = Math.round(rect.width)
            const h = Math.round(rect.height)

            if (w > 0 && h > 0) {
                cancelAnimationFrame(frameId)
                frameId = requestAnimationFrame(() => {
                    setCanvasW(w)
                    setCanvasH(h)
                })
            }
        })

        ro.observe(viewport)
        return () => {
            ro.disconnect()
            cancelAnimationFrame(frameId)
        }
    }, [imageLoaded])

    // ─── Fit-scale + centering offset ───────────────
    useEffect(() => {
        const img = imageRef.current
        if (!img || !canvasW || !canvasH) return
        const scaleX = canvasW / img.width
        const scaleY = canvasH / img.height
        const fit = Math.min(scaleX, scaleY)
        setFitScale(fit)
        setCenterOffset({
            x: (canvasW - img.width * fit) / 2,
            y: (canvasH - img.height * fit) / 2,
        })
        setZoom(1)
        setPan({ x: 0, y: 0 })
    }, [imageLoaded, canvasW, canvasH])

    // ─── Coordinate transforms ──────────────────────
    const effectiveScale = fitScale * zoom

    const screenToImage = useCallback(
        (screenX: number, screenY: number): { x: number; y: number } => {
            const canvas = canvasRef.current
            if (!canvas) return { x: 0, y: 0 }
            const rect = canvas.getBoundingClientRect()
            const cx = screenX - rect.left
            const cy = screenY - rect.top
            return {
                x: Math.round((cx - centerOffset.x) / effectiveScale + pan.x),
                y: Math.round((cy - centerOffset.y) / effectiveScale + pan.y),
            }
        },
        [effectiveScale, pan, centerOffset]
    )

    const imageToScreen = useCallback(
        (ix: number, iy: number): { x: number; y: number } => {
            const canvas = canvasRef.current
            if (!canvas) return { x: 0, y: 0 }
            const rect = canvas.getBoundingClientRect()
            return {
                x: (ix - pan.x) * effectiveScale + centerOffset.x + rect.left,
                y: (iy - pan.y) * effectiveScale + centerOffset.y + rect.top,
            }
        },
        [effectiveScale, pan, centerOffset]
    )

    // ─── Clamp pan ──────────────────────────────────
    const clampPan = useCallback(
        (p: { x: number; y: number }): { x: number; y: number } => {
            const img = imageRef.current
            if (!img) return p
            const viewW = canvasW / effectiveScale
            const viewH = canvasH / effectiveScale
            return {
                x: Math.max(0, Math.min(p.x, img.width - viewW)),
                y: Math.max(0, Math.min(p.y, img.height - viewH)),
            }
        },
        [canvasW, canvasH, effectiveScale]
    )

    // ─── Zoom ───────────────────────────────────────
    const MIN_ZOOM = 0.25
    const MAX_ZOOM = 8

    const zoomAt = useCallback(
        (factor: number, screenX: number, screenY: number) => {
            const canvas = canvasRef.current
            if (!canvas) return
            const rect = canvas.getBoundingClientRect()
            const cx = screenX - rect.left - centerOffset.x
            const cy = screenY - rect.top - centerOffset.y

            setZoom(prev => {
                const next = Math.max(MIN_ZOOM, Math.min(prev * factor, MAX_ZOOM))
                const newScale = fitScale * next
                const oldScale = fitScale * prev
                setPan(p => clampPan({
                    x: p.x + cx / oldScale - cx / newScale,
                    y: p.y + cy / oldScale - cy / newScale,
                }))
                return next
            })
        },
        [fitScale, clampPan, centerOffset]
    )

    const zoomIn = () => {
        const canvas = canvasRef.current
        if (!canvas) return
        const rect = canvas.getBoundingClientRect()
        zoomAt(1.25, rect.left + rect.width / 2, rect.top + rect.height / 2)
    }
    const zoomOut = () => {
        const canvas = canvasRef.current
        if (!canvas) return
        const rect = canvas.getBoundingClientRect()
        zoomAt(0.8, rect.left + rect.width / 2, rect.top + rect.height / 2)
    }
    const resetView = () => {
        setZoom(1)
        setPan({ x: 0, y: 0 })
    }

    // ─── Find dot under cursor ──────────────────────
    const findDotAt = useCallback(
        (screenX: number, screenY: number): number => {
            for (let i = annotations.length - 1; i >= 0; i--) {
                const ann = annotations[i]
                const dotScreen = imageToScreen(ann.dotX, ann.dotY)
                const dx = screenX - dotScreen.x
                const dy = screenY - dotScreen.y
                if (dx * dx + dy * dy <= DOT_HIT_RADIUS * DOT_HIT_RADIUS) {
                    return i
                }
            }
            return -1
        },
        [annotations, imageToScreen]
    )

    // ─── Canvas drawing ─────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current
        const img = imageRef.current
        if (!canvas || !img || !canvasW || !canvasH) return
        const ctx = canvas.getContext('2d')
        if (!ctx) return

        // Background matches toolbar
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#1a1a1a'
        ctx.fillRect(0, 0, canvasW, canvasH)

        ctx.save()
        ctx.translate(centerOffset.x, centerOffset.y)
        ctx.scale(effectiveScale, effectiveScale)
        ctx.translate(-pan.x, -pan.y)

        // Image at native resolution
        ctx.drawImage(img, 0, 0, img.width, img.height)

        // Draw label dots
        const invScale = 1 / effectiveScale
        annotations.forEach((ann, idx) => {
            drawLabelDot(ctx, ann.dotX, ann.dotY, idx + 1, invScale, editingIdx === idx)
        })

        ctx.restore()
    }, [annotations, canvasW, canvasH, effectiveScale, pan, centerOffset, imageLoaded, editingIdx])

    // ─── Mouse handlers ─────────────────────────────

    const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
        if (e.button === 2) return

        const dotIdx = findDotAt(e.clientX, e.clientY)

        // Click on dot → open modal
        if (dotIdx >= 0) {
            setEditingIdx(dotIdx)
            setEditText(annotations[dotIdx].text)
            return
        }

        // Otherwise → pan
        setIsPanning(true)
        panStartRef.current = { screenX: e.clientX, screenY: e.clientY, panX: pan.x, panY: pan.y }
    }

    const handleDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
        e.preventDefault()
        const coords = screenToImage(e.clientX, e.clientY)
        const newIdx = annotations.length
        onChange([...annotations, { type: 'label', dotX: coords.x, dotY: coords.y, text: '' }])
        setEditingIdx(newIdx)
        setEditText('')
    }

    const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
        const imgCoords = screenToImage(e.clientX, e.clientY)
        setCursorPos(imgCoords)

        if (isPanning) {
            const dx = (e.clientX - panStartRef.current.screenX) / effectiveScale
            const dy = (e.clientY - panStartRef.current.screenY) / effectiveScale
            setPan(clampPan({
                x: panStartRef.current.panX - dx,
                y: panStartRef.current.panY - dy,
            }))
        }
    }

    const handleMouseUp = () => {
        if (isPanning) setIsPanning(false)
    }

    const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
        e.preventDefault()
        zoomAt(e.deltaY < 0 ? 1.1 : 0.9, e.clientX, e.clientY)
    }

    const handleContextMenu = (e: React.MouseEvent<HTMLCanvasElement>) => {
        e.preventDefault()
        const dotIdx = findDotAt(e.clientX, e.clientY)
        if (dotIdx >= 0) {
            const next = [...annotations]
            next.splice(dotIdx, 1)
            if (editingIdx === dotIdx) setEditingIdx(null)
            onChange(next)
        }
    }

    const handleMouseLeave = () => {
        setCursorPos(null)
        if (isPanning) setIsPanning(false)
    }

    // ─── Modal handlers ─────────────────────────────

    const handleModalSave = () => {
        if (editingIdx == null) return
        if (!editText.trim()) {
            // Empty text → delete the dot
            const next = [...annotations]
            next.splice(editingIdx, 1)
            onChange(next)
        } else {
            const updated = [...annotations]
            updated[editingIdx] = { ...updated[editingIdx], text: editText.trim() }
            onChange(updated)
        }
        setEditingIdx(null)
        setEditText('')
    }

    const handleModalDelete = () => {
        if (editingIdx == null) return
        const next = [...annotations]
        next.splice(editingIdx, 1)
        onChange(next)
        setEditingIdx(null)
        setEditText('')
    }

    const handleModalClose = () => {
        // If the dot has no text (just placed), delete it
        if (editingIdx != null && !annotations[editingIdx]?.text && !editText.trim()) {
            const next = [...annotations]
            next.splice(editingIdx, 1)
            onChange(next)
        }
        setEditingIdx(null)
        setEditText('')
    }

    const clearAll = () => {
        onChange([])
        setEditingIdx(null)
    }

    // ─── Cursor style ───────────────────────────────
    const getCursor = (): string => {
        if (isPanning) return 'grabbing'
        return 'grab'
    }

    if (!imageLoaded) {
        return (
            <div className="image-annotator image-annotator-full" ref={containerRef}>
                <div className="annotator-loading">Loading image...</div>
            </div>
        )
    }

    const img = imageRef.current!

    return (
        <div className="image-annotator image-annotator-full" ref={containerRef}>
            <div className="annotator-toolbar">
                <button className="annotator-tool" onClick={zoomOut} title="Zoom out">−</button>
                <span className="annotator-zoom-level">{Math.round(zoom * 100)}%</span>
                <button className="annotator-tool" onClick={zoomIn} title="Zoom in">+</button>
                <button className="annotator-tool" onClick={resetView} title="Fit to view">Fit</button>

                <div className="annotator-separator" />

                <span className="annotator-info">{img.width}×{img.height}</span>

                {annotations.length > 0 && (
                    <>
                        <div className="annotator-separator" />
                        <span className="annotator-count">
                            {annotations.length} label{annotations.length !== 1 ? 's' : ''}
                        </span>
                        <button className="annotator-clear" onClick={clearAll} title="Clear all labels">
                            Clear
                        </button>
                    </>
                )}
            </div>



            <div className="annotator-content" ref={viewportRef}>
                <div className="annotator-viewport">
                    <canvas
                        ref={canvasRef}
                        width={canvasW}
                        height={canvasH}
                        className="annotator-canvas"
                        style={{ cursor: getCursor() }}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={handleMouseLeave}
                        onDoubleClick={handleDoubleClick}
                        onContextMenu={handleContextMenu}
                        onWheel={handleWheel}
                    />
                </div>
            </div>

            <div className="annotator-hint">
                {cursorPos && (
                    <span className="annotator-coords">
                        x: {cursorPos.x}  y: {cursorPos.y}
                    </span>
                )}
                <span className="annotator-shortcuts">
                    <span className="annotator-shortcut">Dbl-click</span> label
                    {' · '}
                    <span className="annotator-shortcut">Click dot</span> edit
                    {' · '}
                    <span className="annotator-shortcut">Right-click</span> delete
                    {' · '}
                    <span className="annotator-shortcut">Scroll</span> zoom
                    {' · '}
                    <span className="annotator-shortcut">Drag</span> pan
                </span>
            </div>

            {/* LEMON-style modal for editing label text */}
            {editingIdx != null && editingIdx < annotations.length && (
                <div className="modal open">
                    <div className="modal-backdrop" onClick={handleModalClose} />
                    <div className="modal-content annotation-modal">
                        <div className="modal-header">
                            <h2>Label #{editingIdx + 1}</h2>
                            <button className="modal-close" onClick={handleModalClose}>×</button>
                        </div>
                        <div className="modal-body">
                            <div className="form-group">
                                <label htmlFor="annotation-text">Annotation Text</label>
                                <textarea
                                    id="annotation-text"
                                    value={editText}
                                    onChange={(e) => setEditText(e.target.value)}
                                    placeholder="Enter clarification text for this label..."
                                    rows={4}
                                    autoFocus
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                            handleModalSave()
                                        }
                                    }}
                                />
                                <small className="muted">
                                    Position: ({annotations[editingIdx].dotX}, {annotations[editingIdx].dotY})
                                    {' · Ctrl+Enter to save'}
                                </small>
                            </div>
                            <div className="form-actions">
                                <button className="ghost" onClick={handleModalDelete}>
                                    Delete
                                </button>
                                <button className="ghost" onClick={handleModalClose}>
                                    Cancel
                                </button>
                                <button className="primary" onClick={handleModalSave}>
                                    Save Label
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

// ─── Drawing helpers ────────────────────────────────

function drawLabelDot(
    ctx: CanvasRenderingContext2D,
    x: number, y: number,
    number: number,
    invScale: number,
    isActive: boolean,
) {
    const r = DOT_RADIUS * invScale
    ctx.save()

    // Glow when active
    if (isActive) {
        ctx.beginPath()
        ctx.arc(x, y, r * 2.2, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(230, 184, 0, 0.25)'
        ctx.fill()
    }

    // Drop shadow
    ctx.beginPath()
    ctx.arc(x, y + 1.5 * invScale, r, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(0, 0, 0, 0.3)'
    ctx.fill()

    // Dot
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = isActive ? DOT_COLOR_ACTIVE : DOT_COLOR
    ctx.fill()
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.4)'
    ctx.lineWidth = 1.5 * invScale
    ctx.stroke()

    // Number
    const fontSize = 9 * invScale
    ctx.font = `bold ${fontSize}px "Space Grotesk", sans-serif`
    ctx.fillStyle = '#000'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(number), x, y + 0.5 * invScale)

    ctx.restore()
}
