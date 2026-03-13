import type { RefObject } from 'react'
import { useRef, useEffect } from 'react'

// Zoom boundaries for the canvas viewport.
const MIN_ZOOM = 0.25
const MAX_ZOOM = 8

// Mouse-wheel zoom handler for the canvas SVG element.
// Zooms centred on the cursor position so the point under the pointer stays
// fixed. The listener is attached via useEffect with { passive: false }
// because React's synthetic onWheel is passive by default, which makes
// e.preventDefault() a no-op and lets the page scroll through the canvas.
export function useWheelZoom(
  svgRef: RefObject<SVGSVGElement | null>,
  containerRef: RefObject<HTMLDivElement | null>,
  zoom: number,
  panOffset: { x: number; y: number },
  setZoom: (zoom: number) => void,
  setPanOffset: (offset: { x: number; y: number }) => void,
  screenToSVG: (clientX: number, clientY: number) => { x: number; y: number },
): void {
  // Stable ref so the non-passive listener always calls the latest closure
  // without needing to re-attach on every render.
  const handleWheelRef = useRef<(e: WheelEvent) => void>(() => {})

  useEffect(() => {
    handleWheelRef.current = (e: WheelEvent) => {
      e.preventDefault()

      const svg = svgRef.current
      const container = containerRef.current
      if (!svg || !container) return

      const zoomFactor = 0.1
      const delta = e.deltaY > 0 ? -zoomFactor : zoomFactor
      const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom + delta))
      if (newZoom === zoom) return

      const cursorSVG = screenToSVG(e.clientX, e.clientY)
      const zoomRatio = zoom / newZoom
      const newPanX = panOffset.x + cursorSVG.x * (1 - zoomRatio)
      const newPanY = panOffset.y + cursorSVG.y * (1 - zoomRatio)

      setZoom(newZoom)
      setPanOffset({ x: newPanX, y: newPanY })
    }
  }, [containerRef, panOffset.x, panOffset.y, screenToSVG, setPanOffset, setZoom, svgRef, zoom])

  // Attach non-passive wheel listener to the SVG element
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const handler = (e: WheelEvent) => handleWheelRef.current(e)
    svg.addEventListener('wheel', handler, { passive: false })
    return () => svg.removeEventListener('wheel', handler)
  }, [svgRef])
}
