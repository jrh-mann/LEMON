import { useState, useRef, useEffect, useCallback } from 'react'
import { useChatStore } from '../stores/chatStore'
import { sendChatMessage } from '../api/socket'
import { useWorkflowStore } from '../stores/workflowStore'

// ─── Data model ──────────────────────────────────────

export type Annotation = LabelAnnotation | QuestionAnnotation

export interface LabelAnnotation {
    type: 'label'
    x: number   // native image-px
    y: number
    text: string
}

export interface QuestionAnnotation {
    id: string
    type: 'question'
    x: number
    y: number
    question: string
    status: 'pending' | 'answered'
}

// ─── Component ───────────────────────────────────────

interface Props {
    imageSrc: string
    annotations: Annotation[]
    onChange: (annotations: Annotation[]) => void
}

const DOT_RADIUS = 12         // screen-px
const DOT_HIT_RADIUS = 18     // screen-px
const DOT_COLOR = '#FFB300'   // Material Amber 600
const DOT_COLOR_ACTIVE = '#FFCA28' // Material Amber 400

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

            const b1x = centerOffset.x / effectiveScale
            const b2x = img.width - (canvasW - centerOffset.x) / effectiveScale
            const minX = Math.min(b1x, b2x)
            const maxX = Math.max(b1x, b2x)

            const b1y = centerOffset.y / effectiveScale
            const b2y = img.height - (canvasH - centerOffset.y) / effectiveScale
            const minY = Math.min(b1y, b2y)
            const maxY = Math.max(b1y, b2y)

            return {
                x: Math.max(minX, Math.min(p.x, maxX)),
                y: Math.max(minY, Math.min(p.y, maxY)),
            }
        },
        [canvasW, canvasH, effectiveScale, centerOffset]
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
                const dotScreen = imageToScreen(ann.x, ann.y)
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

        const dpr = window.devicePixelRatio || 1

        // Background matches toolbar
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#1a1a1a'
        ctx.fillRect(0, 0, canvas.width, canvas.height)

        ctx.save()
        ctx.scale(dpr, dpr)
        ctx.translate(centerOffset.x, centerOffset.y)
        ctx.scale(effectiveScale, effectiveScale)
        ctx.translate(-pan.x, -pan.y)

        // Image at native resolution
        ctx.drawImage(img, 0, 0, img.width, img.height)

        // Draw label & question dots
        const invScale = 1 / effectiveScale
        annotations.forEach((ann, idx) => {
            if (ann.type === 'label') {
                drawLabelDot(ctx, ann.x, ann.y, idx + 1, invScale, editingIdx === idx)
            } else if (ann.type === 'question') {
                drawQuestionDot(ctx, ann.x, ann.y, invScale, editingIdx === idx, ann.status)
            }
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
            const ann = annotations[dotIdx]
            setEditText(ann.type === 'label' ? ann.text : (ann as any).text || '')
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
        onChange([...annotations, { type: 'label', x: coords.x, y: coords.y, text: '' } as LabelAnnotation])
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

        const ann = annotations[editingIdx]

        if (ann.type === 'label') {
            if (!editText.trim()) {
                const next = [...annotations]
                next.splice(editingIdx, 1)
                onChange(next)
            } else {
                const updated = [...annotations]
                updated[editingIdx] = { ...updated[editingIdx], text: editText.trim() } as LabelAnnotation
                onChange(updated)
            }
        } else if (ann.type === 'question') {
            if (editText.trim()) {
                // Update local annotation status first
                const updated = [...annotations]
                updated[editingIdx] = { ...updated[editingIdx], status: 'answered', text: editText.trim() } as any
                onChange(updated)

                // Check if all questions are now answered
                const pendingCount = updated.filter(a => a.type === 'question' && a.status === 'pending').length

                if (pendingCount === 0) {
                    // All questions answered, submit combined response to chat
                    const chatStore = useChatStore.getState()
                    const workflowStore = useWorkflowStore.getState()
                    const { pendingImage } = workflowStore

                    // Format a combined message
                    const answeredQuestions = updated.filter(a => a.type === 'question')
                    let combinedMessage = "I have answered all your questions on the image:\n"

                    answeredQuestions.forEach((q: any, i) => {
                        combinedMessage += `\nQ${i + 1}: ${q.question}\nA: ${q.text}\n`
                    })

                    chatStore.sendUserMessage(combinedMessage)
                    sendChatMessage(
                        combinedMessage,
                        chatStore.conversationId,
                        pendingImage || undefined,
                        updated
                    )
                } else {
                    // Show a toast so the user isn't confused why the chat isn't responding yet
                    import('react-hot-toast').then(({ toast }) => {
                        toast.success(`Answer saved. ${pendingCount} question${pendingCount > 1 ? 's' : ''} remaining.`)
                    })
                }
            }
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
        const ann = annotations[editingIdx!]
        // If the dot has no text (just placed label), delete it
        if (ann?.type === 'label' && !(ann as LabelAnnotation).text && !editText.trim()) {
            const next = [...annotations]
            next.splice(editingIdx!, 1)
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
                        width={canvasW * (window.devicePixelRatio || 1)}
                        height={canvasH * (window.devicePixelRatio || 1)}
                        className="annotator-canvas"
                        style={{ width: `${canvasW}px`, height: `${canvasH}px`, cursor: getCursor() }}
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

            {/* LEMON-style modal for editing label text or answering LLM questions */}
            {editingIdx != null && editingIdx < annotations.length && (
                <div className="modal open">
                    <div className="modal-backdrop" onClick={handleModalClose} />
                    <div className="modal-content annotation-modal">
                        <div className="modal-header">
                            <h2>
                                {annotations[editingIdx].type === 'label'
                                    ? `Label #${editingIdx + 1}`
                                    : 'LLM Question'}
                            </h2>
                            <button className="modal-close" onClick={handleModalClose}>×</button>
                        </div>
                        <div className="modal-body">
                            {annotations[editingIdx].type === 'question' && (
                                <div className="form-group" style={{ marginBottom: '16px' }}>
                                    <label>Question</label>
                                    <div className="annotation-question-text" style={{ padding: '12px', background: 'var(--surface-color)', borderRadius: '6px', fontSize: '14px', border: '1px solid var(--border-color)', color: 'var(--text-color)' }}>
                                        {(annotations[editingIdx] as QuestionAnnotation).question}
                                    </div>
                                </div>
                            )}
                            <div className="form-group">
                                <label htmlFor="annotation-text">
                                    {annotations[editingIdx].type === 'label' ? 'Annotation Text' : 'Your Answer'}
                                </label>
                                <textarea
                                    id="annotation-text"
                                    value={editText}
                                    onChange={(e) => setEditText(e.target.value)}
                                    placeholder={annotations[editingIdx].type === 'label' ? "Enter clarification text for this label..." : "Type your answer here..."}
                                    rows={4}
                                    autoFocus
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                            handleModalSave()
                                        }
                                    }}
                                />
                                <small className="muted">
                                    Position: ({annotations[editingIdx].x}, {annotations[editingIdx].y})
                                    {' · Ctrl+Enter to save'}
                                </small>
                            </div>
                            <div className="form-actions">
                                {annotations[editingIdx].type === 'label' && (
                                    <button className="ghost" onClick={handleModalDelete}>
                                        Delete
                                    </button>
                                )}
                                <button className="ghost" onClick={handleModalClose}>
                                    Cancel
                                </button>
                                <button className="primary" onClick={handleModalSave}>
                                    {annotations[editingIdx].type === 'label' ? 'Save Label' : 'Submit Answer'}
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

    if (isActive) {
        ctx.beginPath()
        ctx.arc(x, y, r * 1.5, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(255, 179, 0, 0.2)'
        ctx.fill()
    }

    // Shadow
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)'
    ctx.shadowBlur = 6 * invScale
    ctx.shadowOffsetY = 3 * invScale
    ctx.shadowOffsetX = 0

    // Outer white rim
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = '#FFFFFF'
    ctx.fill()

    // Clear shadow for next layers
    ctx.shadowColor = 'transparent'

    // Inner filled dot
    ctx.beginPath()
    ctx.arc(x, y, r - 2 * invScale, 0, Math.PI * 2)
    ctx.fillStyle = isActive ? DOT_COLOR_ACTIVE : DOT_COLOR
    ctx.fill()

    // Number
    const fontSize = Math.max(10, r * 0.9) // minimum 10px scaled
    ctx.font = `600 ${fontSize}px "Space Grotesk", "Roboto", sans-serif`
    ctx.fillStyle = 'rgba(0, 0, 0, 0.87)' // Material typography primary
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(number), x, y + (0.5 * invScale))

    ctx.restore()
}

function drawQuestionDot(
    ctx: CanvasRenderingContext2D,
    x: number, y: number,
    invScale: number,
    isActive: boolean,
    status: 'pending' | 'answered',
) {
    const r = DOT_RADIUS * invScale
    ctx.save()

    let fill = status === 'pending' ? '#2196F3' : '#4CAF50'
    if (isActive) {
        fill = status === 'pending' ? '#64B5F6' : '#81C784'
        ctx.beginPath()
        ctx.arc(x, y, r * 1.5, 0, Math.PI * 2)
        ctx.fillStyle = status === 'pending' ? 'rgba(33, 150, 243, 0.2)' : 'rgba(76, 175, 80, 0.2)'
        ctx.fill()
    }

    // Shadow
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)'
    ctx.shadowBlur = 6 * invScale
    ctx.shadowOffsetY = 3 * invScale
    ctx.shadowOffsetX = 0

    // Outer white rim
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fillStyle = '#FFFFFF'
    ctx.fill()

    // Clear shadow for next layers
    ctx.shadowColor = 'transparent'

    // Inner filled dot
    ctx.beginPath()
    ctx.arc(x, y, r - 2 * invScale, 0, Math.PI * 2)
    ctx.fillStyle = fill
    ctx.fill()

    // Mark (?) or (✓)
    const fontSize = Math.max(10, r * 1.1)
    ctx.font = `600 ${fontSize}px "Space Grotesk", "Roboto", sans-serif`
    ctx.fillStyle = '#FFFFFF'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(status === 'pending' ? '?' : '✓', x, y + (0.5 * invScale))

    ctx.restore()
}
