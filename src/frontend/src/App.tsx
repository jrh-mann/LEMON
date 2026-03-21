import { Toaster } from 'react-hot-toast'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './styles.css'
import AuthPage from './components/AuthPage'
import Header from './components/Header'
import WorkflowPage from './components/WorkflowPage'
import LibraryPage from './components/LibraryPage'
import ExportPage from './components/ExportPage'
import WorkflowTransitionLayer from './components/WorkflowTransitionLayer'
import { ErrorBoundary } from './components/ErrorBoundary'

function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <div className="backdrop"></div>
        <Toaster position="bottom-right" toastOptions={{
          style: {
            background: 'var(--surface-color, var(--paper))',
            color: 'var(--text-color, var(--ink))',
            border: '1px solid var(--border-color, var(--edge))'
          }
        }} />

        <Routes>
          {/* Auth page - no header */}
          <Route path="/auth" element={<AuthPage />} />

          {/* All other pages - with header */}
          <Route path="*" element={
            <div className="page-transition-wrapper">
              <Header />
              <Routes>
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/export" element={<ExportPage />} />
                <Route path="/workflow/:id?" element={<WorkflowPage />} />
                <Route path="/" element={<Navigate to="/workflow" replace />} />
                <Route path="*" element={<Navigate to="/workflow" replace />} />
              </Routes>
            </div>
          } />
        </Routes>

        <WorkflowTransitionLayer />
      </ErrorBoundary>
    </BrowserRouter>
  )
}

export default App

