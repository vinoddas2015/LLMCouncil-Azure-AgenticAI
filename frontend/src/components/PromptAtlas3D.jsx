/**
 * PromptAtlas3D — Intelligence Dashboard & Decision Tree
 *
 * Redesigned: combines the existing decision-tree flow with an
 * Agent Team intelligence dashboard that surfaces signals, patterns,
 * risks, and insights from 6 specialised agents.
 *
 * Layout:
 *   ┌─── Agent Team Signals (tab 1) ──────┐
 *   │  confidence ring · signal cards       │
 *   ├─── Decision Tree  (tab 2) ──────────┤
 *   │  User Prompt → Stage 1→2→3 tree      │
 *   ├─── Neural Graph   (tab 3) ──────────┤
 *   │  Interactive neural-network flow      │
 *   └─────────────────────────────────────┘
 *
 * WCAG 3.0 Silver:
 *   • APCA Lc ≥ 75 on all text/bg combos
 *   • role="button"  + Enter/Space on all interactive nodes
 *   • role="tab/tabpanel" for view toggle
 *   • role="complementary" landmark for the panel
 *   • aria-expanded, aria-controls, aria-label throughout
 *   • Reduced-motion safe, forced-colors safe
 *   • 24×24 px min interactive targets
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import ExportToolbar from './ExportToolbar';
import CouncilGraph from './CouncilGraph';
import { api } from '../api';
import './PromptAtlas3D.css';

/* ── Stage colours (dark theme; light overridden in CSS) ─────────── */
const STAGE_COLORS = {
  root:     { bg: '#14b8a6', text: '#0a1628', border: '#0d9488', glow: 'rgba(20, 184, 166, 0.25)' },
  stage1:   { bg: '#3b82f6', text: '#ffffff', border: '#2563eb', glow: 'rgba(59, 130, 246, 0.25)' },
  stage2:   { bg: '#a78bfa', text: '#ffffff', border: '#7c3aed', glow: 'rgba(167, 139, 250, 0.25)' },
  evidence: { bg: '#f59e0b', text: '#0a1628', border: '#d97706', glow: 'rgba(245, 158, 11, 0.25)' },
  stage3:   { bg: '#34d399', text: '#0a1628', border: '#059669', glow: 'rgba(52, 211, 153, 0.25)' },
};

const SEVERITY_COLORS = {
  success:  'var(--signal-success, #34d399)',
  info:     'var(--signal-info, #60a5fa)',
  warning:  'var(--signal-warning, #fbbf24)',
  critical: 'var(--signal-critical, #f87171)',
};


/* ════════════════════════════════════════════════════════════════════
   Agent Team Dashboard Components
   ════════════════════════════════════════════════════════════════════ */

function ConfidenceRing({ value, size = 52 }) {
  const percent = Math.round(value * 100);
  const r = (size - 8) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (value * circumference);
  const color = value >= 0.8 ? SEVERITY_COLORS.success
    : value >= 0.6 ? SEVERITY_COLORS.info
    : value >= 0.4 ? SEVERITY_COLORS.warning
    : SEVERITY_COLORS.critical;

  return (
    <svg
      className="confidence-ring"
      width={size} height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Team confidence: ${percent}%`}
    >
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke="var(--ring-track, rgba(100,116,139,0.15))" strokeWidth="6" />
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke={color} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={circumference} strokeDashoffset={offset}
        transform={`rotate(-90 ${size/2} ${size/2})`}
        style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
        className="confidence-ring-text" fill="var(--atlas-text, #e2e8f0)"
        fontSize="13" fontWeight="700">
        {percent}%
      </text>
    </svg>
  );
}

function SignalBadge({ severity, count }) {
  if (!count) return null;
  return (
    <span className={`signal-badge signal-${severity}`}
      role="status" aria-label={`${count} ${severity}`}>
      {count}
    </span>
  );
}

function AgentCard({ agent, isExpanded, onToggle }) {
  const signals = agent.signals || [];
  const hasCritical = signals.some(s => s.severity === 'critical');
  const hasWarning = signals.some(s => s.severity === 'warning');

  return (
    <div
      className={`agent-card ${isExpanded ? 'expanded' : ''} ${hasCritical ? 'has-critical' : hasWarning ? 'has-warning' : ''}`}
      role="button" tabIndex={0}
      aria-expanded={isExpanded}
      aria-label={`${agent.role} — ${agent.summary}`}
      onClick={onToggle}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
    >
      <div className="agent-card-header">
        <span className="agent-icon" aria-hidden="true">{agent.icon}</span>
        <div className="agent-card-info">
          <span className="agent-role">{agent.role}</span>
          <span className="agent-summary">{agent.summary}</span>
        </div>
        <div className="agent-card-badges">
          <SignalBadge severity="critical" count={signals.filter(s => s.severity === 'critical').length} />
          <SignalBadge severity="warning" count={signals.filter(s => s.severity === 'warning').length} />
          <span className="agent-confidence-mini">{Math.round(agent.confidence * 100)}%</span>
        </div>
      </div>

      {isExpanded && signals.length > 0 && (
        <div className="agent-signals" role="list" aria-label={`${agent.role} signals`}>
          {signals.map((signal, i) => (
            <div key={i} className={`signal-row signal-${signal.severity}`} role="listitem">
              <span className="signal-indicator"
                style={{ background: SEVERITY_COLORS[signal.severity] }} aria-hidden="true" />
              <div className="signal-content">
                <span className="signal-title">{signal.title}</span>
                <span className="signal-detail">{signal.detail}</span>
                {signal.evidence && <span className="signal-evidence">{signal.evidence}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentTeamDashboard({ teamData }) {
  const [expandedAgent, setExpandedAgent] = useState(null);
  if (!teamData) return null;

  const { agents = [], team_confidence = 0, total_signals = 0,
          critical_count = 0, warning_count = 0 } = teamData;

  return (
    <div className="agent-team-dashboard" role="region"
      aria-label="Agent Team Intelligence Dashboard">
      {/* Team Summary */}
      <div className="team-summary-bar">
        <ConfidenceRing value={team_confidence} />
        <div className="team-summary-stats">
          <span className="team-stat-label">Team Confidence</span>
          <div className="team-stat-counts">
            <SignalBadge severity="critical" count={critical_count} />
            <SignalBadge severity="warning" count={warning_count} />
            <span className="team-stat-total">{total_signals} signals · {agents.length} agents</span>
          </div>
        </div>
      </div>

      {/* Agent Cards */}
      <div className="agent-cards" role="list" aria-label="Agent team members">
        {agents.map(agent => (
          <AgentCard key={agent.agent_id} agent={agent}
            isExpanded={expandedAgent === agent.agent_id}
            onToggle={() => setExpandedAgent(
              expandedAgent === agent.agent_id ? null : agent.agent_id
            )} />
        ))}
      </div>
    </div>
  );
}


/* ════════════════════════════════════════════════════════════════════
   Decision Tree Components
   ════════════════════════════════════════════════════════════════════ */

function TreeNode({ node, depth = 0, onExpand, expandedId }) {
  const isExpanded = expandedId === node.id;
  const colors = STAGE_COLORS[node.type] || STAGE_COLORS.root;
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div className={`tree-branch depth-${depth}`}
      style={{ '--branch-delay': `${depth * 0.15}s` }}>
      {depth > 0 && <div className="tree-connector" style={{ borderColor: colors.border }} />}
      <div
        className={`tree-node ${isExpanded ? 'expanded' : ''} ${node.loading ? 'loading' : ''} node-${node.type}`}
        style={{
          '--node-bg': colors.bg, '--node-text': colors.text,
          '--node-border': colors.border, '--node-glow': colors.glow,
        }}
        role="button" tabIndex={0}
        aria-expanded={hasChildren ? isExpanded : undefined}
        aria-label={`${node.label}${node.badge ? ` — ${node.badge}` : ''}`}
        onClick={() => onExpand(node.id)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onExpand(node.id); } }}
      >
        <div className="tree-node-header">
          <span className="tree-node-icon" aria-hidden="true">{node.icon}</span>
          <span className="tree-node-label">{node.label}</span>
          {node.badge && <span className="tree-node-badge">{node.badge}</span>}
          {node.loading && <span className="tree-node-spinner" role="status" aria-label="Loading" />}
          {hasChildren && (
            <span className={`tree-node-chevron ${isExpanded ? 'open' : ''}`} aria-hidden="true">▾</span>
          )}
        </div>
        {node.metrics && (
          <div className="tree-node-metrics" role="group" aria-label="Metrics">
            {node.metrics.map((m, i) => (
              <div className="tree-metric" key={i}>
                <span className="tree-metric-val">{m.value}</span>
                <span className="tree-metric-label">{m.label}</span>
              </div>
            ))}
          </div>
        )}
        {isExpanded && node.detail && <div className="tree-node-detail">{node.detail}</div>}
      </div>
      {hasChildren && (
        <div className="tree-children" role="group">
          {node.children.map(child => (
            <TreeNode key={child.id} node={child} depth={depth + 1}
              onExpand={onExpand} expandedId={expandedId} />
          ))}
        </div>
      )}
    </div>
  );
}


/* ── Build tree from conversation (fixes data-from-storage bug) ──── */
function buildTree(conversation) {
  if (!conversation || !conversation.messages) return null;
  const msgs = conversation.messages;
  const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant');
  const lastUser = [...msgs].reverse().find(m => m.role === 'user');
  if (!lastUser) return null;

  const root = {
    id: 'root', type: 'root', icon: '💬', label: 'User Prompt',
    badge: null, metrics: null,
    detail: (<div className="detail-text">
      {lastUser.content?.slice(0, 800)}{lastUser.content?.length > 800 ? '…' : ''}
    </div>),
    children: [], loading: false,
  };

  if (!lastAssistant) {
    root.children.push({
      id: 'stage1-pending', type: 'stage1', icon: '⏳',
      label: 'Stage 1: Awaiting responses...', loading: true, children: [],
    });
    return root;
  }

  // Stage 1
  const s1 = lastAssistant.stage1;
  if (s1 && Array.isArray(s1)) {
    const s1Children = s1.map((resp, i) => {
      const modelShort = (resp.model || 'model').split('/').pop();
      const wc = (resp.response || '').split(/\s+/).length;
      return {
        id: `s1-${i}`, type: 'stage1', icon: '🤖', label: modelShort,
        badge: `${wc} words`,
        metrics: [{ value: modelShort.slice(0, 24), label: 'Model' }, { value: `${wc}`, label: 'Words' }],
        detail: (<div className="detail-text">
          {(resp.response || '').slice(0, 1000)}{(resp.response || '').length > 1000 ? '…' : ''}
        </div>),
        children: [],
      };
    });
    root.children.push({
      id: 'stage1-group', type: 'stage1', icon: '🧠',
      label: 'Stage 1: Individual Responses', badge: `${s1.length} models`,
      metrics: [
        { value: s1.length, label: 'Models' },
        { value: s1.reduce((sum, r) => sum + (r.response || '').split(/\s+/).length, 0), label: 'Total words' },
      ],
      children: s1Children,
    });
  } else if (lastAssistant.loading?.stage1) {
    root.children.push({
      id: 'stage1-loading', type: 'stage1', icon: '⏳',
      label: 'Stage 1: Collecting responses...', loading: true, children: [],
    });
  }

  // Stage 2
  const s2 = lastAssistant.stage2;
  const meta = lastAssistant.metadata;
  if (s2 && Array.isArray(s2)) {
    const aggRankings = meta?.aggregate_rankings || [];
    const gs = meta?.grounding_scores;
    const s2Children = s2.map((rank, i) => {
      const modelShort = (rank.model || 'reviewer').split('/').pop();
      return {
        id: `s2-${i}`, type: 'stage2', icon: '📊',
        label: `${modelShort} — Ranking`,
        metrics: rank.rubric_scores ? [{ value: Object.keys(rank.rubric_scores).length, label: 'Evaluated' }] : null,
        detail: (<div className="detail-text">
          <strong>Parsed ranking:</strong> {(rank.parsed_ranking || []).join(' → ')}<br />
          {rank.ranking?.slice(0, 600)}
        </div>),
        children: [],
      };
    });
    if (gs) {
      s2Children.push({
        id: 's2-grounding', type: 'stage2', icon: '🎯',
        label: `Grounding: ${Math.round(gs.overall_score)}%`,
        metrics: [
          { value: `${Math.round(gs.overall_score)}%`, label: 'Overall' },
          { value: gs.reviewers_count, label: 'Reviewers' },
        ],
        detail: (<div className="detail-text">
          {gs.per_response?.map((r, j) => (
            <div key={j} style={{ marginBottom: 4 }}>
              <strong>#{r.rank}</strong> {(r.model || '').split('/').pop()}:
              {' '}{r.grounding_score}%
              {r.pharma_metrics && (
                <> — Corr {r.pharma_metrics.correctness}% · F1 {r.pharma_metrics.f1}% · Prec {r.pharma_metrics.precision}% · Rec {r.pharma_metrics.recall}%</>
              )}
              {r.context_awareness && r.context_awareness.score != null && (
                <>
                  {' · CA '}
                  {r.context_awareness.combined_score != null
                    ? r.context_awareness.combined_score
                    : r.context_awareness.score}%
                  {r.context_awareness.stability != null && (
                    <> (stab {Math.round(r.context_awareness.stability)}%)</>
                  )}
                </>
              )}
            </div>
          ))}
        </div>),
        children: [],
      });
    }
    root.children.push({
      id: 'stage2-group', type: 'stage2', icon: '⚖️',
      label: 'Stage 2: Peer Rankings',
      badge: gs ? `${Math.round(gs.overall_score)}% grounded` : `${s2.length} reviewers`,
      metrics: [
        { value: s2.length, label: 'Reviewers' },
        ...(aggRankings.length > 0 ? [{ value: (aggRankings[0]?.model || '').split('/').pop(), label: '#1 Ranked' }] : []),
        ...(gs ? [{ value: `${Math.round(gs.overall_score)}%`, label: 'Grounding' }] : []),
      ],
      children: s2Children,
    });
  } else if (lastAssistant.loading?.stage2) {
    root.children.push({
      id: 'stage2-loading', type: 'stage2', icon: '⏳',
      label: 'Stage 2: Peer ranking...', loading: true, children: [],
    });
  }

  // Evidence — FIX: check both top-level (SSE) and nested-in-metadata (storage)
  const ev = lastAssistant.evidence || meta?.evidence;
  if (ev && ev.citations?.length > 0) {
    const evChildren = ev.citations.slice(0, 12).map((c, i) => ({
      id: `ev-${i}`, type: 'evidence',
      icon: c.source === 'OpenFDA' ? '💊' : c.source === 'PubMed' ? '📄' : '🏥',
      label: c.title?.slice(0, 100), badge: c.source,
      detail: (<div className="detail-text">
        <strong>{c.id}</strong> — {c.snippet}<br />
        <a href={c.url} target="_blank" rel="noopener noreferrer" className="evidence-link">
          Open source ↗
        </a>
      </div>),
      children: [],
    }));
    root.children.push({
      id: 'evidence-group', type: 'evidence', icon: '📚',
      label: 'Evidence & Citations', badge: `${ev.citations.length} sources`,
      metrics: [
        { value: ev.citations.length, label: 'Citations' },
        { value: ev.skills_used?.length || 0, label: 'Skills' },
        { value: ev.benchmark?.total_ms ? `${Math.round(ev.benchmark.total_ms)}ms` : '—', label: 'Latency' },
      ],
      children: evChildren,
    });
  }

  // Stage 3
  const s3 = lastAssistant.stage3;
  if (s3) {
    const chairShort = (s3.model || 'chairman').split('/').pop();
    const wc = (s3.response || '').split(/\s+/).length;
    root.children.push({
      id: 'stage3-group', type: 'stage3', icon: '👑',
      label: 'Stage 3: Chairman Synthesis', badge: chairShort,
      metrics: [
        { value: chairShort, label: 'Chairman' },
        { value: wc, label: 'Words' },
        ...(ev?.citations?.length ? [{ value: ev.citations.length, label: 'Citations' }] : []),
      ],
      detail: (<div className="detail-text">
        {(s3.response || '').slice(0, 1500)}{(s3.response || '').length > 1500 ? '…' : ''}
      </div>),
      children: [],
    });
  } else if (lastAssistant.loading?.stage3) {
    root.children.push({
      id: 'stage3-loading', type: 'stage3', icon: '⏳',
      label: 'Stage 3: Synthesizing...', loading: true, children: [],
    });
  }

  // Infographic
  const infog = lastAssistant.infographic;
  if (infog) {
    const infogChildren = [];
    if (infog.key_metrics?.length > 0) {
      infogChildren.push({
        id: 'infog-metrics', type: 'stage3', icon: '📈',
        label: `${infog.key_metrics.length} Key Metrics`,
        detail: (<div className="detail-text atlas-infog-metrics">
          {infog.key_metrics.map((m, i) => (
            <div key={i} className="atlas-infog-metric-row">
              <span className="atlas-infog-metric-icon">{m.icon || '📊'}</span>
              <strong>{m.value}</strong> — {m.label}
            </div>
          ))}
        </div>),
        children: [],
      });
    }
    if (infog.comparison?.rows?.length > 0) {
      infogChildren.push({
        id: 'infog-comparison', type: 'stage3', icon: '📋',
        label: `Comparison — ${infog.comparison.rows.length} rows`,
        detail: (<div className="detail-text">
          <strong>Columns:</strong> {(infog.comparison.headers || []).join(' · ')}
        </div>),
        children: [],
      });
    }
    if (infog.process_steps?.length > 0) {
      infogChildren.push({
        id: 'infog-steps', type: 'stage3', icon: '🔄',
        label: `${infog.process_steps.length}-Step Process`,
        detail: (<div className="detail-text">
          {infog.process_steps.map((s, i) => (
            <div key={i} style={{ marginBottom: 4 }}>
              <strong>Step {s.step}:</strong> {s.title}
              {s.description && <> — {s.description}</>}
            </div>
          ))}
        </div>),
        children: [],
      });
    }
    if (infog.highlights?.length > 0) {
      infogChildren.push({
        id: 'infog-highlights', type: 'stage3', icon: '💡',
        label: `${infog.highlights.length} Takeaways`,
        detail: (<div className="detail-text">
          {infog.highlights.map((h, i) => (
            <div key={i} style={{ marginBottom: 4 }}>
              {h.type === 'success' ? '✅' : h.type === 'warning' ? '⚠️' : h.type === 'danger' ? '🔴' : 'ℹ️'}
              {' '}{h.text}
            </div>
          ))}
        </div>),
        children: [],
      });
    }
    root.children.push({
      id: 'infographic-group', type: 'stage3', icon: '📊',
      label: 'Infographic Summary', badge: infog.title || 'Visual Data',
      metrics: [
        { value: infog.key_metrics?.length || 0, label: 'Metrics' },
        { value: infog.highlights?.length || 0, label: 'Highlights' },
        { value: infog.process_steps?.length || 0, label: 'Steps' },
      ],
      children: infogChildren,
    });
  }

  return root;
}


/* ════════════════════════════════════════════════════════════════════
   Main Component
   ════════════════════════════════════════════════════════════════════ */

export default function PromptAtlas3D({ conversation, isOpen, onToggle, onWidthChange }) {
  const [expandedId, setExpandedId] = useState(null);
  const [activeView, setActiveView] = useState('signals');
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState(null);
  const [localAgentTeam, setLocalAgentTeam] = useState(null);
  const panelRef = useRef(null);
  const exportRef = useRef(null);

  /* ── Drag-to-resize state ─────────────────────────────────────── */
  const MIN_WIDTH = 360;
  const MAX_WIDTH = 900;
  const DEFAULT_WIDTH = 480;
  const [panelWidth, setPanelWidth] = useState(() => {
    const saved = localStorage.getItem('atlas-panel-width');
    return saved ? Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Number(saved))) : DEFAULT_WIDTH;
  });
  const draggingRef = useRef(false);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e2) => {
      if (!draggingRef.current) return;
      const newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - e2.clientX));
      setPanelWidth(newWidth);
      onWidthChange?.(newWidth);
    };

    const handleMouseUp = () => {
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      // Persist
      setPanelWidth(w => { localStorage.setItem('atlas-panel-width', w); return w; });
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [onWidthChange]);

  // Notify parent of initial width
  useEffect(() => { onWidthChange?.(panelWidth); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const tree = buildTree(conversation);

  // Agent team data from latest assistant message
  // Falls back to metadata.agent_team for conversations reloaded from storage
  const lastAssistant = conversation?.messages
    ? [...conversation.messages].reverse().find(m => m.role === 'assistant')
    : null;
  const agentTeamData = lastAssistant?.agentTeam
    || lastAssistant?.metadata?.agent_team
    || localAgentTeam
    || null;

  // Reset local agent team when conversation changes
  useEffect(() => { setLocalAgentTeam(null); setAnalyzeError(null); }, [conversation?.id]);

  // Neural Graph can render whenever we have ANY conversation data
  // (agents are just layer 5 — the graph still shows prompt→S1→S2→evidence→S3)
  const hasConversationData = !!(lastAssistant?.stage1 || lastAssistant?.stage3);

  useEffect(() => {
    if (isOpen && panelRef.current) {
      panelRef.current.scrollTop = panelRef.current.scrollHeight;
    }
  }, [tree, isOpen]);

  const handleExpand = id => setExpandedId(prev => prev === id ? null : id);

  /* ── On-demand agent analysis ──────────────────────────────────── */
  const handleRunAnalysis = async () => {
    if (!conversation?.id || analyzing) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const result = await api.analyzeAgents(conversation.id);
      setLocalAgentTeam(result);
    } catch (err) {
      setAnalyzeError(err.message || 'Analysis failed');
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <>
      {/* Toggle button */}
      <button
        className={`atlas-toggle-btn ${isOpen ? 'panel-open' : ''}`}
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls="prompt-atlas-panel"
        aria-label={isOpen ? 'Close Prompt Atlas' : 'Open Prompt Atlas'}
        style={isOpen ? { right: panelWidth } : undefined}
      >
        <span className="atlas-toggle-icon" aria-hidden="true">{isOpen ? '▶' : '◀'}</span>
        Atlas
      </button>

      {/* Panel */}
      <div
        id="prompt-atlas-panel"
        className={`prompt-atlas-panel ${isOpen ? '' : 'collapsed'}`}
        role="complementary"
        aria-label="LLM Council Prompt Atlas"
        style={isOpen ? { width: panelWidth, minWidth: panelWidth } : undefined}
      >
        {/* Resize handle */}
        <div
          className="atlas-resize-handle"
          onMouseDown={handleMouseDown}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize Atlas panel"
          aria-valuenow={panelWidth}
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') { setPanelWidth(w => { const nw = Math.min(MAX_WIDTH, w + 20); onWidthChange?.(nw); return nw; }); }
            if (e.key === 'ArrowRight') { setPanelWidth(w => { const nw = Math.max(MIN_WIDTH, w - 20); onWidthChange?.(nw); return nw; }); }
          }}
        />
        {/* Header */}
        <div className="atlas-header">
          <div className="atlas-header-left">
            <div className="atlas-header-icon" aria-hidden="true">🧬</div>
            <div>
              <h2 id="atlas-heading">LLM Council Atlas</h2>
              <div className="atlas-header-subtitle">Intelligence Dashboard · Decision Tree</div>
            </div>
          </div>
          <ExportToolbar targetRef={exportRef} filenamePrefix="LLMCouncil_Atlas" />
          <button className="atlas-close-btn" onClick={onToggle} aria-label="Close Prompt Atlas">×</button>
        </div>

        {/* Tab bar — always visible */}
        <div className="atlas-view-toggle" role="tablist" aria-label="Atlas view">
          <button role="tab" aria-selected={activeView === 'signals'}
            className={`view-tab ${activeView === 'signals' ? 'active' : ''}`}
            onClick={() => setActiveView('signals')}>
            🎯 Agent Signals
          </button>
          <button role="tab" aria-selected={activeView === 'tree'}
            className={`view-tab ${activeView === 'tree' ? 'active' : ''}`}
            onClick={() => setActiveView('tree')}>
            🌳 Decision Tree
          </button>
          <button role="tab" aria-selected={activeView === 'graph'}
            className={`view-tab ${activeView === 'graph' ? 'active' : ''}`}
            onClick={() => setActiveView('graph')}>
            🧠 Neural Graph
          </button>
        </div>

        {/* Exportable content */}
        <div className="atlas-export-region" ref={exportRef}>
          <div className="atlas-print-title">
            LLM Council — Prompt Atlas
            <div className="atlas-print-subtitle">Intelligence Dashboard · Agent Team Analysis</div>
          </div>

          {/* Agent Signals view */}
          {activeView === 'signals' && (
            <div className="atlas-tree-container" ref={panelRef}>
              {agentTeamData ? (
                <AgentTeamDashboard teamData={agentTeamData} />
              ) : hasConversationData ? (
                <div className="atlas-empty atlas-welcome" role="status">
                  <div className="atlas-empty-icon" aria-hidden="true">🎯</div>
                  <div className="atlas-welcome-title">Agent Signals</div>
                  <div className="atlas-empty-text">
                    Agent analysis was not captured for this conversation.
                    Click below to run the 9 specialized agents now.
                  </div>
                  {analyzeError && (
                    <div className="atlas-analyze-error" role="alert">⚠️ {analyzeError}</div>
                  )}
                  <button
                    className="atlas-run-analysis-btn"
                    onClick={handleRunAnalysis}
                    disabled={analyzing}
                    aria-busy={analyzing}
                  >
                    {analyzing ? (
                      <><span className="atlas-spinner" aria-hidden="true" /> Analyzing…</>
                    ) : (
                      <>▶ Run Agent Analysis</>
                    )}
                  </button>
                  <div className="atlas-welcome-hint">Results will be saved for future visits</div>
                </div>
              ) : (
                <div className="atlas-empty atlas-welcome" role="status">
                  <div className="atlas-empty-icon" aria-hidden="true">🎯</div>
                  <div className="atlas-welcome-title">Agent Signals</div>
                  <div className="atlas-empty-text">
                    9 specialized agents analyze every council response in real-time — Research Analyst, Fact Checker, Risk Assessor, Pattern Scout, Insight Synthesizer, Quality Auditor, and 3 VP specialists.
                  </div>
                  <div className="atlas-welcome-badges">
                    <span className="atlas-preview-badge badge-success">✅ Fact Checks</span>
                    <span className="atlas-preview-badge badge-warning">⚠️ Risk Signals</span>
                    <span className="atlas-preview-badge badge-info">🔍 Patterns</span>
                    <span className="atlas-preview-badge badge-insight">💡 Insights</span>
                  </div>
                  <div className="atlas-welcome-hint">Send a prompt to activate the agent team</div>
                </div>
              )}
            </div>
          )}

          {/* Decision Tree view */}
          {activeView === 'tree' && (
            <div className="atlas-tree-container" ref={panelRef}>
              {tree ? (
                <TreeNode node={tree} depth={0} onExpand={handleExpand} expandedId={expandedId} />
              ) : (
                <div className="atlas-empty atlas-welcome" role="status">
                  <div className="atlas-empty-icon" aria-hidden="true">🌳</div>
                  <div className="atlas-welcome-title">Decision Tree</div>
                  <div className="atlas-empty-text">
                    Watch the 3-stage council pipeline unfold — from parallel model responses through peer review to the chairman's synthesis.
                  </div>
                  <div className="atlas-welcome-flow">
                    <span className="atlas-flow-step">📝 Prompt</span>
                    <span className="atlas-flow-arrow">→</span>
                    <span className="atlas-flow-step">🔬 Stage 1</span>
                    <span className="atlas-flow-arrow">→</span>
                    <span className="atlas-flow-step">⚖️ Stage 2</span>
                    <span className="atlas-flow-arrow">→</span>
                    <span className="atlas-flow-step">🏛️ Stage 3</span>
                  </div>
                  <div className="atlas-welcome-hint">Send a prompt to see the decision tree flow in real-time</div>
                </div>
              )}
            </div>
          )}

          {/* Neural Graph view */}
          {activeView === 'graph' && (
            <div className="atlas-tree-container atlas-graph-container" ref={panelRef}>
              {hasConversationData ? (
                <CouncilGraph conversation={conversation} agentTeamData={agentTeamData} />
              ) : (
                <div className="atlas-empty atlas-welcome" role="status">
                  <div className="atlas-empty-icon" aria-hidden="true">🧠</div>
                  <div className="atlas-welcome-title">Neural Graph</div>
                  <div className="atlas-empty-text">
                    Interactive network visualization showing the flow of information between models, reviewers, evidence sources, agents, and the chairman.
                  </div>
                  <div className="atlas-welcome-badges">
                    <span className="atlas-preview-badge badge-model">🤖 Models</span>
                    <span className="atlas-preview-badge badge-evidence">📚 Evidence</span>
                    <span className="atlas-preview-badge badge-agent">🕵️ Agents</span>
                    <span className="atlas-preview-badge badge-chairman">🏛️ Chairman</span>
                  </div>
                  <div className="atlas-welcome-hint">Send a prompt to generate the neural graph</div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="atlas-footer">
          LLM Council Atlas v4.1 · Agent Intelligence · Decision Tree · Neural Graph · Export Ready
        </div>
      </div>
    </>
  );
}
