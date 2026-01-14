export default function Header() {
  return (
    <header className="app-header">
      <div className="logo">
        <span className="logo-mark">L</span>
        <span className="logo-text">LEMON</span>
      </div>
      <div className="header-actions">
        <button className="ghost">Browse Library</button>
        <label className="ghost upload-label" htmlFor="imageUpload">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          Upload Image
        </label>
        <input type="file" id="imageUpload" accept="image/*" style={{ display: 'none' }} />
        <button className="primary" disabled>Export</button>
      </div>
    </header>
  )
}
