import { useState, useEffect, useRef } from 'react';
import SciMarkdown from './SciMarkdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import InfographicPanel from './InfographicPanel';
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
  'text/markdown': { ext: '.md', name: 'Markdown' },
  'text/plain': { ext: '.txt', name: 'Text' },  // .md files sometimes report as text/plain
  'image/png': { ext: '.png', name: 'Image' },
  'image/jpeg': { ext: '.jpg', name: 'Image' },
  'image/gif': { ext: '.gif', name: 'Image' },
  'image/webp': { ext: '.webp', name: 'Image' },
  'image/svg+xml': { ext: '.svg', name: 'SVG' },
};

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB max file size

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
  preferences,
  onUpdatePreferences,
}) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [attachmentError, setAttachmentError] = useState(null);
  const [enhanceState, setEnhanceState] = useState(null); // null | 'loading' | 'ready'
  const [enhancedData, setEnhancedData] = useState(null); // { original, enhanced }

  // Conversation blocked by prompt guard — disable all input
  const isBlocked = !!(conversation?.blocked);
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
    // Check file type — also allow by extension for .md files (browsers may report text/plain)
    const isAllowedType = ALLOWED_FILE_TYPES[file.type];
    const isMarkdownByExt = file.name.endsWith('.md') || file.name.endsWith('.markdown');
    if (!isAllowedType && !isMarkdownByExt) {
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
    if ((input.trim() || attachments.length > 0) && !isLoading && !enhanceState && !isBlocked) {
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
          // If the enhanced prompt is essentially the same as the original, skip the card
          const normalise = (s) => s.trim().toLowerCase().replace(/[?.!,;:]+$/g, '');
          if (normalise(result.enhanced) === normalise(promptText)) {
            // No meaningful change — send original directly
            setEnhanceState(null);
            setEnhancedData(null);
            setPendingAttachments([]);
            onSendMessage(promptText, currentAttachments);
          } else {
            setEnhancedData(result);
            setEnhanceState('ready');
          }
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
      case '.md': return '📝';
      case '.txt': return '📝';
      case '.png': case '.jpg': case '.gif': case '.webp': return '🖼️';
      case '.svg': return '🎨';
      default: return '📄';
    }
  };

  // Handle paste events — support pasting images from clipboard
  const handlePaste = (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (const item of items) {
      // Handle pasted images
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;

        // Generate a name for clipboard images
        const ext = file.type.split('/')[1] || 'png';
        const name = `pasted-image-${Date.now()}.${ext}`;

        const reader = new FileReader();
        reader.onload = () => {
          const base64 = reader.result.split(',')[1];
          setAttachments(prev => [...prev, {
            name,
            type: file.type,
            size: file.size,
            base64,
          }]);
        };
        reader.readAsDataURL(file);
      }
      // Handle pasted files (e.g. .md from file managers)
      else if (item.kind === 'file') {
        const file = item.getAsFile();
        if (!file) continue;
        // Check if it's an allowed file type or a markdown/text file
        const isAllowed = ALLOWED_FILE_TYPES[file.type] ||
          file.name.endsWith('.md') || file.name.endsWith('.txt');
        if (!isAllowed) continue;

        e.preventDefault();
        const reader = new FileReader();
        reader.onload = () => {
          const base64 = reader.result.split(',')[1];
          setAttachments(prev => [...prev, {
            name: file.name,
            type: file.type || 'text/markdown',
            size: file.size,
            base64,
          }]);
        };
        reader.readAsDataURL(file);
      }
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
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} evidence={msg.evidence || msg.metadata?.evidence} />}

                  {/* Infographic Panel */}
                  {(msg.infographic || msg.metadata?.infographic) && <InfographicPanel data={msg.infographic || msg.metadata?.infographic} />}

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
        {/* Follow-up quick-select chips (only show after first exchange) */}
        {conversation.messages.length > 0 && (
          <div className="followup-options">
            <span className="followup-label">Focus on:</span>
            {['Stage 1', 'Stage 2', 'Stage 3'].map((stage) => (
              <button
                key={stage}
                type="button"
                className={`followup-chip followup-stage`}
                onClick={() => {
                  const prefix = `Regarding ${stage}: `;
                  setInput(prev => prev.startsWith(prefix) ? prev : prefix + prev);
                }}
                disabled={isLoading || isBlocked}
              >
                {stage}
              </button>
            ))}
            {/* Show council member chips from the last assistant message */}
            {(() => {
              const lastAssistant = [...conversation.messages].reverse().find(m => m.role === 'assistant');
              const models = lastAssistant?.stage1?.map(r => r.model) || [];
              const uniqueModels = [...new Set(models)];
              return uniqueModels.slice(0, 5).map((model) => {
                const shortName = model.split('/').pop() || model;
                return (
                  <button
                    key={model}
                    type="button"
                    className="followup-chip followup-member"
                    onClick={() => {
                      const prefix = `Regarding ${shortName}'s response: `;
                      setInput(prev => prev.startsWith(prefix) ? prev : prefix + prev);
                    }}
                    disabled={isLoading || isBlocked}
                    title={model}
                  >
                    {shortName}
                  </button>
                );
              });
            })()}
          </div>
        )}

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
            accept=".pdf,.pptx,.xlsx,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.gif,.webp,.svg,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/plain,image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
            multiple
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />
          
          {/* Attachment Button */}
          <button
            type="button"
            className="attachment-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || isBlocked}
            title="Attach files (PDF, PPTX, XLSX, DOCX, MD, images)"
          >
            📎
          </button>

          {/* Web Search Toggle — right next to input */}
          <button
            type="button"
            className={`web-search-btn ${preferences?.web_search_enabled ? 'active' : ''}`}
            onClick={() => {
              if (onUpdatePreferences && preferences) {
                onUpdatePreferences({
                  ...preferences,
                  web_search_enabled: !preferences.web_search_enabled,
                });
              }
            }}
            disabled={isLoading || isBlocked}
            title={preferences?.web_search_enabled ? 'Web Search: ON — click to disable' : 'Web Search: OFF — click to enable'}
          >
            🌐
          </button>

          <textarea
            className="message-input"
            placeholder={isBlocked
              ? "This conversation has been closed. Please start a new conversation."
              : conversation.messages.length > 0 
                ? "Ask a follow-up question... (Shift+Enter for new line, Enter to send)" 
                : "Ask your question... (Shift+Enter for new line, Enter to send)"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={isLoading || !!enhanceState || isBlocked}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={(!input.trim() && attachments.length === 0) || isLoading || !!enhanceState || isBlocked}
          >
            {conversation.messages.length > 0 ? 'Follow Up' : 'Send'}
          </button>
        </div>
        
        <div className="input-hint">
          {isBlocked
            ? "🛡️ This conversation is closed — please start a new conversation"
            : conversation.messages.length > 0 
              ? "Continue the conversation with follow-up questions" 
              : "Paste images or attach PDF, PPTX, XLSX, DOCX, MD files (max 10MB each)"}
        </div>
      </form>
    </div>
  );
}
