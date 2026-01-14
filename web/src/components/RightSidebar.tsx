import WorkflowBrowser from './WorkflowBrowser'

export default function RightSidebar() {
  return (
    <aside className="sidebar library-sidebar">
      <div className="sidebar-tabs">
        <button className="sidebar-tab active" data-tab="library">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          </svg>
          <span>Library</span>
        </button>
        <button className="sidebar-tab" data-tab="inputs">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="12" y1="18" x2="12" y2="12"/>
            <line x1="9" y1="15" x2="15" y2="15"/>
          </svg>
          <span>Inputs</span>
        </button>
      </div>

      {/* Library panel */}
      <div className="sidebar-panel" id="libraryPanel" data-panel="library">
        <WorkflowBrowser />
      </div>

      {/* Inputs panel */}
      <div className="sidebar-panel hidden" id="inputsPanel" data-panel="inputs">
        <div className="inputs-empty" id="inputsEmpty">
          <p className="muted">No inputs defined.</p>
          <p className="muted small">Create or load a workflow to see its inputs.</p>
        </div>
        <div className="inputs-list" id="inputsList">
          {/* Input items loaded by JS */}
        </div>
      </div>
    </aside>
  )
}
