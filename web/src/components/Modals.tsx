export default function Modals() {
  return (
    <>
      {/* Library Modal */}
      <div className="modal" id="libraryModal">
        <div className="modal-backdrop"></div>
        <div className="modal-content">
          <div className="modal-header">
            <h2>Workflow Library</h2>
            <button className="modal-close" id="closeLibrary">×</button>
          </div>
          <div className="modal-body">
            <div className="library-grid" id="libraryGrid">
              {/* Library items populated by JS */}
            </div>
          </div>
        </div>
      </div>

      {/* Validation Modal */}
      <div className="modal" id="validationModal">
        <div className="modal-backdrop"></div>
        <div className="modal-content">
          <div className="modal-header">
            <h2 id="validationTitle">Validate Workflow</h2>
            <button className="modal-close" id="closeValidation">×</button>
          </div>
          <div className="modal-body">
            <div id="validationCase">
              {/* Validation case populated by JS */}
            </div>
          </div>
        </div>
      </div>

      {/* Context Menus */}
      <div className="context-menu" id="nodeContextMenu">
        <button className="context-menu-item" data-action="edit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
          Edit Label
        </button>
        <button className="context-menu-item" data-action="delete">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
          Delete
        </button>
      </div>

      <div className="context-menu" id="edgeContextMenu">
        <button className="context-menu-item" data-action="delete">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
          Delete
        </button>
      </div>
    </>
  )
}
