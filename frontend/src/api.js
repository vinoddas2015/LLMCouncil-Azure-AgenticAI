/**
 * API client for the LLM Council backend.
 *
 * In development, Vite proxies /api/* to http://localhost:8001
 * so all requests stay on the same origin — avoiding corporate
 * proxy / Zscaler interception of cross-origin localhost calls.
 *
 * In production, the environment config determines the backend URL.
 */

import { config, currentEnvironment } from './enviroments/env.js';

const API_BASE = config.apiBaseUrl;
const AUTH_TOKEN_REFRESH_URL = config.authTokenRefreshUrl;
const TOKEN_STORAGE_KEY = 'LLM-COUNCIL-TOKEN-INFO';

console.log(`[API] Running in ${currentEnvironment} mode, API_BASE: ${API_BASE}`);

/**
 * Store token info in sessionStorage with expiry timestamp.
 * Includes 120-second buffer before actual expiry for safety.
 * @param {Object} token - Token response data
 */
function storeToken(token) {
  const tokenExpiryInMs = Date.now() + ((token.expires_in - 120) * 1000);
  sessionStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify({ ...token, tokenExpiryInMs }));
}

/**
 * Fetch OAuth token from the auth endpoint.
 * @returns {Promise<Object>} Token response data
 */
async function getOAuthTokenInfo() {
  try {
    const response = await fetch(AUTH_TOKEN_REFRESH_URL, {
      method: 'GET',
      cache: 'no-store',
      credentials: 'include',
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch token: HTTP ${response.status}`);
    }

    const result = await response.json();
    const tokenData = result.data || result;
    
    storeToken(tokenData);
    return tokenData;
  } catch (error) {
    console.error('[Auth] Failed to get OAuth token:', error);
    throw error;
  }
}

/**
 * Get valid access token, fetching a new one if expired or missing.
 * @returns {Promise<string>} Valid access token
 */
async function getToken() {
  const currentToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
  const { tokenExpiryInMs = 0, access_token: accessToken = '' } = JSON.parse(currentToken || '{}');
  
  if (!accessToken || Date.now() > tokenExpiryInMs) {
    console.log('[Auth] Token missing or expired, fetching new token');
    const newToken = await getOAuthTokenInfo();
    return newToken.access_token;
  }
  
  return accessToken;
}

/**
 * Wrapper around fetch that automatically adds Authorization header to all requests.
 * This acts as an interceptor for authentication.
 * 
 * In LOCAL environment, authentication is skipped entirely.
 */
async function fetchWithAuth(url, options = {}) {
  // Local development: no OAuth, but include user-id header for storage isolation
  if (currentEnvironment === 'development') {
    return fetch(url, {
      ...options,
      headers: { ...options.headers, 'user-id': 'local-user' },
    });
  }
  
  const token = await getToken();
  
  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`,
  };
  
  return fetch(url, {
    ...options,
    headers,
  });
}

/**
 * Get the current user ID.
 * Cloud: read from the stored token payload (set by auth-token-refresh).
 * Local dev: returns "local-user".
 */
export function getUserId() {
  if (currentEnvironment === 'development') {
    return 'local-user';
  }
  try {
    const stored = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (parsed['user-id']) return parsed['user-id'];
    }
  } catch { /* ignore */ }
  return null;
}

export const api = {
  /**
   * Get available models and defaults.
   */
  async getModels() {
    const response = await fetchWithAuth(`${API_BASE}/api/models`);
    if (!response.ok) {
      throw new Error('Failed to get models');
    }
    return response.json();
  },

  /**
   * Enhance a user prompt using AI to produce a more detailed, specific version.
   * @param {string} content - The original user prompt
   * @returns {Promise<{original: string, enhanced: string}>}
   */
  async enhancePrompt(content) {
    const response = await fetchWithAuth(`${API_BASE}/api/enhance-prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      throw new Error('Failed to enhance prompt');
    }
    return response.json();
  },

  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetchWithAuth(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetchWithAuth(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetchWithAuth(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Export a conversation in the specified format.
   * @param {string} conversationId - The conversation ID
   * @param {string} format - Export format: 'markdown' or 'json'
   * @returns {Promise<{filename: string, content: string, content_type: string}>}
   */
  async exportConversation(conversationId, format = 'markdown') {
    const response = await fetchWithAuth(
      `${API_BASE}/api/conversations/${conversationId}/export?format=${format}`
    );
    if (!response.ok) {
      throw new Error('Failed to export conversation');
    }
    return response.json();
  },

  /**
   * Delete a conversation.
   */
  async deleteConversation(conversationId) {
    const response = await fetchWithAuth(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'DELETE',
      }
    );
    if (!response.ok) {
      throw new Error('Failed to delete conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetchWithAuth(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @param {Array} attachments - Optional array of attachment objects with base64 content
   * @param {Object} preferences - Optional object with council_models and chairman_model
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, attachments = [], preferences = {}) {
    const controller = new AbortController();
    const { signal } = controller;

    // Timeout safety — abort if no data for 180s (corporate proxies often kill at ~120s)
    let lastActivity = Date.now();
    const watchdog = setInterval(() => {
      if (Date.now() - lastActivity > 180_000) {
        controller.abort();
        clearInterval(watchdog);
      }
    }, 10_000);

    try {
      const response = await fetchWithAuth(
        `${API_BASE}/api/conversations/${conversationId}/message/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Connection': 'keep-alive',
          },
          body: JSON.stringify({ 
            content,
            attachments: attachments.map(a => ({
              name: a.name,
              type: a.type,
              size: a.size,
              base64: a.base64,
            })),
            council_models: preferences.council_models || null,
            chairman_model: preferences.chairman_model || null,
            web_search_enabled: preferences.web_search_enabled || false,
          }),
          signal,
        }
      );

      if (!response.ok) {
        // Try to extract a meaningful message from proxy error pages
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.text();
          // Corporate proxies return HTML error pages — extract the useful part
          const reasonMatch = body.match(/Reason:\s*([^<\n]+)/i);
          if (reasonMatch) detail = reasonMatch[1].trim();
          else if (body.length < 500) detail = body;
        } catch { /* ignore */ }
        throw new Error(`Failed to send message: ${detail}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        lastActivity = Date.now();
        buffer += decoder.decode(value, { stream: true });

        // Process complete lines from buffer
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete last line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              const event = JSON.parse(data);
              onEvent(event.type, event);
            } catch (e) {
              console.error('Failed to parse SSE event:', e, 'Raw data:', data);
            }
          }
        }
      }

      // Process any remaining data in buffer
      if (buffer.startsWith('data: ')) {
        try {
          const event = JSON.parse(buffer.slice(6));
          onEvent(event.type, event);
        } catch { /* ignore trailing partial data */ }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error('Connection timed out — the corporate proxy may have closed the connection. Please retry.');
      }
      throw err;
    } finally {
      clearInterval(watchdog);
    }
  },

  // ────────────────────────────────────────────────────────────────────
  // Kill Switch & Health Monitoring API
  // ────────────────────────────────────────────────────────────────────

  /**
   * Kill a specific in-flight council session (primary kill switch).
   * @param {string} sessionId - The session ID received from session_start event
   * @param {string} reason - Optional reason for killing
   */
  async killSession(sessionId, reason = 'User triggered kill switch') {
    const response = await fetchWithAuth(`${API_BASE}/api/kill-switch/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, reason }),
    });
    if (!response.ok) {
      throw new Error('Failed to kill session');
    }
    return response.json();
  },

  /**
   * Emergency global halt — kills ALL sessions and blocks new ones.
   * @param {string} reason - Reason for the halt
   */
  async globalHalt(reason = 'Emergency halt triggered by user') {
    const response = await fetchWithAuth(`${API_BASE}/api/kill-switch/halt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    if (!response.ok) {
      throw new Error('Failed to activate global halt');
    }
    return response.json();
  },

  /**
   * Release global halt to resume normal operation.
   */
  async releaseHalt() {
    const response = await fetchWithAuth(`${API_BASE}/api/kill-switch/release`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to release halt');
    }
    return response.json();
  },

  /**
   * Get kill switch status (active sessions, halt state).
   */
  async getKillSwitchStatus() {
    const response = await fetchWithAuth(`${API_BASE}/api/kill-switch/status`);
    if (!response.ok) {
      throw new Error('Failed to get kill switch status');
    }
    return response.json();
  },

  /**
   * Get full system health: circuits, healing actions, kill switch.
   */
  async getSystemHealth() {
    const response = await fetchWithAuth(`${API_BASE}/api/health`);
    if (!response.ok) {
      throw new Error('Failed to get system health');
    }
    return response.json();
  },

  /**
   * Reset circuit breaker for a model (or all models).
   * @param {string|null} model - Model ID to reset, or null for all
   */
  async resetCircuit(model = null) {
    const url = model
      ? `${API_BASE}/api/health/circuits/reset?model=${encodeURIComponent(model)}`
      : `${API_BASE}/api/health/circuits/reset`;
    const response = await fetchWithAuth(url, { method: 'POST' });
    if (!response.ok) {
      throw new Error('Failed to reset circuit');
    }
    return response.json();
  },

  // ────────────────────────────────────────────────────────────────────
  // Memory Management API
  // ────────────────────────────────────────────────────────────────────

  /**
   * Get memory statistics across all tiers.
   */
  async getMemoryStats() {
    const response = await fetchWithAuth(`${API_BASE}/api/memory/stats`);
    if (!response.ok) throw new Error('Failed to get memory stats');
    return response.json();
  },

  /**
   * List memories for a tier (semantic, episodic, procedural).
   * @param {string} type - Memory tier
   * @param {boolean} includeUnlearned - Whether to include unlearned entries
   */
  async listMemories(type, includeUnlearned = false) {
    const url = `${API_BASE}/api/memory/${type}?include_unlearned=${includeUnlearned}`;
    const response = await fetchWithAuth(url);
    if (!response.ok) throw new Error(`Failed to list ${type} memories`);
    return response.json();
  },

  /**
   * Get a specific memory entry.
   */
  async getMemoryEntry(type, id) {
    const response = await fetchWithAuth(`${API_BASE}/api/memory/${type}/${id}`);
    if (!response.ok) throw new Error('Memory entry not found');
    return response.json();
  },

  /**
   * Apply a learn/unlearn decision.
   * @param {string} decision - "learn" or "unlearn"
   * @param {string} memoryType - "semantic", "episodic", or "procedural"
   * @param {string} memoryId - The memory entry ID
   * @param {string} reason - Optional reason for the decision
   */
  async applyMemoryDecision(decision, memoryType, memoryId, reason = '') {
    const response = await fetchWithAuth(`${API_BASE}/api/memory/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision,
        memory_type: memoryType,
        memory_id: memoryId,
        reason,
      }),
    });
    if (!response.ok) throw new Error('Failed to apply memory decision');
    return response.json();
  },

  /**
   * Search memories by text.
   */
  async searchMemories(type, query, limit = 10) {
    const url = `${API_BASE}/api/memory/search/${type}?q=${encodeURIComponent(query)}&limit=${limit}`;
    const response = await fetchWithAuth(url);
    if (!response.ok) throw new Error('Search failed');
    return response.json();
  },

  /**
   * Delete a memory entry permanently.
   */
  async deleteMemory(type, id) {
    const response = await fetchWithAuth(`${API_BASE}/api/memory/${type}/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to delete memory');
    return response.json();
  },

  /**
   * Run on-demand agent team analysis for an existing conversation.
   */
  async analyzeAgents(conversationId) {
    const response = await fetchWithAuth(
      `${API_BASE}/api/conversations/${conversationId}/analyze-agents`,
      { method: 'POST' }
    );
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Agent analysis failed');
    }
    return response.json();
  },

  /**
   * Download the full A2A agent card bundle as a JSON file.
   */
  async downloadAgentCards() {
    const response = await fetchWithAuth(`${API_BASE}/api/agent-cards-download`);
    if (!response.ok) throw new Error('Failed to download agent cards');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'llm-council-agent-cards.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  /**
   * Trigger a manual model sync from the MyGenAssist catalog.
   */
  async syncModels() {
    const response = await fetchWithAuth(`${API_BASE}/api/models/sync`, { method: 'POST' });
    if (!response.ok) throw new Error('Model sync failed');
    return response.json();
  },

  /**
   * Get model sync status (last sync time, model count, etc.).
   */
  async getSyncStatus() {
    const response = await fetchWithAuth(`${API_BASE}/api/models/sync-status`);
    if (!response.ok) throw new Error('Failed to get sync status');
    return response.json();
  },
};
