export default function Palette() {
  return (
    <aside className="sidebar palette-sidebar">
      <div className="sidebar-section">
        <p className="eyebrow">BLOCKS</p>
        <div className="block-palette">
          <button className="palette-block" data-type="start" draggable="true">
            <div className="block-icon start-icon"></div>
            <span>Start</span>
          </button>
          <button className="palette-block" data-type="decision" draggable="true">
            <div className="block-icon decision-icon"></div>
            <span>Decision</span>
          </button>
          <button className="palette-block" data-type="output" draggable="true">
            <div className="block-icon output-icon"></div>
            <span>Output</span>
          </button>
          <button className="palette-block" data-type="subflow" draggable="true">
            <div className="block-icon subflow-icon"></div>
            <span>Subflow</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
