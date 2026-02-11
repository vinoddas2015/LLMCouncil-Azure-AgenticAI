import { useState, useEffect } from 'react';
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
  const [atlasOpen, setAtlasOpen] = useState(false);
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
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'cost_summary':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.costSummary = event.data;
              return { ...prev, messages };
            });
            break;

          case 'memory_recall':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.memoryRecall = event.data;
              return { ...prev, messages };
            });
            break;

          case 'memory_gate':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.memoryGate = event.data;
              return { ...prev, messages };
            });
            break;

          case 'evidence_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.evidence = event.data;
              return { ...prev, messages };
            });
            break;

          case 'memory_learning':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.memoryLearning = event.data;
              return { ...prev, messages };
            });
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
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              if (lastMsg && lastMsg.role === 'assistant') {
                lastMsg.loading = { stage1: false, stage2: false, stage3: false };
                if (!lastMsg.stage3) {
                  lastMsg.stage3 = {
                    model: 'system',
                    response: '⏹ **Council session stopped by user.**'
                  };
                }
              }
              return { ...prev, messages };
            });
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            setActiveSessionId(null);
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
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          lastMsg.loading = { stage1: false, stage2: false, stage3: false };
          if (!lastMsg.stage3) {
            lastMsg.stage3 = {
              model: 'system',
              response: `⚠ **Connection Error**\n\n${friendlyMsg}\n\nYou can try sending your message again.`,
            };
          }
        } else {
          // Fallback: remove optimistic messages
          return { ...prev, messages: prev.messages.slice(0, -2) };
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
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          lastMsg.loading = { stage1: false, stage2: false, stage3: false };
          if (!lastMsg.stage3) {
            lastMsg.stage3 = {
              model: 'system',
              response: '⚠ **Emergency halt activated — all sessions stopped.**'
            };
          }
        }
        return { ...prev, messages };
      });
    }
  };

  return (
    <div className={`app${atlasOpen ? ' atlas-open' : ''}`}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onOpenSettings={() => setShowSettings(true)}
        onExportConversation={handleExportConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
        preferences={preferences}
        onUpdatePreferences={handleSavePreferences}
      />
      <PromptAtlas3D
        conversation={currentConversation}
        isOpen={atlasOpen}
        onToggle={() => setAtlasOpen((v) => !v)}
      />
      {/* Kill Switch — always accessible to the end user */}
      <div className="kill-switch-fixed">
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
