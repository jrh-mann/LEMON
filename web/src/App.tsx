import './styles.css'
import Header from './components/Header'
import Palette from './components/Palette'
import Canvas from './components/Canvas'
import RightSidebar from './components/RightSidebar'
import Chat from './components/Chat'
import Modals from './components/Modals'

function App() {
  return (
    <>
      <div className="backdrop"></div>

      <div className="app-layout">
        <Header />

        <main className="workspace">
          <Palette />
          <Canvas />
          <RightSidebar />
        </main>
      </div>

      <Chat />
      <Modals />
    </>
  )
}

export default App
