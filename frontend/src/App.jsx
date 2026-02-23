import { useState, useEffect } from 'react';
import { flushSync } from 'react-dom';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import Settings from './components/Settings';
import KillSwitch from './components/KillSwitch';
import MemoryPanel from './components/MemoryPanel';
import PromptAtlas3D from './components/PromptAtlas3D';
import { api } from './api';
import './App.css';

// Load preferences from localStorage
const loadPreferences = () => {
  try {
    const stored = localStorage.getItem('llm-council-preferences');
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (e) {
    console.error('Failed to load preferences:', e);
  }
  return { council_models: null, chairman_model: null, web_search_enabled: false };
};

// Save preferences to localStorage
const savePreferences = (prefs) => {
  try {
    localStorage.setItem('llm-council-preferences', JSON.stringify(prefs));
  } catch (e) {
    console.error('Failed to save preferences:', e);
  }
};

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showMemory, setShowMemory] = useState(false);
  const [atlasOpen, setAtlasOpen] = useState(true);
  const [atlasWidth, setAtlasWidth] = useState(480);
  const [preferences, setPreferences] = useState(loadPreferences);
  const [activeSessionId, setActiveSessionId] = useState(null);

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleSavePreferences = (newPrefs) => {
    setPreferences(newPrefs);
    savePreferences(newPrefs);
  };

  const handleExportConversation = async (conversationId) => {
    try {
      const exportData = await api.exportConversation(conversationId, 'markdown');
      
      // Create a blob and download it
      const blob = new Blob([exportData.content], { type: exportData.content_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = exportData.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export conversation:', error);
      alert('Failed to export conversation');
    }
  };

  const handleDeleteConversation = async (conversationId) => {
    if (!confirm('Are you sure you want to delete this conversation?')) {
      return;
    }
    
    try {
      await api.deleteConversation(conversationId);
      
      // Remove from list
      setConversations(prev => prev.filter(c => c.id !== conversationId));
      
      // If deleted the current conversation, clear it
      if (conversationId === currentConversationId) {
        setCurrentConversationId(null);
        setCurrentConversation(null);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      alert('Failed to delete conversation');
    }
  };

  const handleSendMessage = async (content, attachments = []) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      // Build user message content including attachment info
      let userMessageContent = content;
      if (attachments.length > 0) {
        const attachmentList = attachments.map(a => `📎 ${a.name}`).join('\n');
        userMessageContent = content 
          ? `${content}\n\n---\nAttachments:\n${attachmentList}`
          : `Attachments:\n${attachmentList}`;
      }

      // Optimistically add user message to UI
      const userMessage = { role: 'user', content: userMessageContent };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Helper: immutably update the last assistant message.
      // Clones both the message object and its loading sub-object so
      // React detects changes at every level of the component tree.
      const cloneLastMsg = (prev, updater) => {
        const messages = [...prev.messages];
        const idx = messages.length - 1;
        if (idx < 0) return prev;
        const msg = { ...messages[idx], loading: { ...messages[idx].loading } };
        updater(msg);
        messages[idx] = msg;
        return { ...prev, messages };
      };

      // Wrap state updates in flushSync so the UI re-renders immediately
      // on each stream event. Without this, React batches updates in production
      // and the UI stays frozen until the stream completes.
      const streamUpdate = (updater) => {
        flushSync(() => setCurrentConversation(updater));
      };

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        costSummary: null,
        memoryRecall: null,
        memoryGate: null,
        memoryLearning: null,
        agentTeam: null,
        evidence: null,
        infographic: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming (include attachments and preferences)
      await api.sendMessageStream(
        currentConversationId, 
        content, 
        (eventType, event) => {
        switch (eventType) {
          case 'session_start':
            // Capture session ID for kill switch targeting
            setActiveSessionId(event.data?.session_id || null);
            break;

          case 'stage1_start':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.loading.stage1 = true;
              msg.stage1Progress = { completed: 0, failed: 0, total: 0 };
            }));
            break;

          case 'stage1_model_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              if (!msg.stage1) msg.stage1 = [];
              msg.stage1 = [...msg.stage1, event.data];
              msg.stage1Progress = event.progress;
            }));
            break;

          case 'stage1_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.stage1 = event.data;
              msg.loading.stage1 = false;
              delete msg.stage1Progress;
            }));
            break;

          case 'stage2_start':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.loading.stage2 = true;
              msg.loading.stage2_completed = 0;
              msg.loading.stage2_total = 0;
            }));
            break;

          case 'stage2_model_response':
            // Incremental: display each ranking as it arrives
            setCurrentConversation((prev) => cloneLastMsg(prev, msg => {
              if (!msg.stage2) msg.stage2 = [];
              msg.stage2 = [...msg.stage2, event.data];
              msg.loading.stage2_completed = event.progress?.completed || msg.stage2.length;
              msg.loading.stage2_total = event.progress?.total || 0;
            }));
            break;

          case 'stage2_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.stage2 = event.data;
              msg.metadata = event.metadata;
              msg.loading.stage2 = false;
            }));
            break;

          case 'stage3_start':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.loading.stage3 = true;
            }));
            break;

          case 'stage3_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.stage3 = event.data;
              msg.loading.stage3 = false;
            }));
            break;

          case 'cost_summary':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.costSummary = event.data;
            }));
            break;

          case 'memory_recall':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.memoryRecall = event.data;
            }));
            break;

          case 'memory_gate':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.memoryGate = event.data;
            }));
            break;

          case 'evidence_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.evidence = event.data;
            }));
            break;

          case 'infographic_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.infographic = event.data;
            }));
            break;

          case 'ca_validation_complete':
            // Update grounding scores with enhanced CA (multi-round + adversarial)
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              if (event.data?.grounding_scores && msg.metadata) {
                msg.metadata.grounding_scores = event.data.grounding_scores;
              }
            }));
            break;

          case 'agent_team_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.agentTeam = event.data;
            }));
            break;

          case 'memory_learning':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.memoryLearning = event.data;
            }));
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            setActiveSessionId(null);
            break;

          case 'killed':
            // Session was killed by user via kill switch
            console.warn('Session killed:', event.message);
            setIsLoading(false);
            setActiveSessionId(null);
            // Update the last assistant message to show killed state
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              if (msg.role === 'assistant') {
                msg.loading = { stage1: false, stage2: false, stage3: false };
                if (!msg.stage3) {
                  msg.stage3 = {
                    model: 'system',
                    response: '⏹ **Council session stopped by user.**'
                  };
                }
              }
            }));
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            setActiveSessionId(null);
            break;

          case 'prompt_rejected':
            // Prompt was blocked by the suitability guard
            console.warn('Prompt rejected:', event.data?.category);
            setIsLoading(false);
            setActiveSessionId(null);
            // Show the rejection as a system message in the assistant slot
            streamUpdate((prev) => {
              const messages = [...prev.messages];
              const idx = messages.length - 1;
              if (idx < 0) return prev;
              const lastMsg = { ...messages[idx], loading: { ...messages[idx].loading } };
              if (lastMsg.role === 'assistant') {
                lastMsg.loading = { stage1: false, stage2: false, stage3: false };
                lastMsg.stage3 = {
                  model: 'system',
                  response: `🛡️ **Prompt Review — ${event.data?.category?.replace(/_/g, ' ') || 'Policy Check'}**\n\n${event.data?.message || 'This query could not be processed.'}`,
                };
                lastMsg.rejected = true;
              }
              messages[idx] = lastMsg;
              // Mark conversation as blocked in local state
              return { ...prev, blocked: true, messages };
            });
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      },
      attachments
      , preferences);
    } catch (error) {
      console.error('Failed to send message:', error);

      // Build a human-readable error message
      const rawMsg = error?.message || String(error);
      // Strip proxy boilerplate if present
      const friendlyMsg = rawMsg.includes('firewall')
        ? 'The corporate network proxy closed the connection. Please check your VPN and retry.'
        : rawMsg.includes('timed out')
        ? 'The request timed out — the LLM API may be slow. Please retry.'
        : rawMsg.includes('ERR_CONNECTION')
        ? 'Connection to the backend was lost. Please refresh and retry.'
        : rawMsg;

      // Instead of silently removing messages, show an error stage3
      setCurrentConversation((prev) => {
        if (!prev) return prev;
        const messages = [...prev.messages];
        const idx = messages.length - 1;
        if (idx >= 0) {
          const lastMsg = { ...messages[idx], loading: { ...messages[idx].loading } };
          if (lastMsg.role === 'assistant') {
            lastMsg.loading = { stage1: false, stage2: false, stage3: false };
            if (!lastMsg.stage3) {
              lastMsg.stage3 = {
                model: 'system',
                response: `⚠ **Connection Error**\n\n${friendlyMsg}\n\nYou can try sending your message again.`,
              };
            }
            messages[idx] = lastMsg;
          } else {
            // Fallback: remove optimistic messages
            return { ...prev, messages: prev.messages.slice(0, -2) };
          }
        }
        return { ...prev, messages };
      });
      setIsLoading(false);
    }
  };

  const handleKilled = (type) => {
    setIsLoading(false);
    setActiveSessionId(null);
    if (type === 'global') {
      // On global halt, update UI to reflect system state
      setCurrentConversation((prev) => {
        if (!prev) return prev;
        const messages = [...prev.messages];
        const idx = messages.length - 1;
        if (idx >= 0) {
          const lastMsg = { ...messages[idx], loading: { ...messages[idx].loading } };
          if (lastMsg.role === 'assistant') {
            lastMsg.loading = { stage1: false, stage2: false, stage3: false };
            if (!lastMsg.stage3) {
              lastMsg.stage3 = {
                model: 'system',
                response: '⚠ **Emergency halt activated — all sessions stopped.**'
              };
            }
          }
          messages[idx] = lastMsg;
        }
        return { ...prev, messages };
      });
    }
  };

  return (
    <div className={`app${atlasOpen ? ' atlas-open' : ''}`} style={{ '--atlas-width': `${atlasWidth}px` }}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <nav aria-label="Conversation sidebar">
        <Sidebar
          conversations={conversations}
          currentConversationId={currentConversationId}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          onOpenSettings={() => setShowSettings(true)}
          onExportConversation={handleExportConversation}
          onDeleteConversation={handleDeleteConversation}
        />
      </nav>
      <main id="main-content" role="main" aria-label="Chat area">
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          preferences={preferences}
          onUpdatePreferences={handleSavePreferences}
        />
      </main>
      <aside aria-label="3D Prompt Atlas">
        <PromptAtlas3D
          conversation={currentConversation}
          isOpen={atlasOpen}
          onToggle={() => setAtlasOpen((v) => !v)}
          onWidthChange={setAtlasWidth}
        />
      </aside>
      {/* Kill Switch — always accessible to the end user */}
      <div className="kill-switch-fixed" role="region" aria-label="Emergency controls">
        <KillSwitch
          sessionId={activeSessionId}
          isLoading={isLoading}
          onKilled={handleKilled}
        />
      </div>
      {/* Memory Panel Button */}
      <button
        className="memory-panel-toggle"
        onClick={() => setShowMemory(true)}
        title="Memory Management"
        aria-label="Open memory management panel"
      >
        🧠
      </button>
      <MemoryPanel
        isOpen={showMemory}
        onClose={() => setShowMemory(false)}
      />
      <Settings
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        preferences={preferences}
        onSave={handleSavePreferences}
      />
    </div>
  );
}

export default App;
