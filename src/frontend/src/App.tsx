import { useEffect } from 'react'
import './styles.css'
import Header from './components/Header'
import TabBar from './components/TabBar'
import Palette from './components/Palette'
import Canvas from './components/Canvas'
import RightSidebar from './components/RightSidebar'
import Chat from './components/Chat'
import Modals from './components/Modals'
import { useSession } from './hooks/useSession'
import { useUIStore } from './stores/uiStore'

function App() {
  // Initialize session and socket connection
  useSession()

  const { error, clearError } = useUIStore()

  // Show error toast
  useEffect(() => {
    if (error) {
      const timer = setTimeout(clearError, 5000)
      return () => clearTimeout(timer)
    }
  }, [error, clearError])

  return (
    <>
      <div className="backdrop"></div>

      <div className="app-layout">
        <Header />
        <TabBar />

        <main className="workspace">
          <Palette />
          <Canvas />
          <RightSidebar />
        </main>
      </div>

      <Chat />
      <Modals />

      {/* Error toast */}
      {error && (
        <div className="error-toast" onClick={clearError}>
          <span>{error}</span>
          <button className="toast-close">×</button>
        </div>
      )}
    </>
  )
}

export default App
