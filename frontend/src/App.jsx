import { useState, useEffect, useCallback, useRef } from 'react';
import { useIsAuthenticated, useMsal } from '@azure/msal-react';
import { InteractionStatus } from '@azure/msal-browser';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import Settings from './components/Settings';
import KillSwitch from './components/KillSwitch';
import MemoryPanel from './components/MemoryPanel';
import PromptAtlas3D from './components/PromptAtlas3D';
import { api } from './api';
import { currentEnvironment } from './enviroments/env.js';
import { loginRequest } from './authConfig.js';
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
  // ── Azure SSO: gate the UI behind authentication ──────────────────
  const needsAuth = currentEnvironment === 'azure';
  const isAuthenticated = needsAuth ? useIsAuthenticated() : true;
  const { instance: msalInstance, inProgress } = needsAuth ? useMsal() : { instance: null, inProgress: 'none' };

  const handleLogin = () => {
    if (msalInstance) {
      msalInstance.loginRedirect(loginRequest);
    }
  };

  const handleLogout = () => {
    if (msalInstance) {
      msalInstance.logoutRedirect({ postLogoutRedirectUri: window.location.origin });
    }
  };

  // Show login screen while MSAL is loading or user is not authenticated
  if (needsAuth && inProgress !== InteractionStatus.None) {
    return (
      <div className="auth-loading">
        <div className="auth-loading-spinner" />
        <p>Authenticating with Bayer Entra ID...</p>
      </div>
    );
  }

  if (needsAuth && !isAuthenticated) {
    return (
      <div className="auth-login-screen">
        <div className="auth-login-card">
          <h1>🏛️ LLM Council</h1>
          <p>Sign in with your Bayer CWID to access the LLM Council.</p>
          <button className="auth-login-button" onClick={handleLogin}>
            Sign in with Microsoft
          </button>
        </div>
      </div>
    );
  }

  // ── Extract user display name from MSAL account ──────────────────
  // The account object contains: username (UPN/email), name (display name)
  let userDisplayName = null;
  if (msalInstance) {
    const account = msalInstance.getActiveAccount() || msalInstance.getAllAccounts()[0];
    if (account) {
      // Prefer display name, fallback to username (CWID@bayer.com)
      userDisplayName = account.name || account.username || null;
    }
  }

  // ── Authenticated app ─────────────────────────────────────────────
  return <AuthenticatedApp handleLogout={needsAuth ? handleLogout : null} userDisplayName={userDisplayName} />;
}

function AuthenticatedApp({ handleLogout, userDisplayName }) {
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
  const [errorBanner, setErrorBanner] = useState(null);

  // Track completed stages for self-healing resume
  const completedStagesRef = useRef(new Set());
  const resumeConvIdRef = useRef(null);

  // Auto-dismiss error banner after 8 seconds
  useEffect(() => {
    if (!errorBanner) return;
    const t = setTimeout(() => setErrorBanner(null), 8000);
    return () => clearTimeout(t);
  }, [errorBanner]);

  // ── RAF-batched state updater (replaces flushSync) ────────────
  // Queues state updates and flushes them all in a single animation
  // frame, collapsing 20+ SSE events into ~1-2 React renders.
  const pendingUpdateRef = useRef(null);
  const rafIdRef = useRef(null);

  const batchedStreamUpdate = useCallback((updater) => {
    // Chain updaters: each one receives the result of the previous
    if (pendingUpdateRef.current) {
      const prev = pendingUpdateRef.current;
      pendingUpdateRef.current = (state) => updater(prev(state));
    } else {
      pendingUpdateRef.current = updater;
    }

    // Schedule a single RAF flush
    if (!rafIdRef.current) {
      rafIdRef.current = requestAnimationFrame(() => {
        const finalUpdater = pendingUpdateRef.current;
        pendingUpdateRef.current = null;
        rafIdRef.current = null;
        if (finalUpdater) {
          setCurrentConversation(finalUpdater);
        }
      });
    }
  }, []);

  // Cleanup RAF on unmount
  useEffect(() => {
    return () => {
      if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
    };
  }, []);

  // Deduplicated loadConversations with guard ref
  const loadingConvsRef = useRef(false);
  const loadConversations = useCallback(async () => {
    if (loadingConvsRef.current) return;
    loadingConvsRef.current = true;
    try {
      const convs = await api.listConversations();
      // Filter out empty conversations (0 messages) that were created
      // before the lazy-create logic was added.  Keeps sidebar clean.
      setConversations(convs.filter(c => c.message_count > 0));
    } catch (error) {
      console.error('Failed to load conversations:', error);
      setErrorBanner(`Failed to load conversations: ${error.message}`);
    } finally {
      loadingConvsRef.current = false;
    }
  }, []);

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

  // (loadConversations is defined above as a useCallback)

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = () => {
    // Just clear the current selection — the actual backend conversation
    // is created lazily in handleSendMessage when the user sends the
    // first message.  This prevents empty "New Conversation" entries
    // from accumulating in storage.
    setCurrentConversationId(null);
    setCurrentConversation(null);
    setErrorBanner(null);
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
    // Auto-create conversation if none selected (removes manual "+ New Conversation" friction)
    let convId = currentConversationId;
    if (!convId) {
      try {
        const newConv = await api.createConversation();
        convId = newConv.id;
        setConversations(prev => [
          { id: newConv.id, created_at: newConv.created_at, title: 'New Conversation', message_count: 0 },
          ...prev,
        ]);
        setCurrentConversationId(convId);
        setCurrentConversation(newConv);
      } catch (error) {
        console.error('Auto-create conversation failed:', error);
        setErrorBanner(`Failed to create conversation: ${error.message}`);
        return;
      }
    }

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

      // Use RAF-batched updater to coalesce rapid SSE events into fewer
      // React renders (replaces flushSync which forced synchronous paints).
      const streamUpdate = batchedStreamUpdate;

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

      // Reset resume tracking for this new request
      completedStagesRef.current = new Set();
      resumeConvIdRef.current = convId;

      // Send message with streaming (include attachments and preferences)
      await api.sendMessageStream(
        convId, 
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
            completedStagesRef.current.add('stage1');
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
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              if (!msg.stage2) msg.stage2 = [];
              msg.stage2 = [...msg.stage2, event.data];
              msg.loading.stage2_completed = event.progress?.completed || msg.stage2.length;
              msg.loading.stage2_total = event.progress?.total || 0;
            }));
            break;

          case 'stage2_complete':
            completedStagesRef.current.add('stage2');
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
            completedStagesRef.current.add('stage3');
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

          case 'relevancy_gate':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.relevancyGate = event.data;
              // Also store in metadata for persistence
              if (msg.metadata) {
                msg.metadata.relevancy_gate = event.data?.gate;
              }
            }));
            break;

          case 'user_behaviour_update':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.userBehaviour = event.data;
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

          case 'context_classified':
            // Store domain/topic context tags for the conversation
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.contextTags = event.data;
            }));
            break;

          case 'title_complete':
            // Reload conversations to get updated title + context tags
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

      // Determine if we can offer a resume (at least Stage 1 completed)
      const hasCheckpoint = completedStagesRef.current.has('stage1') || completedStagesRef.current.has('stage2');
      const nextStage = completedStagesRef.current.has('stage2')
        ? 'Stage 3'
        : completedStagesRef.current.has('stage1')
        ? 'Stage 2'
        : null;

      // Show error with resume option if stages were partially completed
      setCurrentConversation((prev) => {
        if (!prev) return prev;
        const messages = [...prev.messages];
        const idx = messages.length - 1;
        if (idx >= 0) {
          const lastMsg = { ...messages[idx], loading: { ...messages[idx].loading } };
          if (lastMsg.role === 'assistant') {
            lastMsg.loading = { stage1: false, stage2: false, stage3: false };
            if (!lastMsg.stage3) {
              const resumeHint = hasCheckpoint
                ? `\n\n🔄 **Pipeline checkpoint saved.** Click **Resume** below to continue from ${nextStage}.`
                : '\n\nYou can try sending your message again.';
              lastMsg.stage3 = {
                model: 'system',
                response: `⚠ **Connection Error**\n\n${friendlyMsg}${resumeHint}`,
              };
              // Embed resumability flag for ChatInterface to render button
              lastMsg._canResume = hasCheckpoint;
              lastMsg._resumeFrom = nextStage;
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

  // ── Self-healing resume: pick up from last checkpoint ──────────
  const handleResume = async () => {
    const convId = resumeConvIdRef.current || currentConversationId;
    if (!convId) return;

    setIsLoading(true);

    // Clear the error stage3 — keep existing stage1/stage2 data
    setCurrentConversation((prev) => {
      if (!prev) return prev;
      const messages = [...prev.messages];
      const idx = messages.length - 1;
      if (idx >= 0 && messages[idx].role === 'assistant') {
        const msg = { ...messages[idx], loading: { ...messages[idx].loading } };
        // If stage3 was the error placeholder, remove it and show loading
        if (msg.stage3?.model === 'system') {
          msg.stage3 = null;
        }
        msg._canResume = false;
        msg.loading = { stage1: false, stage2: false, stage3: true };
        messages[idx] = msg;
      }
      return { ...prev, messages };
    });

    // Helper reused from handleSendMessage
    const cloneLastMsg = (prev, updater) => {
      const messages = [...prev.messages];
      const idx = messages.length - 1;
      if (idx < 0) return prev;
      const msg = { ...messages[idx], loading: { ...messages[idx].loading } };
      updater(msg);
      messages[idx] = msg;
      return { ...prev, messages };
    };
    const streamUpdate = batchedStreamUpdate;

    try {
      await api.resumeStream(convId, (eventType, event) => {
        switch (eventType) {
          case 'session_start':
            setActiveSessionId(event.data?.session_id || null);
            break;
          case 'stage1_complete':
            completedStagesRef.current.add('stage1');
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.stage1 = event.data;
              msg.loading.stage1 = false;
            }));
            break;
          case 'stage2_start':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.loading.stage2 = true;
            }));
            break;
          case 'stage2_model_response':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              if (!msg.stage2) msg.stage2 = [];
              msg.stage2 = [...msg.stage2, event.data];
            }));
            break;
          case 'stage2_complete':
            completedStagesRef.current.add('stage2');
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
            completedStagesRef.current.add('stage3');
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.stage3 = event.data;
              msg.loading.stage3 = false;
            }));
            break;
          case 'evidence_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.evidence = event.data;
            }));
            break;
          case 'relevancy_gate':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.relevancyGate = event.data;
            }));
            break;
          case 'cost_summary':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.costSummary = event.data;
            }));
            break;
          case 'infographic_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.infographic = event.data;
            }));
            break;
          case 'agent_team_complete':
            streamUpdate((prev) => cloneLastMsg(prev, msg => {
              msg.agentTeam = event.data;
            }));
            break;
          case 'doubting_thomas_complete':
            // DT is informational during resume
            break;
          case 'complete':
            loadConversations();
            setIsLoading(false);
            setActiveSessionId(null);
            break;
          case 'error':
            console.error('Resume stream error:', event.message);
            setIsLoading(false);
            setActiveSessionId(null);
            break;
          default:
            break;
        }
      }, preferences);
    } catch (error) {
      console.error('Resume failed:', error);
      const rawMsg = error?.message || String(error);
      // Show error but keep existing data
      setCurrentConversation((prev) => {
        if (!prev) return prev;
        const messages = [...prev.messages];
        const idx = messages.length - 1;
        if (idx >= 0 && messages[idx].role === 'assistant') {
          const msg = { ...messages[idx], loading: { stage1: false, stage2: false, stage3: false } };
          if (!msg.stage3 || msg.stage3.model === 'system') {
            msg.stage3 = {
              model: 'system',
              response: `⚠ **Resume Failed**\n\n${rawMsg}\n\nYou can try again or send a new message.`,
            };
          }
          msg._canResume = completedStagesRef.current.has('stage1') || completedStagesRef.current.has('stage2');
          messages[idx] = msg;
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
          onLogout={handleLogout}
          userDisplayName={userDisplayName}
        />
      </nav>
      <main id="main-content" role="main" aria-label="Chat area">
        {errorBanner && (
          <div className="error-banner" role="alert" aria-live="assertive">
            <span>{errorBanner}</span>
            <button onClick={() => setErrorBanner(null)} aria-label="Dismiss error">&times;</button>
          </div>
        )}
        <ChatInterface
          conversation={currentConversation}
          onSendMessage={handleSendMessage}
          onResume={handleResume}
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
      {/* Sign Out moved to Sidebar footer — see Sidebar.jsx */}
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
