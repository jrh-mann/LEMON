import { useEffect, useState } from 'react'
import { Toaster } from 'react-hot-toast'
import './styles.css'
import AuthPage from './components/AuthPage'
import Header from './components/Header'
import WorkflowPage from './components/WorkflowPage'
import LibraryPage from './components/LibraryPage'
import ExportPage from './components/ExportPage'

type Route = 'auth' | 'workflow' | 'library' | 'export'

function parseRoute(): Route {
  const hash = window.location.hash
  if (hash.startsWith('#/auth') || hash === '#auth') return 'auth'
  if (hash.startsWith('#/library')) return 'library'
  if (hash.startsWith('#/export')) return 'export'
  // Both home and workflow now go to the unified WorkflowPage
  return 'workflow'
}

function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute())

  useEffect(() => {
    const handleHashChange = () => setRoute(parseRoute())
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  return (
    <>
      <div className="backdrop"></div>
      <Toaster position="bottom-right" toastOptions={{
        style: {
          background: 'var(--surface-color, var(--paper))',
          color: 'var(--text-color, var(--ink))',
          border: '1px solid var(--border-color, var(--edge))'
        }
      }} />
      {route === 'auth' ? (
        <AuthPage />
      ) : (
        <div className="page-transition-wrapper">
          <Header />
          {route === 'workflow' && <WorkflowPage />}
          {route === 'library' && <LibraryPage />}
          {route === 'export' && <ExportPage />}
        </div>
      )}
    </>
  )
}

export default App

