import { useState, useRef, useEffect, useCallback } from 'react'
import { marked } from 'marked'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { cancelChatTask, sendChatMessage } from '../api/socketActions'
import { useVoiceInput } from '../hooks/useVoiceInput'
import type { Message } from '../types'

export default function Chat({ revealedClass }: { revealedClass?: string }) {
  const [inputValue, setInputValue] = useState('')
  const [showCustomAnswer, setShowCustomAnswer] = useState(false)
  const [customAnswer, setCustomAnswer] = useState('')
  // Collected answers for multi-question batches — only sent after the last answer
  const collectedAnswers = useRef<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isUserScrolledUp = useRef(false)
  const isProgrammaticScroll = useRef(false)

  // Read from the active workflow's conversation — no dual-mode, same path for all workflows
  const activeWorkflowId = useChatStore(s => s.activeWorkflowId)
  const conv = useChatStore(s => activeWorkflowId ? s.conversations[activeWorkflowId] : undefined)
  const messages = conv?.messages ?? []
  const isStreaming = conv?.isStreaming ?? false
  const streamingContent = conv?.streamingContent ?? ''
  const processingStatus = conv?.processingStatus ?? null
  const thinkingContent = conv?.thinkingContent ?? ''
  const currentTaskId = conv?.currentTaskId ?? null
  const contextUsagePct = conv?.contextUsagePct ?? 0

  // Global state (not per-workflow)
  const pendingQuestions = useChatStore(s => s.pendingQuestions)
  const clearPendingQuestion = useChatStore(s => s.clearPendingQuestion)
  const sendUserMessage = useChatStore(s => s.sendUserMessage)
  const markTaskCancelled = useChatStore(s => s.markTaskCancelled)

  const {
    pendingFiles,
    clearPendingFiles,
    addPendingFile,
    filesSent,
    markFilesSent,
    plan,
    setPlan,
  } = useWorkflowStore()

  const conversationId = conv?.conversationId ?? null

  // Current question is the front of the queue (null if empty)
  const pendingQuestion = pendingQuestions[0] ?? null

  const fileInputRef = useRef<HTMLInputElement>(null)

  const { chatHeight, setChatHeight } = useUIStore()

  // Ref for auto-scrolling the thinking stream to the bottom as new chunks arrive.
  const thinkingRef = useRef<HTMLDivElement>(null)
  const isThinkingScrolledUp = useRef(false)

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
      baseTextRef.current = baseTextRef.current ? `${baseTextRef.current} ${text}` : text
      setInputValue(baseTextRef.current)
    },
    onInterimTranscript: (text) => {
      setInputValue(baseTextRef.current ? `${baseTextRef.current} ${text}` : text)
    },
  })

  // Wrap toggle to capture base text when starting
  const toggleListening = useCallback(() => {
    if (!isListening) {
      baseTextRef.current = inputValue
    }
    rawToggleListening()
  }, [isListening, inputValue, rawToggleListening])

  // Handle file upload from chat input area
  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result as string
      const isImage = file.type.startsWith('image/')
      addPendingFile({
        id: crypto.randomUUID(),
        name: file.name,
        dataUrl,
        type: isImage ? 'image' : 'pdf',
        purpose: 'unclassified',
      })
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }, [addPendingFile])

  // Track if user has scrolled up manually (ignore programmatic scrolls)
  const handleScroll = useCallback(() => {
    if (isProgrammaticScroll.current) return
    const container = messagesContainerRef.current
    if (!container) return
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100
    isUserScrolledUp.current = !atBottom
  }, [])

  // Helper to scroll without triggering the "user scrolled" detection
  const scrollToBottom = useCallback(() => {
    isProgrammaticScroll.current = true
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    setTimeout(() => {
      isProgrammaticScroll.current = false
    }, 100)
  }, [])

  // Auto-scroll to bottom when new messages are added
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

  // Heartbeat watchdog — detect stale tasks when no backend events arrive.
  // Timeout is 60s to survive API rate-limit retries (429 retry-after can be ~50s).
  // Clears streaming state so the user isn't stuck on "Thinking..." forever.
  useEffect(() => {
    if (!isStreaming || !activeWorkflowId) return
    const HEARTBEAT_TIMEOUT_MS = 60_000
    const interval = setInterval(() => {
      const c = useChatStore.getState().conversations[activeWorkflowId]
      if (!c?.isStreaming) return  // streaming ended naturally
      const lastBeat = c.lastHeartbeatAt
      if (lastBeat > 0 && Date.now() - lastBeat > HEARTBEAT_TIMEOUT_MS) {
        console.warn('[Chat] Heartbeat timeout — clearing stale streaming state')
        const cs = useChatStore.getState()
        cs.finalizeStream(activeWorkflowId)
        cs.setCurrentTaskId(activeWorkflowId, null)
        useUIStore.getState().setError('Connection to backend lost — please try again')
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [isStreaming, activeWorkflowId])

  // Auto-scroll the thinking stream container
  useEffect(() => {
    if (thinkingRef.current && !isThinkingScrolledUp.current) {
      thinkingRef.current.scrollTop = thinkingRef.current.scrollHeight
    }
  }, [thinkingContent])

  // Reset the scroll-up flag when thinking content is cleared
  useEffect(() => {
    if (!thinkingContent) {
      isThinkingScrolledUp.current = false
    }
  }, [thinkingContent])

  // Detect manual scroll inside the thinking stream container
  const handleThinkingScroll = useCallback(() => {
    const el = thinkingRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20
    isThinkingScrolledUp.current = !atBottom
  }, [])

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

    sendUserMessage(trimmed)

    // Send via socket — only include files on first send
    const filesToSend = pendingFiles.length > 0 && !filesSent ? pendingFiles : undefined
    sendChatMessage(
      trimmed,
      conversationId,
      filesToSend,
    )

    if (filesToSend) {
      markFilesSent()
    }

    clearPendingQuestion()
    setInputValue('')
    baseTextRef.current = ''
  }

  // Handle clicking an option chip on a question card
  const handleAnswerQuestion = (optionLabel: string) => {
    const questionText = pendingQuestion?.question || ''
    const answer = questionText
      ? `${questionText}: ${optionLabel}`
      : optionLabel

    sendUserMessage(optionLabel)
    collectedAnswers.current.push(answer)
    clearPendingQuestion()
    setShowCustomAnswer(false)
    setCustomAnswer('')
    setInputValue('')
    baseTextRef.current = ''

    // If no more questions remain, send all collected answers to the backend
    const remaining = pendingQuestions.length - 1
    if (remaining <= 0) {
      const fullMessage = collectedAnswers.current.join('\n')
      sendChatMessage(fullMessage, conversationId)
      collectedAnswers.current = []
    }
  }

  const handleStop = () => {
    if (currentTaskId) {
      cancelChatTask(currentTaskId)
      markTaskCancelled(currentTaskId)
    }
    if (activeWorkflowId) {
      const cs = useChatStore.getState()
      cs.finalizeStream(activeWorkflowId)
      // Clear currentTaskId immediately so the UI isn't stuck waiting
      // for the backend's chat_cancelled ack to clear it.
      cs.setCurrentTaskId(activeWorkflowId, null)
    }
    setPlan([])
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

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    startY.current = e.clientY
    startHeight.current = chatHeight
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'ns-resize'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging.current) return
    const delta = startY.current - e.clientY
    const newHeight = Math.min(Math.max(startHeight.current + delta, 0), window.innerHeight * 0.6)
    setChatHeight(newHeight)
  }

  const handleMouseUp = () => {
    isDragging.current = false
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
  }

  const isCollapsed = chatHeight === 0
  return (
    <div className={`chat-dock ${revealedClass || ''} ${isCollapsed ? 'chat-dock-collapsed' : ''}`} style={{ height: isCollapsed ? undefined : chatHeight }}>
      <div className="chat-resize-handle" onMouseDown={handleMouseDown}>
        <div className="resize-grip"></div>
      </div>

      <div className="chat-messages" id="chatThread" ref={messagesContainerRef} onScroll={handleScroll}>
        {messages.length === 0 && !isStreaming ? (
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


        {isStreaming && (() => {
          // Rolling plan window: show ~8 items centered around current progress
          const maxVisible = 8
          const firstPending = plan.findIndex(item => !item.done)
          const anchor = firstPending === -1 ? plan.length : firstPending
          const windowStart = Math.max(0, anchor - 3)
          const visiblePlan = plan.slice(windowStart, windowStart + maxVisible)

          const planChecklist = visiblePlan.length > 0 && (
            <div className="plan-checklist">
              {visiblePlan.map((item, i) => {
                const isActive = !item.done && (i === 0 || visiblePlan[i - 1]?.done)
                return (
                  <div key={windowStart + i} className={`plan-item ${item.done ? 'done' : ''} ${isActive ? 'active' : ''}`}>
                    <span className="plan-icon">{item.done ? '\u2713' : '\u25CB'}</span>
                    <span className="plan-text">{item.text}</span>
                  </div>
                )
              })}
            </div>
          )

          return (
            <div className="message assistant streaming">
              <div className="message-content">
                {streamingContent ? (
                  <>
                    {thinkingContent && (
                      <div className="thinking-stream" ref={thinkingRef} onScroll={handleThinkingScroll}>
                        <span className="thinking-label">Reasoning</span>
                        <div className="thinking-text">{thinkingContent}</div>
                      </div>
                    )}
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
                    {planChecklist}
                  </>
                ) : processingStatus ? (
                  <>
                    {thinkingContent && (
                      <div className="thinking-stream" ref={thinkingRef} onScroll={handleThinkingScroll}>
                        <span className="thinking-label">Reasoning</span>
                        <div className="thinking-text">{thinkingContent}</div>
                      </div>
                    )}
                    <span className="processing-status">
                      <span className="status-dot"></span>
                      {processingStatus}
                    </span>
                    {planChecklist}
                  </>
                ) : (
                  <span className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                )}
              </div>
            </div>
          )
        })()}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-container">
        {pendingFiles.length > 0 && (
          <div className="pending-image-indicator">
            <span>
              {pendingFiles.length === 1
                ? `File ready: ${pendingFiles[0].name}`
                : `${pendingFiles.length} files ready`}
            </span>
            <button
              className="clear-image-btn"
              onClick={clearPendingFiles}
              title="Remove all files"
            >
              x
            </button>
          </div>
        )}
        {pendingQuestion && (
          <div className="question-card">
            <p className="question-text">{pendingQuestion.question}</p>
            {pendingQuestion.options.length > 0 && (
              <div className="question-options">
                {pendingQuestion.options.map((opt, i) => (
                  <button
                    key={i}
                    className="option-chip"
                    onClick={() => { setShowCustomAnswer(false); handleAnswerQuestion(opt.label) }}
                  >
                    {opt.label}
                  </button>
                ))}
                <button
                  className={`option-chip option-chip-other ${showCustomAnswer ? 'active' : ''}`}
                  onClick={() => setShowCustomAnswer(!showCustomAnswer)}
                >
                  Other
                </button>
              </div>
            )}
            {showCustomAnswer && (
              <div className="custom-answer-row">
                <input
                  type="text"
                  className="custom-answer-input"
                  placeholder="Type your answer..."
                  value={customAnswer}
                  onChange={(e) => setCustomAnswer(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && customAnswer.trim()) {
                      handleAnswerQuestion(customAnswer.trim())
                      setCustomAnswer('')
                      setShowCustomAnswer(false)
                    }
                  }}
                  autoFocus
                />
                <button
                  className="primary custom-answer-send"
                  disabled={!customAnswer.trim()}
                  onClick={() => {
                    if (customAnswer.trim()) {
                      handleAnswerQuestion(customAnswer.trim())
                      setCustomAnswer('')
                      setShowCustomAnswer(false)
                    }
                  }}
                >
                  Send
                </button>
              </div>
            )}
          </div>
        )}
        {contextUsagePct > 50 && (
          <div className="context-meter">
            <div className="context-track">
              <div
                className={`context-fill${contextUsagePct > 80 ? ' warn' : ''}${contextUsagePct > 95 ? ' critical' : ''}`}
                style={{ width: `${contextUsagePct}%` }}
              />
            </div>
            <span className={`context-label${contextUsagePct > 80 ? ' warn' : ''}${contextUsagePct > 95 ? ' critical' : ''}`}>
              {contextUsagePct}%
            </span>
          </div>
        )}
        <div className="chat-input-wrapper">
          <textarea
            ref={textareaRef}
            id="chatInput"
            placeholder={isStreaming ? 'Agent is working...' : 'Describe your workflow...'}
            rows={1}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
          />
          {/* Hidden file input for image/PDF upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf"
            style={{ display: 'none' }}
            onChange={handleFileUpload}
          />
          <button
            className="voice-btn"
            title="Upload image or PDF"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </button>
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
      {message.tool_calls.length > 0 && (
        <details className="tool-call-disclosure" open>
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
      )}
    </div>
  )
}
