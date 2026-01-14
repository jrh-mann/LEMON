import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import { useChatStore } from '../stores/chatStore'
import { sendChatMessage } from '../api/socket'
import type { Message } from '../types'

export default function Chat() {
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const {
    messages,
    conversationId,
    isStreaming,
    pendingQuestion,
    sendUserMessage,
  } = useChatStore()

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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

    // Send via socket
    sendChatMessage(trimmed, conversationId)

    // Clear input
    setInputValue('')
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

  return (
    <div className="chat-dock">
      <div className="chat-resize-handle">
        <div className="resize-grip"></div>
      </div>

      <div className="chat-header">
        <h3>Orchestrator</h3>
        <p className="muted">Describe your workflow or ask questions</p>
      </div>

      <div className="chat-messages" id="chatThread">
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
              <span className="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-container">
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
          <button className="voice-btn" id="voiceBtn" title="Voice input" disabled>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>
          <button
            className="primary"
            id="sendBtn"
            onClick={handleSend}
            disabled={!inputValue.trim() || isStreaming}
          >
            {isStreaming ? 'Sending...' : 'Send'}
          </button>
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

  return (
    <div className={`message ${message.role}`}>
      <div
        className="message-content"
        dangerouslySetInnerHTML={{
          __html: isUser || isSystem ? message.content : renderMarkdown(message.content),
        }}
      />
      {message.tool_calls.length > 0 && (
        <div className="tool-calls">
          {message.tool_calls.map((tc, idx) => (
            <div key={idx} className="tool-call">
              <span className="tool-name">{tc.tool}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
