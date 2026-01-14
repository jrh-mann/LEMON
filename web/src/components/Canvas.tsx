export default function Canvas() {
  return (
    <div className="canvas-area">
      {/* Workspace tabs */}
      <div className="workspace-tabs" id="workspaceTabs">
        {/* Tabs will be populated dynamically */}
      </div>

      <div className="canvas-container" id="canvasContainer">
        <svg id="flowchartCanvas" viewBox="0 0 1200 800">
          <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
              <polygon points="0 0, 10 3.5, 0 7" fill="var(--ink)"></polygon>
            </marker>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--edge)" strokeWidth="0.5" opacity="0.5"/>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)"/>
          <g id="imageLayer"></g>
          <g id="edgeLayer"></g>
          <g id="nodeLayer"></g>
        </svg>

        {/* Empty state overlay */}
        <div className="canvas-empty" id="canvasEmpty">
          <div className="empty-content">
            <div className="empty-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 5v14M5 12h14"/>
              </svg>
            </div>
            <h2>Start building</h2>
            <p>Drag blocks from the left, or describe your workflow below</p>
          </div>
        </div>

        {/* Zoom controls */}
        <div className="zoom-controls">
          <button className="zoom-btn" id="zoomIn" title="Zoom in (+)">+</button>
          <button className="zoom-btn" id="zoomReset" title="Reset zoom (0)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"/>
            </svg>
          </button>
          <button className="zoom-btn" id="zoomOut" title="Zoom out (-)">-</button>
        </div>

        {/* Meta controls */}
        <div className="meta-controls">
          <button className="meta-btn" id="autoArrangeBtn" title="Auto-arrange">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
              <polyline points="7.5 4.21 12 6.81 16.5 4.21"/>
              <polyline points="7.5 19.79 7.5 14.6 3 12"/>
              <polyline points="21 12 16.5 14.6 16.5 19.79"/>
              <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
              <line x1="12" y1="22.08" x2="12" y2="12"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
