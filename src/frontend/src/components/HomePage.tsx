import { useState, useRef, useCallback } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { sendChatMessage } from '../api/socket'
import { addAssistantMessage } from '../stores/chatStore'
import { compressDataUrl, MAX_IMAGE_BYTES, MAX_IMAGE_DIMENSION } from '../utils/imageUtils'
import '../styles/HomePage.css'

export default function HomePage() {
    const [chatInput, setChatInput] = useState('')
    const [isSending, setIsSending] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const { addPendingFile } = useWorkflowStore()
    const { setError } = useUIStore()

    // Handle sending a message to AI
    const handleSend = useCallback(async () => {
        const text = chatInput.trim()
        if (!text || isSending) return

        setIsSending(true)
        try {
            // Navigate to workflow page and send the message
            window.location.hash = '#/workflow'
            // Small delay to let the workflow page mount and initialize socket
            setTimeout(() => {
                sendChatMessage(text)
                setIsSending(false)
            }, 300)
        } catch {
            setIsSending(false)
        }
    }, [chatInput, isSending])

    // Handle key press in chat input
    const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSend()
        }
    }, [handleSend])

    // Handle file upload (images and PDFs, supports multiple)
    const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const fileList = e.target.files
        if (!fileList || fileList.length === 0) return

        const names: string[] = []
        for (const file of Array.from(fileList)) {
            try {
                const isPdf = file.type === 'application/pdf'
                const reader = new FileReader()
                const dataUrl = await new Promise<string>((resolve, reject) => {
                    reader.onload = () => resolve(reader.result as string)
                    reader.onerror = () => reject(new Error('Failed to read file'))
                    reader.readAsDataURL(file)
                })

                let finalDataUrl = dataUrl
                if (!isPdf) {
                    const { dataUrl: compressed, didChange, bytes } = await compressDataUrl(dataUrl, {
                        maxBytes: MAX_IMAGE_BYTES,
                        maxDimension: MAX_IMAGE_DIMENSION,
                    })
                    if (bytes > MAX_IMAGE_BYTES) {
                        setError(`"${file.name}" is too large (${(bytes / (1024 * 1024)).toFixed(1)}MB). Skipped.`)
                        continue
                    }
                    finalDataUrl = compressed
                    if (didChange) {
                        names.push(`${file.name} (resized)`)
                    } else {
                        names.push(file.name)
                    }
                } else {
                    names.push(file.name)
                }

                addPendingFile({
                    id: `${Date.now()}_${file.name}`,
                    name: file.name,
                    dataUrl: finalDataUrl,
                    type: isPdf ? 'pdf' : 'image',
                    purpose: 'unclassified',
                })
            } catch (err) {
                setError(err instanceof Error ? err.message : `Failed to process ${file.name}`)
            }
        }

        if (names.length > 0) {
            const msg = names.length === 1
                ? `File "${names[0]}" uploaded. You can now ask me to analyse it.`
                : `Uploaded ${names.length} files: ${names.join(', ')}.`
            addAssistantMessage(msg)
            window.location.hash = '#/workflow'
        }

        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }, [addPendingFile, setError])

    return (
        <div className="home-page">
            <header className="home-header animate-slide-down-1">
                <div className="logo">
                    <span className="logo-mark">L</span>
                    <span className="logo-text">LEMON</span>
                </div>
                <button className="ghost home-signout" onClick={() => {
                    window.location.hash = '#/auth'
                }}>
                    Sign out
                </button>
            </header>

            <main className="home-content">
                <div className="home-greeting animate-slide-down-2">
                    <span className="greeting-sparkle">✦</span>
                    <h2 className="greeting-subtitle">Hi there</h2>
                    <h1 className="greeting-title">Where should we start?</h1>
                </div>

                <div className="home-chat-bar animate-slide-down-3">
                    <textarea
                        className="home-chat-input"
                        placeholder="Describe a workflow to build..."
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        rows={1}
                        disabled={isSending}
                    />
                    <div className="home-chat-actions">
                        <button
                            className="home-send-btn"
                            onClick={handleSend}
                            disabled={!chatInput.trim() || isSending}
                            title="Send message"
                        >
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M22 2L11 13" />
                                <path d="M22 2l-7 20-4-9-9-4 20-7z" />
                            </svg>
                        </button>
                    </div>
                </div>

                <div className="home-chips animate-slide-down-4">
                    <button className="home-chip" onClick={() => { window.location.hash = '#/library' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
                            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
                        </svg>
                        Browse Library
                    </button>

                    <label className="home-chip" htmlFor="homeFileUpload">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                            <polyline points="17 8 12 3 7 8" />
                            <line x1="12" y1="3" x2="12" y2="15" />
                        </svg>
                        Upload Files
                    </label>
                    <input
                        ref={fileInputRef}
                        type="file"
                        id="homeFileUpload"
                        accept="image/*,application/pdf"
                        multiple
                        style={{ display: 'none' }}
                        onChange={handleFileUpload}
                    />

                    <button className="home-chip" onClick={() => { window.location.hash = '#/workflow' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M12 5v14M5 12h14" />
                        </svg>
                        New Workflow
                    </button>
                </div>
            </main>
        </div>
    )
}
