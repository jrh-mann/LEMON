import { useEffect } from 'react'

// Dependencies required by the keyboard shortcuts hook.
interface CanvasKeyboardDeps {
  selectedNodeIds: string[]
  deleteNode: (id: string) => void
  undo: () => void
  redo: () => void
  connectMode: boolean
  cancelConnect: () => void
  clearSelection: () => void
  setCanvasMode: (mode: 'select' | 'pan') => void
}

// Keyboard shortcut handler for the canvas.
// Attaches a global keydown listener that maps keys to canvas actions:
//   Delete/Backspace  — delete selected nodes
//   Cmd/Ctrl+Z        — undo (+ Shift = redo)
//   Escape            — cancel connect mode or clear selection
//   V / H             — switch canvas mode to select / pan
// Ignores keystrokes while the user is typing in an input or textarea.
export function useCanvasKeyboard(deps: CanvasKeyboardDeps): void {
  const {
    selectedNodeIds,
    deleteNode,
    undo,
    redo,
    connectMode,
    cancelConnect,
    clearSelection,
    setCanvasMode,
  } = deps

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore shortcuts when typing in input fields
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }

      // Delete selected nodes
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeIds.length > 0) {
        selectedNodeIds.forEach(nodeId => deleteNode(nodeId))
      }

      // Undo/Redo
      if (e.key === 'z' && (e.metaKey || e.ctrlKey)) {
        if (e.shiftKey) {
          redo()
        } else {
          undo()
        }
      }

      // Cancel connect mode or clear selection
      if (e.key === 'Escape') {
        if (connectMode) {
          cancelConnect()
        } else if (selectedNodeIds.length > 0) {
          clearSelection()
        }
      }

      // Canvas mode shortcuts (V for select, H for pan/hand)
      if (e.key === 'v' || e.key === 'V') {
        setCanvasMode('select')
      }
      if (e.key === 'h' || e.key === 'H') {
        setCanvasMode('pan')
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNodeIds, deleteNode, undo, redo, connectMode, cancelConnect, clearSelection, setCanvasMode])
}
