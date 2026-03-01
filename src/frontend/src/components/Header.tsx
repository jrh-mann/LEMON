import { useRef, useCallback } from 'react'
import { ApiError } from '../api/client'
import { logoutUser } from '../api/auth'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import toast from 'react-hot-toast'

export default function Header() {
  const { openModal, setError, devMode, toggleDevMode } = useUIStore()
  const { currentWorkflow, flowchart } = useWorkflowStore()

  // Secret dev mode activation: 20 rapid clicks on LEMON logo
  const clickCountRef = useRef(0)
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleLogoClick = useCallback(() => {
    clickCountRef.current += 1

    // Reset counter after 5 seconds of inactivity
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current)
    clickTimerRef.current = setTimeout(() => {
      clickCountRef.current = 0
    }, 5000)

    if (clickCountRef.current >= 20) {
      clickCountRef.current = 0
      toggleDevMode()
      toast(devMode ? 'Developer mode disabled' : 'Developer mode enabled', {
        icon: devMode ? '🔒' : '🔧',
        duration: 2000,
      })
    }
  }, [devMode, toggleDevMode])

  const canExport = currentWorkflow || flowchart.nodes.length > 0

  const handleLogout = useCallback(async () => {
    try {
      await logoutUser()
      window.location.hash = '#/auth'
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Sign out failed.'
      setError(message)
    }
  }, [setError])

  return (
    <header className="app-header">
      <div className="logo" onClick={handleLogoClick} style={{ cursor: 'pointer', position: 'relative' }}>
        <span className="logo-mark">L</span>
        <span className="logo-text">LEMON</span>
        {devMode && (
          <span style={{
            position: 'absolute',
            top: 2,
            right: -6,
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'var(--green)',
            border: '2px solid var(--paper)',
          }} />
        )}
      </div>

      <div className="header-actions">
        <button className="ghost" onClick={() => { window.location.hash = '#/library' }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
          </svg>
          Browse Library
        </button>

        <button
          className="primary"
          disabled={!canExport}
          onClick={() => openModal('save')}
          title={canExport ? 'Save workflow to library' : 'No workflow to save'}
        >
          Save
        </button>

        <button
          className="ghost"
          disabled={!canExport}
          onClick={() => { window.location.hash = '#/export' }}
          title={canExport ? 'Export workflow' : 'No workflow to export'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Export
        </button>

        <button className="ghost" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </header>
  )
}
