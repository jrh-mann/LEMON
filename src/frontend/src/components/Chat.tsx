import { useState, useRef, useEffect, useCallback } from 'react'
import { marked } from 'marked'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { cancelChatTask, sendChatMessage } from '../api/socket'
import { useVoiceInput } from '../hooks/useVoiceInput'
import type { Message } from '../types'

export default function Chat() {
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isUserScrolledUp = useRef(false)
  const isProgrammaticScroll = useRef(false)

  const {
    messages,
    conversationId,
    isStreaming,
    streamingContent,
    processingStatus,
    currentTaskId,
    pendingQuestion,
    sendUserMessage,
    finalizeStreamingMessage,
    markTaskCancelled,
    clearCurrentTaskId,
  } = useChatStore()

  const {
    pendingImage,
    pendingImageName,
    pendingAnnotations,
    clearPendingImage,
  } = useWorkflowStore()

  const { chatHeight, setChatHeight } = useUIStore()

  // Track the base text (before current speech session)
  const baseTextRef = useRef('')

  // Voice input hook
  const {
    isListening,
    isSupported: isVoiceSupported,
    volume,
    toggleListening: rawToggleListening,
  } = useVoiceInput({
    onTranscript: (text) => {
      // Final transcript - commit to base text
      baseTextRef.current = baseTextRef.current ? `${baseTextRef.current} ${text}` : text
      setInputValue(baseTextRef.current)
    },
    onInterimTranscript: (text) => {
      // Show interim results in real-time
      setInputValue(baseTextRef.current ? `${baseTextRef.current} ${text}` : text)
    },
  })

  // Wrap toggle to capture base text when starting
  const toggleListening = useCallback(() => {
    if (!isListening) {
      // Starting - capture current input as base
      baseTextRef.current = inputValue
    }
    rawToggleListening()
  }, [isListening, inputValue, rawToggleListening])

  // Track if user has scrolled up manually (ignore programmatic scrolls)
  const handleScroll = useCallback(() => {
    // Ignore scroll events caused by our own scrollIntoView calls
    if (isProgrammaticScroll.current) return

    const container = messagesContainerRef.current
    if (!container) return
    // Consider "at bottom" if within 100px of the bottom
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100
    isUserScrolledUp.current = !atBottom
  }, [])

  // Helper to scroll without triggering the "user scrolled" detection
  const scrollToBottom = useCallback(() => {
    isProgrammaticScroll.current = true
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    // Reset flag after scroll animation completes
    setTimeout(() => {
      isProgrammaticScroll.current = false
    }, 100)
  }, [])

  // Auto-scroll to bottom when new messages are added
  // But only if user hasn't scrolled up manually
  useEffect(() => {
    if (!isUserScrolledUp.current) {
      scrollToBottom()
    }
  }, [messages, scrollToBottom])

  // Reset scroll tracking and scroll to bottom when streaming starts
  useEffect(() => {
    if (isStreaming) {
      isUserScrolledUp.current = false
      scrollToBottom()
    }
  }, [isStreaming, scrollToBottom])

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`
    }
  }, [inputValue])

  // Handle send
  const handleSend = () => {
    const trimmed = inputValue.trim()
    if (!trimmed || isStreaming) return

    // Add user message to store
    sendUserMessage(trimmed)

    // Send via socket - include pending image and annotations if available
    sendChatMessage(
      trimmed,
      conversationId,
      pendingImage || undefined,
      pendingAnnotations.length > 0 ? pendingAnnotations : undefined
    )

    // Keep pending image around so user can reference it in Source Image tab
    // Image is only cleared when user explicitly clicks x or uploads a new one

    // Clear input and reset voice base text
    setInputValue('')
    baseTextRef.current = ''
  }

  const handleStop = () => {
    if (currentTaskId) {
      cancelChatTask(currentTaskId)
      markTaskCancelled(currentTaskId)
    }
    finalizeStreamingMessage()
    clearCurrentTaskId()
    textareaRef.current?.focus()
  }

  // Handle key press
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Render markdown safely
  const renderMarkdown = (content: string): string => {
    try {
      return marked.parse(content, { async: false }) as string
    } catch {
      return content
    }
  }

  const isDragging = useRef(false)
  const startY = useRef(0)
  const startHeight = useRef(0)

  // Handle resize drag
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()  // Prevent text selection
    isDragging.current = true
    startY.current = e.clientY
    startHeight.current = chatHeight
    // Disable text selection and set cursor during drag
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ns-resize'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging.current) return
    const delta = startY.current - e.clientY
    // Min 200px, max 60% of viewport to leave room for workspace
    const newHeight = Math.min(Math.max(startHeight.current + delta, 200), window.innerHeight * 0.6)
    setChatHeight(newHeight)
  }

  const handleMouseUp = () => {
    isDragging.current = false
    // Restore text selection and cursor
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }

  return (
    <div className="chat-dock" style={{ height: chatHeight }}>
      <div className="chat-resize-handle" onMouseDown={handleMouseDown}>
        <div className="resize-grip"></div>
      </div>

      <div className="chat-header">
        <h3>Orchestrator</h3>
        <p className="muted">Describe your workflow or ask questions</p>
      </div>

      <div className="chat-messages" id="chatThread" ref={messagesContainerRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p className="muted">
              Start by describing your workflow or uploading a flowchart image.
            </p>
            <div className="chat-suggestions">
              <button
                className="suggestion-chip"
                onClick={() => setInputValue('Show me nephrology workflows')}
              >
                Browse nephrology workflows
              </button>
              <button
                className="suggestion-chip"
                onClick={() => setInputValue('Create a workflow for blood pressure classification')}
              >
                Create BP classification
              </button>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble key={message.id} message={message} renderMarkdown={renderMarkdown} />
          ))
        )}

        {isStreaming && (
          <div className="message assistant streaming">
            <div className="message-content">
              {streamingContent ? (
                <>
                  <div
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(streamingContent),
                    }}
                  />
                  {processingStatus && (
                    <span className="processing-status">
                      <span className="status-dot"></span>
                      {processingStatus}
                    </span>
                  )}
                </>
              ) : processingStatus ? (
                <span className="processing-status">
                  <span className="status-dot"></span>
                  {processingStatus}
                </span>
              ) : (
                <span className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-container">
        {pendingImage && (
          <div className="pending-image-indicator">
            <span>Image ready: {pendingImageName || 'uploaded image'}</span>
            <button
              className="clear-image-btn"
              onClick={clearPendingImage}
              title="Remove image"
            >
              x
            </button>
          </div>
        )}
        {pendingQuestion && (
          <div className="pending-question-hint">
            <span>Awaiting your response...</span>
          </div>
        )}
        <div className="chat-input-wrapper">
          <textarea
            ref={textareaRef}
            id="chatInput"
            placeholder="Describe your workflow..."
            rows={1}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
          />
          <button
            className={`voice-btn ${isListening ? 'listening' : ''}`}
            id="voiceBtn"
            title={isVoiceSupported ? (isListening ? 'Stop recording' : 'Voice input') : 'Voice not supported'}
            onClick={toggleListening}
            disabled={!isVoiceSupported || isStreaming}
            style={isListening ? {
              '--volume': volume,
              transform: `scale(${1 + volume * 0.3})`,
            } as React.CSSProperties : undefined}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>
          {isStreaming ? (
            <button
              className="ghost"
              id="stopBtn"
              onClick={handleStop}
            >
              Stop
            </button>
          ) : (
            <button
              className="primary"
              id="sendBtn"
              onClick={handleSend}
              disabled={!inputValue.trim()}
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// Message bubble component
function MessageBubble({
  message,
  renderMarkdown,
}: {
  message: Message
  renderMarkdown: (content: string) => string
}) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const { devMode, setSelectedToolCall } = useUIStore()

  const handleToolClick = (tc: import('../types').ToolCall) => {
    if (devMode) {
      setSelectedToolCall(tc)
    }
  }

  return (
    <div className={`message ${message.role}`}>
      <div
        className="message-content"
        dangerouslySetInnerHTML={{
          __html: isUser || isSystem ? message.content : renderMarkdown(message.content),
        }}
      />
      {message.tool_calls.length > 0 &&
        (message.tool_calls.length > 3 ? (
          <details className="tool-call-disclosure">
            <summary className="tool-call-summary">
              Tools ({message.tool_calls.length})
            </summary>
            <div className="tool-calls">
              {message.tool_calls.map((tc, idx) => (
                <div
                  key={idx}
                  className={`tool-call ${devMode ? 'clickable' : ''} ${tc.success === false ? 'failed' : ''}`}
                  onClick={() => handleToolClick(tc)}
                  title={devMode ? 'Click to inspect tool call' : undefined}
                >
                  <span className="tool-name">{tc.tool}</span>
                  {tc.success === false && <span className="tool-failed-badge">✗</span>}
                </div>
              ))}
            </div>
          </details>
        ) : (
          <div className="tool-calls">
            {message.tool_calls.map((tc, idx) => (
              <div
                key={idx}
                className={`tool-call ${devMode ? 'clickable' : ''} ${tc.success === false ? 'failed' : ''}`}
                onClick={() => handleToolClick(tc)}
                title={devMode ? 'Click to inspect tool call' : undefined}
              >
                <span className="tool-name">{tc.tool}</span>
                {tc.success === false && <span className="tool-failed-badge">✗</span>}
              </div>
            ))}
          </div>
        ))}
    </div>
  )
}
