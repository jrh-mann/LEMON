import { useRef, useCallback, useState, useEffect } from 'react'
import { ApiError } from '../api/client'
import { logoutUser } from '../api/auth'
import { validateWorkflow, compileToPython } from '../api/workflows'
import { useUIStore } from '../stores/uiStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { addAssistantMessage } from '../stores/chatStore'

function estimateDataUrlBytes(dataUrl: string): number {
  const comma = dataUrl.indexOf(',')
  const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
  let padding = 0
  if (b64.endsWith('==')) padding = 2
  else if (b64.endsWith('=')) padding = 1
  return Math.max(0, Math.floor((b64.length * 3) / 4) - padding)
}

async function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return await new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Failed to load image for resizing'))
    img.src = dataUrl
  })
}

async function compressDataUrl(
  dataUrl: string,
  opts: {
    maxBytes: number
    maxDimension: number
  }
): Promise<{ dataUrl: string; didChange: boolean; bytes: number }> {
  const { maxBytes, maxDimension } = opts
  const originalBytes = estimateDataUrlBytes(dataUrl)
  if (originalBytes <= maxBytes) {
    return { dataUrl, didChange: false, bytes: originalBytes }
  }

  const img = await loadImage(dataUrl)
  const w = img.naturalWidth || img.width
  const h = img.naturalHeight || img.height
  const scale = Math.min(1, maxDimension / Math.max(w, h))
  const outW = Math.max(1, Math.round(w * scale))
  const outH = Math.max(1, Math.round(h * scale))

  const canvas = document.createElement('canvas')
  canvas.width = outW
  canvas.height = outH
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Failed to create canvas context for image resizing')

  ctx.drawImage(img, 0, 0, outW, outH)

  // Default to JPEG for large payloads: smaller and more likely to fit through Socket.IO polling limits.
  let quality = 0.9
  let next = canvas.toDataURL('image/jpeg', quality)
  let nextBytes = estimateDataUrlBytes(next)

  while (nextBytes > maxBytes && quality > 0.6) {
    quality = Math.max(0.6, quality - 0.05)
    next = canvas.toDataURL('image/jpeg', quality)
    nextBytes = estimateDataUrlBytes(next)
  }

  return { dataUrl: next, didChange: true, bytes: nextBytes }
}

export default function Header() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const exportDropdownRef = useRef<HTMLDivElement>(null)
  const [isValidating, setIsValidating] = useState(false)
  const [showExportDropdown, setShowExportDropdown] = useState(false)

  const { openModal, setError, devMode, toggleDevMode } = useUIStore()
  const { currentWorkflow, flowchart, setPendingImage, currentAnalysis } = useWorkflowStore()

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportDropdownRef.current && !exportDropdownRef.current.contains(event.target as Node)) {
        setShowExportDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Handle image upload - just store the image, don't auto-analyse
  const handleImageUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return

      // Read file as base64 data URL. This is later sent to backend inside the `chat` socket payload.
      // In production (Azure), large payloads can be rejected by proxies/buffers; we proactively compress.
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          const original = reader.result as string

          // Keep a conservative limit because the chat payload also includes workflow state.
          const MAX_BYTES = 7 * 1024 * 1024
          const MAX_DIMENSION = 2000

          const { dataUrl, didChange, bytes } = await compressDataUrl(original, {
            maxBytes: MAX_BYTES,
            maxDimension: MAX_DIMENSION,
          })

          if (bytes > MAX_BYTES) {
            setError(
              `Image is too large to send (${(bytes / (1024 * 1024)).toFixed(1)}MB). ` +
              `Try a smaller screenshot or export as JPG, then re-upload.`
            )
            return
          }

          // Store image in state for later use
          setPendingImage(dataUrl, file.name)

          const note = didChange
            ? ` (resized/compressed to ${(bytes / (1024 * 1024)).toFixed(1)}MB)`
            : ''

          // Add assistant message prompting user to ask for analysis
          addAssistantMessage(
            `Image "${file.name}" uploaded${note}. You can now ask me to analyse it, for example:\n\n` +
            `- "Analyse this workflow image"\n` +
            `- "Analyse this image, focus on the decision logic for diabetic patients"\n` +
            `- "Extract the inputs and outputs from this flowchart"`
          )
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to process uploaded image')
        }
      }
      reader.readAsDataURL(file)

      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    },
    [setPendingImage, setError]
  )

  // Handle JSON export
  const handleExportJSON = useCallback(async () => {
    if (!currentWorkflow && flowchart.nodes.length === 0) return

    setIsValidating(true)
    setShowExportDropdown(false)

    try {
      // Validate workflow first
      const validationResult = await validateWorkflow({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],
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

      // Build export data with analysis (variables/outputs)
      const exportData = {
        id: currentWorkflow?.id || 'draft',
        metadata: currentWorkflow?.metadata || {
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
        // Include analysis data so variables are preserved on import
        variables: currentAnalysis?.variables || [],
        outputs: currentAnalysis?.outputs || [],
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

  // Handle PNG export - captures the flowchart canvas as an image
  const handleExportPNG = useCallback(async () => {
    setShowExportDropdown(false)
    setIsValidating(true)

    try {
      const svgElement = document.getElementById('flowchartCanvas') as unknown as SVGSVGElement
      if (!svgElement) {
        throw new Error('Flowchart canvas not found')
      }

      // Get CSS variable values from computed styles
      const computedStyle = getComputedStyle(document.documentElement)
      const cssVars: Record<string, string> = {
        '--ink': computedStyle.getPropertyValue('--ink').trim() || '#1f2422',
        '--paper': computedStyle.getPropertyValue('--paper').trim() || '#faf8f4',
        '--cream': computedStyle.getPropertyValue('--cream').trim() || '#f5f1e8',
        '--edge': computedStyle.getPropertyValue('--edge').trim() || '#e4d9c7',
        '--muted': computedStyle.getPropertyValue('--muted').trim() || '#8a8577',
        '--teal': computedStyle.getPropertyValue('--teal').trim() || '#1f6e68',
        '--teal-light': computedStyle.getPropertyValue('--teal-light').trim() || 'rgba(31, 110, 104, 0.12)',
        '--amber': computedStyle.getPropertyValue('--amber').trim() || '#c98a2c',
        '--amber-light': computedStyle.getPropertyValue('--amber-light').trim() || 'rgba(201, 138, 44, 0.15)',
        '--green': computedStyle.getPropertyValue('--green').trim() || '#3e7c4d',
        '--green-light': computedStyle.getPropertyValue('--green-light').trim() || 'rgba(62, 124, 77, 0.15)',
        '--rose': computedStyle.getPropertyValue('--rose').trim() || '#c25d6a',
        '--rose-light': computedStyle.getPropertyValue('--rose-light').trim() || 'rgba(194, 93, 106, 0.15)',
        '--sky': computedStyle.getPropertyValue('--sky').trim() || '#4a90a4',
        '--sky-light': computedStyle.getPropertyValue('--sky-light').trim() || 'rgba(74, 144, 164, 0.15)',
      }

      // Clone the SVG element
      const clonedSvg = svgElement.cloneNode(true) as SVGSVGElement

      // Remove connection port circles (drag handles) from the export
      const connectionPorts = clonedSvg.querySelectorAll('.connection-port')
      connectionPorts.forEach(port => port.remove())

      // Replace CSS variables with actual values in the cloned SVG
      const replaceVars = (str: string): string => {
        let result = str
        for (const [varName, value] of Object.entries(cssVars)) {
          result = result.replace(new RegExp(`var\\(${varName}\\)`, 'g'), value)
        }
        return result
      }

      // Process all elements in the cloned SVG
      const processElement = (el: Element) => {
        // Process inline styles
        if (el instanceof SVGElement || el instanceof HTMLElement) {
          const style = el.getAttribute('style')
          if (style) {
            el.setAttribute('style', replaceVars(style))
          }
        }

        // Process fill, stroke, and other attributes
        const attrs = ['fill', 'stroke', 'stop-color', 'flood-color', 'lighting-color']
        for (const attr of attrs) {
          const value = el.getAttribute(attr)
          if (value && value.includes('var(')) {
            el.setAttribute(attr, replaceVars(value))
          }
        }

        // Recursively process children
        for (const child of el.children) {
          processElement(child)
        }
      }

      processElement(clonedSvg)

      // Get viewBox dimensions
      const viewBox = svgElement.viewBox.baseVal
      const scale = 2 // Export at 2x resolution for crisp images
      const width = viewBox.width * scale
      const height = viewBox.height * scale

      // Set explicit dimensions on the cloned SVG
      clonedSvg.setAttribute('width', String(width))
      clonedSvg.setAttribute('height', String(height))

      // Add background rectangle (cream color to match canvas)
      const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
      bgRect.setAttribute('width', '100%')
      bgRect.setAttribute('height', '100%')
      bgRect.setAttribute('fill', cssVars['--cream'])
      clonedSvg.insertBefore(bgRect, clonedSvg.firstChild)

      // Serialize SVG to string
      const serializer = new XMLSerializer()
      const svgString = serializer.serializeToString(clonedSvg)

      // Create a blob and image from SVG
      const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
      const svgUrl = URL.createObjectURL(svgBlob)

      // Draw to canvas for PNG export
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          setError('Failed to create canvas context')
          URL.revokeObjectURL(svgUrl)
          setIsValidating(false)
          return
        }

        // Draw the SVG image onto the canvas
        ctx.drawImage(img, 0, 0, width, height)

        // Convert to PNG and download
        const pngUrl = canvas.toDataURL('image/png')
        const a = document.createElement('a')
        a.href = pngUrl
        const workflowName = currentWorkflow?.metadata?.name || 'workflow'
        a.download = `${workflowName}.png`
        a.click()

        URL.revokeObjectURL(svgUrl)
        setIsValidating(false)
      }

      img.onerror = () => {
        setError('Failed to load SVG for PNG export')
        URL.revokeObjectURL(svgUrl)
        setIsValidating(false)
      }

      img.src = svgUrl
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PNG export failed')
      setIsValidating(false)
    }
  }, [currentWorkflow, setError])

  // Handle Python export - generates Python code from workflow
  const handleExportPython = useCallback(async () => {
    setShowExportDropdown(false)
    setIsValidating(true)

    try {
      const result = await compileToPython({
        nodes: flowchart.nodes,
        edges: flowchart.edges,
        variables: currentAnalysis?.variables || [],
        outputs: currentAnalysis?.outputs || [],
        name: currentWorkflow?.metadata?.name || 'workflow',
        include_imports: true,
        include_docstring: true,
        include_main: true,
      })

      if (!result.success || !result.code) {
        throw new Error(result.error || 'Failed to generate Python code')
      }

      // Check for critical warnings that indicate broken code
      const criticalWarnings = (result.warnings || []).filter(w =>
        w.includes('Could not compile condition') ||
        w.includes('Unknown variable') ||
        w.includes('not defined') ||
        w.includes('requires manual implementation')
      )

      if (criticalWarnings.length > 0) {
        const proceed = confirm(
          `⚠️ Python Export Warnings\n\n` +
          `The generated code may not work correctly:\n\n` +
          criticalWarnings.map(w => `• ${w}`).join('\n') +
          `\n\nDo you want to download anyway?`
        )
        if (!proceed) {
          setIsValidating(false)
          return
        }
      }

      // Download as .py file
      const blob = new Blob([result.code], { type: 'text/x-python' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const workflowName = currentWorkflow?.metadata?.name || 'workflow'
      // Convert name to valid filename
      const filename = workflowName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_+$/, '')
      a.download = `${filename || 'workflow'}.py`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Python export failed')
    } finally {
      setIsValidating(false)
    }
  }, [flowchart, currentAnalysis, currentWorkflow, setError])

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
          onClick={() => openModal('miro-import')}
          title="Import flowchart from Miro"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Import Miro
        </button>

        <div className="export-dropdown-container" ref={exportDropdownRef}>
          <button
            className="ghost"
            disabled={!canExport || isValidating}
            onClick={() => setShowExportDropdown(!showExportDropdown)}
            title={canExport ? 'Export workflow' : 'No workflow to export'}
          >
            {isValidating ? 'Exporting...' : 'Export'}
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              style={{ marginLeft: '4px' }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
          {showExportDropdown && (
            <div className="export-dropdown">
              <button onClick={handleExportJSON}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                Export as JSON
              </button>
              <button onClick={handleExportPNG}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
                Export as PNG
              </button>
              <button onClick={handleExportPython}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" />
                  <path d="M8 12l2 2 4-4" />
                </svg>
                Export as Python
              </button>
            </div>
          )}
        </div>

        {/* Dev Mode Toggle */}
        <div className="dev-mode-toggle">
          <label className="toggle-label">
            <span className="toggle-text">DEV</span>
            <input
              type="checkbox"
              checked={devMode}
              onChange={toggleDevMode}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>

        <button className="ghost" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </header>
  )
}
