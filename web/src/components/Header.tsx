import { useRef, useCallback } from 'react'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useChatStore } from '../stores/chatStore'
import { sendChatMessage } from '../api/socket'

export default function Header() {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { openModal } = useUIStore()
  const { currentWorkflow, flowchart } = useWorkflowStore()
  const { conversationId, sendUserMessage } = useChatStore()

  // Handle image upload
  const handleImageUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      // Read file as base64
      const reader = new FileReader()
      reader.onload = () => {
        const base64 = reader.result as string

        // Add user message
        sendUserMessage(`Analyze this workflow image: ${file.name}`)

        // Send to backend via socket with image
        sendChatMessage(
          `Please analyze this workflow image and extract the inputs, outputs, and decision logic.`,
          conversationId,
          base64
        )
      }
      reader.readAsDataURL(file)

      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    },
    [conversationId, sendUserMessage]
  )

  // Handle export
  const handleExport = useCallback(() => {
    if (!currentWorkflow && flowchart.nodes.length === 0) return

    const exportData = currentWorkflow || {
      id: 'draft',
      metadata: {
        name: 'Draft Workflow',
        description: '',
        tags: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        validation_score: 0,
        validation_count: 0,
        is_validated: false,
      },
      flowchart,
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${exportData.metadata?.name || 'workflow'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [currentWorkflow, flowchart])

  const canExport = currentWorkflow || flowchart.nodes.length > 0

  return (
    <header className="app-header">
      <div className="logo">
        <span className="logo-mark">L</span>
        <span className="logo-text">LEMON</span>
      </div>

      <div className="header-actions">
        <button className="ghost" onClick={() => openModal('library')}>
          Browse Library
        </button>

        <label className="ghost upload-label" htmlFor="imageUpload">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          Upload Image
        </label>
        <input
          ref={fileInputRef}
          type="file"
          id="imageUpload"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={handleImageUpload}
        />

        <button
          className="primary"
          disabled={!canExport}
          onClick={handleExport}
          title={canExport ? 'Export workflow as JSON' : 'No workflow to export'}
        >
          Export
        </button>
      </div>
    </header>
  )
}
