import { useState, useEffect, useRef } from 'react';
import SciMarkdown from './SciMarkdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import TokenBurndown from './TokenBurndown';
import LearnUnlearn from './LearnUnlearn';
import EnhancePrompt from './EnhancePrompt';
import { api } from '../api';
import './ChatInterface.css';

// Allowed file types and their MIME types
const ALLOWED_FILE_TYPES = {
  'application/pdf': { ext: '.pdf', name: 'PDF' },
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': { ext: '.pptx', name: 'PowerPoint' },
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': { ext: '.xlsx', name: 'Excel' },
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': { ext: '.docx', name: 'Word' },
};

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB max file size

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [attachmentError, setAttachmentError] = useState(null);
  const [enhanceState, setEnhanceState] = useState(null); // null | 'loading' | 'ready'
  const [enhancedData, setEnhancedData] = useState(null); // { original, enhanced }
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const userScrolledAwayRef = useRef(false);

  const scrollToBottom = (force = false) => {
    if (!messagesContainerRef.current) return;
    // Only auto-scroll if user is near the bottom (within 200px) or forced
    const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    if (force || distanceFromBottom < 200) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  };

  // Track whether user manually scrolled up
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      userScrolledAwayRef.current = (scrollHeight - scrollTop - clientHeight) > 200;
    };
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const validateFile = (file) => {
    // Check file type
    if (!ALLOWED_FILE_TYPES[file.type]) {
      const allowedExts = Object.values(ALLOWED_FILE_TYPES).map(t => t.ext).join(', ');
      return `Invalid file type. Allowed: ${allowedExts}`;
    }
    
    // Check file size
    if (file.size > MAX_FILE_SIZE) {
      return `File too large. Maximum size: ${MAX_FILE_SIZE / (1024 * 1024)}MB`;
    }
    
    // Check if file already attached
    if (attachments.some(a => a.name === file.name && a.size === file.size)) {
      return 'File already attached';
    }
    
    return null;
  };

  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files);
    setAttachmentError(null);
    
    for (const file of files) {
      const error = validateFile(file);
      if (error) {
        setAttachmentError(error);
        continue;
      }
      
      // Read file as base64
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = reader.result.split(',')[1]; // Remove data:...;base64, prefix
        setAttachments(prev => [...prev, {
          name: file.name,
          type: file.type,
          size: file.size,
          base64: base64,
        }]);
      };
      reader.onerror = () => {
        setAttachmentError(`Failed to read file: ${file.name}`);
      };
      reader.readAsDataURL(file);
    }
    
    // Reset file input
    e.target.value = '';
  };

  const removeAttachment = (index) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
    setAttachmentError(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if ((input.trim() || attachments.length > 0) && !isLoading && !enhanceState) {
      const promptText = input.trim();
      const currentAttachments = [...attachments];

      // Only enhance if there's actual text (not just attachments)
      if (promptText) {
        setEnhanceState('loading');
        setPendingAttachments(currentAttachments);
        setInput('');
        setAttachments([]);
        setAttachmentError(null);

        try {
          const result = await api.enhancePrompt(promptText);
          setEnhancedData(result);
          setEnhanceState('ready');
        } catch (error) {
          console.error('Failed to enhance prompt, sending original:', error);
          // If enhance fails, just send the original
          setEnhanceState(null);
          setEnhancedData(null);
          setPendingAttachments([]);
          onSendMessage(promptText, currentAttachments);
        }
      } else {
        // No text, just attachments — send directly
        onSendMessage('', currentAttachments);
        setInput('');
        setAttachments([]);
        setAttachmentError(null);
      }
    }
  };

  const handleKeepOriginal = () => {
    const original = enhancedData?.original || '';
    const atts = pendingAttachments;
    setEnhanceState(null);
    setEnhancedData(null);
    setPendingAttachments([]);
    onSendMessage(original, atts);
  };

  const handleUseEnhanced = (editedPrompt) => {
    const atts = pendingAttachments;
    setEnhanceState(null);
    setEnhancedData(null);
    setPendingAttachments([]);
    onSendMessage(editedPrompt, atts);
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const getFileIcon = (type) => {
    const typeInfo = ALLOWED_FILE_TYPES[type];
    if (!typeInfo) return '📄';
    switch (typeInfo.ext) {
      case '.pdf': return '📕';
      case '.pptx': return '📊';
      case '.xlsx': return '📗';
      case '.docx': return '📘';
      default: return '📄';
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface" id="main-content" role="main">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface" id="main-content" role="main">
      <div className="messages-container" ref={messagesContainerRef}>
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <SciMarkdown>{msg.content}</SciMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                      groundingScores={msg.metadata?.grounding_scores}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} evidence={msg.evidence} />}

                  {/* Cost / Token Burndown */}
                  {msg.costSummary && <TokenBurndown costSummary={msg.costSummary} />}

                  {/* Memory Learn/Unlearn Controls */}
                  {msg.memoryLearning && (
                    <LearnUnlearn
                      learningData={msg.memoryLearning}
                      memoryRecall={msg.memoryRecall}
                      memoryGate={msg.memoryGate}
                    />
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && !conversation.messages.some(m => m.loading) && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        {/* Enhance Prompt Flow */}
        {enhanceState === 'loading' && (
          <div className="enhance-loading-indicator">
            <div className="spinner"></div>
            <span>Enhancing your prompt...</span>
          </div>
        )}
        {enhanceState === 'ready' && enhancedData && (
          <EnhancePrompt
            originalPrompt={enhancedData.original}
            enhancedPrompt={enhancedData.enhanced}
            onKeepOriginal={handleKeepOriginal}
            onUseEnhanced={handleUseEnhanced}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Always show input form - for both new conversations and follow-ups */}
      <form className="input-form" onSubmit={handleSubmit}>
        {/* Attachments Preview */}
        {attachments.length > 0 && (
          <div className="attachments-preview">
            {attachments.map((file, index) => (
              <div key={index} className="attachment-chip">
                <span className="attachment-icon">{getFileIcon(file.type)}</span>
                <span className="attachment-name">{file.name}</span>
                <span className="attachment-size">({formatFileSize(file.size)})</span>
                <button
                  type="button"
                  className="attachment-remove"
                  onClick={() => removeAttachment(index)}
                  disabled={isLoading}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        
        {/* Attachment Error */}
        {attachmentError && (
          <div className="attachment-error">
            ⚠️ {attachmentError}
          </div>
        )}

        <div className="input-row">
          {/* File Input (hidden) */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.pptx,.xlsx,.docx,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            multiple
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />
          
          {/* Attachment Button */}
          <button
            type="button"
            className="attachment-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            title="Attach files (PDF, PPTX, XLSX, DOCX)"
          >
            📎
          </button>

          <textarea
            className="message-input"
            placeholder={conversation.messages.length > 0 
              ? "Ask a follow-up question... (Shift+Enter for new line, Enter to send)" 
              : "Ask your question... (Shift+Enter for new line, Enter to send)"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading || !!enhanceState}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={(!input.trim() && attachments.length === 0) || isLoading || !!enhanceState}
          >
            {conversation.messages.length > 0 ? 'Follow Up' : 'Send'}
          </button>
        </div>
        
        <div className="input-hint">
          {conversation.messages.length > 0 
            ? "Continue the conversation with follow-up questions" 
            : "Supported attachments: PDF, PPTX, XLSX, DOCX (max 10MB each)"}
        </div>
      </form>
    </div>
  );
}
