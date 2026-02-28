import { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense, memo } from 'react';
import SciMarkdown from './SciMarkdown';
const Stage1 = lazy(() => import('./Stage1'));
const Stage2 = lazy(() => import('./Stage2'));
const Stage3 = lazy(() => import('./Stage3'));
import InfographicPanel from './InfographicPanel';
import TokenBurndown from './TokenBurndown';
import LearnUnlearn from './LearnUnlearn';
import EnhancePrompt from './EnhancePrompt';
import { api } from '../api';
import './ChatInterface.css';

/** Lightweight placeholder shown while a lazy-loaded Stage chunk is fetched. */
const StageFallback = () => <div className="stage-loading-placeholder" aria-busy="true">Loading…</div>;

// ── Rotating Quotes ─────────────────────────────────────────────────
// Displayed in the empty state and during loading to keep the user
// engaged while the council deliberates.

const COUNCIL_QUOTES = [
  { text: "Every expert was once a beginner.", author: "Helen Hayes" },
  { text: "In the middle of difficulty lies opportunity.", author: "Albert Einstein" },
  { text: "Science is organised knowledge. Wisdom is organised life.", author: "Immanuel Kant" },
  { text: "The best way to predict the future is to create it.", author: "Peter Drucker" },
  { text: "Alone we can do so little; together we can do so much.", author: "Helen Keller" },
  { text: "The whole is greater than the sum of its parts.", author: "Aristotle" },
  { text: "Not everything that counts can be counted.", author: "William Bruce Cameron" },
  { text: "The art of medicine consists of amusing the patient while nature cures the disease.", author: "Voltaire" },
  { text: "Where there is unity, there is always victory.", author: "Publilius Syrus" },
  { text: "A council of wisdom outweighs a throne of power.", author: "Proverb" },
  { text: "The measure of intelligence is the ability to change.", author: "Albert Einstein" },
  { text: "Diversity of opinion in a council breeds clarity of thought.", author: "Herodotus" },
  { text: "By three methods we may learn wisdom: by reflection, by imitation, and by experience.", author: "Confucius" },
  { text: "The greatest enemy of knowledge is not ignorance — it is the illusion of knowledge.", author: "Daniel J. Boorstin" },
  { text: "Research is what I'm doing when I don't know what I'm doing.", author: "Wernher von Braun" },
];

const LOADING_QUOTES = [
  "Models are deliberating...",
  "Gathering collective intelligence...",
  "Cross-referencing perspectives...",
  "Applying peer review...",
  "Synthesising expert opinions...",
  "Evaluating evidence quality...",
  "Building consensus...",
  "Checking for bias...",
  "Aggregating insights...",
  "Weighing the council's vote...",
];

/**
 * Cycles through an array of items at a fixed interval.
 * Returns the current item — updates every `intervalMs`.
 */
function useRotatingItem(items, intervalMs = 5000, active = true) {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * items.length));
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      setIndex(prev => (prev + 1) % items.length);
    }, intervalMs);
    return () => clearInterval(id);
  }, [items.length, intervalMs, active]);
  return items[index];
}

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

const MAX_FILE_SIZE_BLOB   = 200 * 1024 * 1024; // 200MB via Azure Blob SAS upload
const MAX_FILE_SIZE_INLINE = 10 * 1024 * 1024;  // 10MB via base64 JSON body (fallback)

export default function ChatInterface({
  conversation,
  onSendMessage,
  onResume,
  isLoading,
  preferences,
  onUpdatePreferences,
}) {
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [attachmentError, setAttachmentError] = useState(null);
  const [enhanceState, setEnhanceState] = useState(null); // null | 'loading' | 'ready'
  const [enhancedData, setEnhancedData] = useState(null); // { original, enhanced }

  // Rotating quotes for empty state and loading indicator
  const councilQuote = useRotatingItem(COUNCIL_QUOTES, 6000, !isLoading);
  const loadingQuote = useRotatingItem(LOADING_QUOTES, 3500, isLoading);

  // When no conversation is selected yet (lazy-create mode), render
  // a synthetic empty conversation so the input form is visible and
  // the user can start typing immediately.
  const conv = conversation || { messages: [], blocked: false };

  // Conversation blocked by prompt guard — disable all input
  const isBlocked = !!(conv?.blocked);
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const userScrolledAwayRef = useRef(false);
  const isStreamingRef = useRef(false);

  const scrollToBottom = useCallback((force = false) => {
    if (!messagesContainerRef.current) return;
    // During active streaming: always scroll unless user grabbed the scrollbar
    // Outside streaming: only scroll if near the bottom (within 200px)
    if (force || !userScrolledAwayRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, []);

  // Track whether user manually scrolled up (only while streaming)
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    let lastScrollTop = container.scrollTop;
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      // User scrolled UP → they want to read previous content
      if (scrollTop < lastScrollTop && distanceFromBottom > 300) {
        userScrolledAwayRef.current = true;
      }
      // User scrolled back to near bottom → re-enable auto-scroll
      if (distanceFromBottom < 100) {
        userScrolledAwayRef.current = false;
      }
      lastScrollTop = scrollTop;
    };
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  // Auto-scroll during streaming — fires as content arrives
  useEffect(() => {
    if (!conversation) return;
    const msgs = conversation.messages || [];
    const last = msgs[msgs.length - 1];
    const streaming = !!(last?.loading?.stage1 || last?.loading?.stage2 || last?.loading?.stage3);
    isStreamingRef.current = streaming;
    if (streaming) {
      scrollToBottom();
    }
  }, [
    conversation?.messages?.length,
    conversation?.messages?.[conversation?.messages?.length - 1]?.stage1?.length,
    conversation?.messages?.[conversation?.messages?.length - 1]?.stage2?.length,
    conversation?.messages?.[conversation?.messages?.length - 1]?.stage3?.response,
    conversation?.messages?.[conversation?.messages?.length - 1]?.loading,
    scrollToBottom,
  ]);

  const validateFile = (file) => {
    // Check file type — also allow by extension for .md files (browsers may report text/plain)
    const isAllowedType = ALLOWED_FILE_TYPES[file.type];
    const isMarkdownByExt = file.name.endsWith('.md') || file.name.endsWith('.markdown');
    if (!isAllowedType && !isMarkdownByExt) {
      const allowedExts = Object.values(ALLOWED_FILE_TYPES).map(t => t.ext).join(', ');
      return `Invalid file type. Allowed: ${allowedExts}`;
    }
    
    // Check file size — blob upload supports 200MB, inline fallback 10MB
    if (file.size > MAX_FILE_SIZE_BLOB) {
      return `File too large. Maximum size: ${MAX_FILE_SIZE_BLOB / (1024 * 1024)}MB`;
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

      // Unique ID for tracking upload state
      const uid = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

      // Add file entry immediately (with uploading state)
      setAttachments(prev => [...prev, {
        _uid: uid,
        name: file.name,
        type: file.type,
        size: file.size,
        base64: '',
        blob_name: '',
        uploading: true,
        progress: 0,
      }]);

      // Try Azure Blob SAS upload first; fall back to base64
      try {
        const { upload_url, blob_name } = await api.getUploadUrl(file.name, file.type, file.size);
        await api.uploadToBlob(upload_url, file, (pct) => {
          setAttachments(prev => prev.map(a =>
            a._uid === uid ? { ...a, progress: pct } : a
          ));
        });
        // Upload complete — store blob reference
        setAttachments(prev => prev.map(a =>
          a._uid === uid ? { ...a, uploading: false, progress: 100, blob_name } : a
        ));
      } catch {
        // Blob not available — fall back to base64 (respects inline limit)
        if (file.size > MAX_FILE_SIZE_INLINE) {
          setAttachments(prev => prev.filter(a => a._uid !== uid));
          setAttachmentError(`File too large for inline upload: ${file.name}. Maximum: ${MAX_FILE_SIZE_INLINE / (1024 * 1024)}MB`);
          continue;
        }
        const reader = new FileReader();
        reader.onload = () => {
          const base64 = reader.result.split(',')[1];
          setAttachments(prev => prev.map(a =>
            a._uid === uid ? { ...a, uploading: false, progress: 100, base64 } : a
          ));
        };
        reader.onerror = () => {
          setAttachments(prev => prev.filter(a => a._uid !== uid));
          setAttachmentError(`Failed to read file: ${file.name}`);
        };
        reader.readAsDataURL(file);
      }
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
    const anyUploading = attachments.some(a => a.uploading);
    if ((input.trim() || attachments.length > 0) && !anyUploading && !isLoading && !enhanceState && !isBlocked) {
      // Reset scroll tracking and force scroll to bottom for new message
      userScrolledAwayRef.current = false;
      scrollToBottom(true);
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

  if (!conv) {
    return null; // defensive — should never happen since conv has a default
  }

  return (
    <div className="chat-interface" id="main-content" role="main">
      <div className="messages-container" ref={messagesContainerRef}>
        {conv.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Consult the LLM Council</h2>
            <p className="empty-state-subtitle">Ask a pharmaceutical, scientific, or clinical question</p>
            <blockquote className="rotating-quote" aria-live="polite">
              <p>"{councilQuote.text}"</p>
              <footer>— {councilQuote.author}</footer>
            </blockquote>
          </div>
        ) : (
          conv.messages.map((msg, index) => (
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
                      <span>
                        {msg.stage1Progress && msg.stage1Progress.completed > 0
                          ? `Running Stage 1: ${msg.stage1Progress.completed} of ${msg.stage1Progress.total} models responded...`
                          : 'Running Stage 1: Collecting individual responses...'}
                      </span>
                    </div>
                  )}
                  <Suspense fallback={<StageFallback />}>
                    {msg.stage1 && <Stage1 responses={msg.stage1} />}
                  </Suspense>

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>
                        {msg.loading.stage2_total > 0
                          ? `Running Stage 2: ${msg.loading.stage2_completed} of ${msg.loading.stage2_total} peer rankings received...`
                          : 'Running Stage 2: Peer rankings...'}
                      </span>
                    </div>
                  )}
                  <Suspense fallback={<StageFallback />}>
                    {msg.stage2 && (
                      <Stage2
                        rankings={msg.stage2}
                        labelToModel={msg.metadata?.label_to_model}
                        aggregateRankings={msg.metadata?.aggregate_rankings}
                        groundingScores={msg.metadata?.grounding_scores}
                      />
                    )}
                  </Suspense>

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>{msg.targetedFollowup
                        ? `⚡ Focused follow-up on ${msg.targetedFollowup.target}...`
                        : 'Running Stage 3: Final synthesis...'}</span>
                    </div>
                  )}
                  <Suspense fallback={<StageFallback />}>
                    {msg.stage3 && <Stage3 finalResponse={msg.stage3} evidence={msg.evidence || msg.metadata?.evidence} />}
                  </Suspense>

                  {/* Empty assistant message fallback — pipeline errored or data missing */}
                  {!msg.stage1 && !msg.stage2 && !msg.stage3
                    && !msg.loading?.stage1 && !msg.loading?.stage2 && !msg.loading?.stage3
                    && !isLoading && (
                    <div className="pipeline-error-state" role="alert">
                      <span className="pipeline-error-icon">⚠️</span>
                      <span>Council response unavailable — the pipeline may have encountered an error. Try sending your question again.</span>
                    </div>
                  )}

                  {/* Self-healing Resume Button */}
                  {msg._canResume && !isLoading && onResume && (
                    <div className="resume-pipeline-banner" role="alert">
                      <button
                        className="resume-pipeline-button"
                        onClick={onResume}
                        aria-label={`Resume pipeline from ${msg._resumeFrom || 'checkpoint'}`}
                      >
                        🔄 Resume from {msg._resumeFrom || 'checkpoint'}
                      </button>
                      <span className="resume-hint">
                        Stages already completed are preserved — only remaining stages will run.
                      </span>
                    </div>
                  )}

                  {/* Infographic Panel */}
                  {(msg.infographic || msg.metadata?.infographic) && <InfographicPanel data={msg.infographic || msg.metadata?.infographic} />}

                  {/* Cost / Token Burndown */}
                  {(msg.costSummary || msg.metadata?.cost_summary) && <TokenBurndown costSummary={msg.costSummary || msg.metadata?.cost_summary} />}

                  {/* Memory Learn/Unlearn Controls */}
                  {(msg.memoryLearning || msg.metadata?.memory_learning) && (
                    <LearnUnlearn
                      learningData={msg.memoryLearning || msg.metadata?.memory_learning}
                      memoryRecall={msg.memoryRecall || msg.metadata?.memory_recall}
                      memoryGate={msg.memoryGate || msg.metadata?.memory_gate}
                    />
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && !conv.messages.some(m => m.loading) && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span className="loading-quote" aria-live="polite">{loadingQuote}</span>
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
        {conv.messages.length > 0 && (
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
              const lastAssistant = [...conv.messages].reverse().find(m => m.role === 'assistant');
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
              <div key={file._uid || index} className="attachment-chip">
                <span className="attachment-icon">{getFileIcon(file.type)}</span>
                <span className="attachment-name">{file.name}</span>
                <span className="attachment-size">({formatFileSize(file.size)})</span>
                {file.uploading && (
                  <span className="attachment-progress">
                    <span className="attachment-progress-bar" style={{ width: `${file.progress}%` }} />
                    <span className="attachment-progress-text">{file.progress}%</span>
                  </span>
                )}
                {!file.uploading && file.blob_name && (
                  <span className="attachment-cloud" title="Uploaded to Azure Blob">☁</span>
                )}
                <button
                  type="button"
                  className="attachment-remove"
                  onClick={() => removeAttachment(index)}
                  disabled={isLoading || file.uploading}
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

          {/* Speed Mode Toggle — visible quick toggle */}
          <button
            type="button"
            className={`speed-mode-btn ${preferences?.speed_mode ? 'active' : ''}`}
            onClick={() => {
              if (onUpdatePreferences && preferences) {
                onUpdatePreferences({
                  ...preferences,
                  speed_mode: !preferences.speed_mode,
                });
              }
            }}
            disabled={isLoading || isBlocked}
            title={preferences?.speed_mode ? 'Speed Mode: ON — faster pipeline, streamlined evaluations. Click to disable' : 'Speed Mode: OFF — full pipeline with claim analysis. Click to enable'}
          >
            ⚡
          </button>

          <textarea
            className="message-input"
            placeholder={isBlocked
              ? "This conversation has been closed. Please start a new conversation."
              : conv.messages.length > 0 
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
            disabled={(!input.trim() && attachments.length === 0) || attachments.some(a => a.uploading) || isLoading || !!enhanceState || isBlocked}
          >
            {conv.messages.length > 0 ? 'Follow Up' : 'Send'}
          </button>
        </div>
        
        <div className="input-hint">
          {isBlocked
            ? "🛡️ This conversation is closed — please start a new conversation"
            : conv.messages.length > 0 
              ? "Continue the conversation with follow-up questions" 
              : "Paste images or attach PDF, PPTX, XLSX, DOCX, MD files (max 200MB each via Azure Blob)"}
        </div>
      </form>
    </div>
  );
}
