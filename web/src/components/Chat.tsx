export default function Chat() {
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
        {/* Messages will be populated here */}
      </div>
      <div className="chat-input-container">
        <div className="chat-input-wrapper">
          <textarea 
            id="chatInput" 
            placeholder="Describe your workflow..." 
            rows={1}
          ></textarea>
          <button className="voice-btn" id="voiceBtn" title="Voice input">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/>
              <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
          </button>
          <button className="primary" id="sendBtn">Send</button>
        </div>
      </div>
    </div>
  )
}
