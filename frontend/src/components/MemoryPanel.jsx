import { useState, useEffect } from 'react';
import { api } from '../api';
import './MemoryPanel.css';

const TIER_META = {
  semantic: { label: 'Semantic', icon: '🧠', desc: 'What the council knows — stored facts, definitions, and domain knowledge it can recall anytime' },
  episodic: { label: 'Episodic', icon: '📝', desc: 'What the council remembers — specific past questions, answers, and decisions from earlier sessions' },
  procedural: { label: 'Procedural', icon: '⚙️', desc: 'How the council works — learned patterns for ranking, synthesising, and resolving disagreements' },
};

export default function MemoryPanel({ isOpen, onClose }) {
  const [activeTier, setActiveTier] = useState('semantic');
  const [memories, setMemories] = useState([]);
  const [stats, setStats] = useState(null);
  const [showUnlearned, setShowUnlearned] = useState(false);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    if (isOpen) {
      loadStats();
      loadMemories(activeTier);
    }
  }, [isOpen, activeTier, showUnlearned]);

  const loadStats = async () => {
    try {
      const s = await api.getMemoryStats();
      setStats(s);
    } catch (e) {
      console.error('Failed to load memory stats:', e);
    }
  };

  const loadMemories = async (tier) => {
    setLoading(true);
    try {
      const list = await api.listMemories(tier, showUnlearned);
      setMemories(list);
    } catch (e) {
      console.error('Failed to load memories:', e);
      setMemories([]);
    } finally {
      setLoading(false);
    }
  };

  const handleDecision = async (decision, memoryType, memoryId) => {
    try {
      await api.applyMemoryDecision(decision, memoryType, memoryId);
      loadMemories(activeTier);
      loadStats();
    } catch (e) {
      console.error('Failed to apply decision:', e);
    }
  };

  const handleDelete = async (memoryType, memoryId) => {
    if (!confirm('Permanently delete this memory entry?')) return;
    try {
      await api.deleteMemory(memoryType, memoryId);
      loadMemories(activeTier);
      loadStats();
    } catch (e) {
      console.error('Failed to delete memory:', e);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="memory-overlay">
      <div className="memory-panel">
        <div className="memory-panel-header">
          <h2>Council Memory Management</h2>
          <p className="memory-panel-subtitle">
            Semantic &middot; Episodic &middot; Procedural
          </p>
          <button className="memory-close" onClick={onClose} aria-label="Close">&times;</button>
        </div>

        {/* Stats bar */}
        {stats && (
          <div className="memory-stats-bar">
            {Object.entries(TIER_META).map(([tier, meta]) => (
              <div
                key={tier}
                className={`memory-stat-chip ${activeTier === tier ? 'active' : ''}`}
                onClick={() => setActiveTier(tier)}
              >
                <span className="stat-icon">{meta.icon}</span>
                <span className="stat-label">{meta.label}</span>
                <span className="stat-count">{stats[tier]?.active ?? 0}</span>
                {(stats[tier]?.unlearned ?? 0) > 0 && (
                  <span className="stat-unlearned">-{stats[tier].unlearned}</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Controls */}
        <div className="memory-controls">
          <label className="memory-toggle-label">
            <input
              type="checkbox"
              checked={showUnlearned}
              onChange={(e) => setShowUnlearned(e.target.checked)}
            />
            Show unlearned
          </label>
          <span className="memory-tier-desc">
            {TIER_META[activeTier]?.desc}
          </span>
        </div>

        {/* Memory list */}
        <div className="memory-list">
          {loading ? (
            <div className="memory-loading">
              <div className="spinner"></div>
              <span>Loading memories...</span>
            </div>
          ) : memories.length === 0 ? (
            <div className="memory-empty">
              No {TIER_META[activeTier]?.label.toLowerCase()} memories yet.
              Council decisions will appear here after deliberations.
            </div>
          ) : (
            memories.map((m) => (
              <MemoryCard
                key={m.id}
                memory={m}
                tier={activeTier}
                expanded={expandedId === m.id}
                onToggle={() => setExpandedId(expandedId === m.id ? null : m.id)}
                onLearn={() => handleDecision('learn', activeTier, m.id)}
                onUnlearn={() => handleDecision('unlearn', activeTier, m.id)}
                onDelete={() => handleDelete(activeTier, m.id)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}


function MemoryCard({ memory, tier, expanded, onToggle, onLearn, onUnlearn, onDelete }) {
  const isUnlearned = memory.status === 'unlearned';
  const confidence = memory.confidence ?? memory.grounding_score ?? 0;
  const confPct = Math.round(confidence * 100);
  const confColor = confPct >= 80 ? 'var(--success)' : confPct >= 60 ? 'var(--warning)' : 'var(--error)';

  return (
    <div className={`memory-card ${isUnlearned ? 'unlearned' : ''}`}>
      <div className="memory-card-header" onClick={onToggle}>
        <div className="memory-card-status">
          {isUnlearned ? '🚫' : memory.user_verdict === 'learn' ? '✅' : '⏳'}
        </div>
        <div className="memory-card-title">
          {tier === 'semantic' && memory.topic}
          {tier === 'episodic' && (memory.query || '').slice(0, 80)}
          {tier === 'procedural' && memory.task_type}
        </div>
        <div className="memory-card-conf" style={{ color: confColor }}>
          {confPct}%
        </div>
        <button className="memory-card-chevron" aria-label="Toggle details">
          {expanded ? '▲' : '▼'}
        </button>
      </div>

      {expanded && (
        <div className="memory-card-body">
          {/* Semantic details */}
          {tier === 'semantic' && (
            <>
              <div className="memory-field">
                <strong>Facts:</strong>
                <ul>
                  {(memory.facts || []).map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              </div>
              <div className="memory-field">
                <strong>Tags:</strong> {(memory.tags || []).join(', ') || 'none'}
              </div>
            </>
          )}

          {/* Episodic details */}
          {tier === 'episodic' && (
            <>
              <div className="memory-field">
                <strong>Query:</strong> {memory.query}
              </div>
              <div className="memory-field">
                <strong>Chairman:</strong> {memory.chairman_model}
              </div>
              <div className="memory-field">
                <strong>Decision preview:</strong>{' '}
                {(memory.chairman_response_preview || '').slice(0, 300)}...
              </div>
              {memory.aggregate_rankings && (
                <div className="memory-field">
                  <strong>Rankings:</strong>{' '}
                  {memory.aggregate_rankings.map(
                    (r, i) => `#${i + 1} ${(r.model || '').split('/')[1] || r.model}`
                  ).join(' → ')}
                </div>
              )}
            </>
          )}

          {/* Procedural details */}
          {tier === 'procedural' && (
            <>
              <div className="memory-field">
                <strong>Procedure:</strong> {memory.procedure}
              </div>
              {memory.steps && memory.steps.length > 0 && (
                <div className="memory-field">
                  <strong>Steps:</strong>
                  <ol>
                    {memory.steps.map((s, i) => <li key={i}>{s}</li>)}
                  </ol>
                </div>
              )}
              <div className="memory-field">
                <strong>Reinforced:</strong> {memory.reinforcement_count || 1}×
              </div>
            </>
          )}

          <div className="memory-meta-row">
            <span>Created: {new Date(memory.created_at).toLocaleDateString()}</span>
            {memory.updated_at && (
              <span>Updated: {new Date(memory.updated_at).toLocaleDateString()}</span>
            )}
          </div>

          {/* Learn / Unlearn actions */}
          <div className="memory-actions">
            {isUnlearned ? (
              <button className="mem-btn learn" onClick={onLearn}>
                ↩ Re-learn
              </button>
            ) : (
              <button className="mem-btn unlearn" onClick={onUnlearn}>
                🚫 Unlearn
              </button>
            )}
            {!isUnlearned && memory.user_verdict !== 'learn' && (
              <button className="mem-btn learn" onClick={onLearn}>
                ✅ Confirm Learn
              </button>
            )}
            <button className="mem-btn delete" onClick={onDelete}>
              🗑 Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
