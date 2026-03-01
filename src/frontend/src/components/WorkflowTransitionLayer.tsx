import { useEffect } from 'react'
import { useUIStore } from '../stores/uiStore'
import '../styles/WorkflowTransitionLayer.css'

export default function WorkflowTransitionLayer() {
    const { zoomingCard, setZoomingCard, zoomPhase, setZoomPhase, revealWorkspace, setIsTransitioning } = useUIStore()

    useEffect(() => {
        if (zoomingCard && zoomPhase === 'idle') {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    setZoomPhase('expanding')
                })
            })
        }
    }, [zoomingCard, zoomPhase, setZoomPhase])

    useEffect(() => {
        if (zoomPhase === 'fading') {
            setIsTransitioning(true)
            revealWorkspace()

            const endTimer = setTimeout(() => {
                setIsTransitioning(false)
                setZoomingCard(null)
                setZoomPhase('idle')
            }, 400) // Wait for full 400ms animation to complete

            return () => {
                clearTimeout(endTimer)
            }
        }
    }, [zoomPhase, setZoomingCard, setZoomPhase, revealWorkspace, setIsTransitioning])

    if (!zoomingCard) return null

    const isExpanding = zoomPhase === 'expanding' || zoomPhase === 'fading'
    const isFading = zoomPhase === 'fading'

    // Initial style matches the card bounds
    const style: React.CSSProperties = isExpanding
        ? {
            top: '0px',
            left: '0px',
            width: '100vw',
            height: '100vh',
            borderRadius: '0px',
            backgroundColor: 'var(--bg)', // matches app background
            backgroundImage: 'radial-gradient(rgba(31, 36, 34, 0.15) 1.5px, transparent 1.5px)',
            backgroundSize: '20px 20px',
            backgroundPosition: '0 0',
            boxShadow: 'none',
            opacity: isFading ? 0 : 1
        }
        : {
            top: `${zoomingCard.rect.top}px`,
            left: `${zoomingCard.rect.left}px`,
            width: `${zoomingCard.rect.width}px`,
            height: `${zoomingCard.rect.height}px`,
            borderRadius: '16px',
            backgroundColor: 'var(--paper)', // matches card background
            backgroundImage: 'none',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
            opacity: 1
        }

    return (
        <div
            className="workflow-transition-layer"
            style={style}
        >
            <div
                className="workflow-transition-content"
                style={{
                    opacity: isExpanding ? 0 : 1, // Fades out the title as it expands
                    transition: 'opacity 0.2s ease'
                }}
            >
                <h4 style={{ margin: 0, fontSize: '1.1rem', padding: '20px' }}>
                    {zoomingCard.title}
                </h4>
            </div>
        </div>
    )
}
