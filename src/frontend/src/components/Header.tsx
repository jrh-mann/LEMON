import { useRef, useCallback, useState } from 'react'
import { ApiError } from '../api/client'
import { logoutUser } from '../api/auth'
import { validateWorkflow } from '../api/workflows'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { addAssistantMessage } from '../stores/chatStore'

export default function Header() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isValidating, setIsValidating] = useState(false)

  const { openModal, setError } = useUIStore()
  const { currentWorkflow, flowchart, setPendingImage, currentAnalysis } = useWorkflowStore()

  // Handle image upload - just store the image, don't auto-analyse
  const handleImageUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      // Read file as base64
      const reader = new FileReader()
      reader.onload = () => {
        const base64 = reader.result as string

        // Store image in state for later use
        setPendingImage(base64, file.name)

        // Add assistant message prompting user to ask for analysis
        addAssistantMessage(
          `Image "${file.name}" uploaded. You can now ask me to analyse it, for example:\n\n` +
          `- "Analyse this workflow image"\n` +
          `- "Analyse this image, focus on the decision logic for diabetic patients"\n` +
          `- "Extract the inputs and outputs from this flowchart"`
        )
      }
      reader.readAsDataURL(file)

      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    },
    [setPendingImage]
  )

  // Handle export
  const handleExport = useCallback(async () => {
    if (!currentWorkflow && flowchart.nodes.length === 0) return

    setIsValidating(true)

    try {
      // Validate workflow first
      const validationResult = await validateWorkflow({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        inputs: currentAnalysis?.inputs || [],
      })

      if (!validationResult.valid) {
        // Show validation errors and ask for confirmation
        const errorMessages = validationResult.errors
          ?.map(e => `• ${e.code}: ${e.message}${e.node_id ? ` (Node: ${e.node_id})` : ''}`)
          .join('\n')

        const proceed = confirm(
          `⚠️ Workflow Validation Failed\n\n${errorMessages}\n\nDo you want to export anyway?`
        )

        if (!proceed) {
          setIsValidating(false)
          return
        }
      }

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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed')
    } finally {
      setIsValidating(false)
    }
  }, [currentWorkflow, flowchart, currentAnalysis, setError])

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
          onClick={() => openModal('save')}
          title={canExport ? 'Save workflow to library' : 'No workflow to save'}
        >
          Save
        </button>

        <button
          className="ghost"
          disabled={!canExport || isValidating}
          onClick={handleExport}
          title={canExport ? 'Export workflow as JSON' : 'No workflow to export'}
        >
          {isValidating ? 'Validating...' : 'Export'}
        </button>

        <button className="ghost" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </header>
  )
}
