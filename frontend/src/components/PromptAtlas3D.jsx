/**
 * PromptAtlas3D — Decision-Tree Flow Visualization
 *
 * Redesigned from 3D scatter → flowing decision tree / family tree
 * that animates in real-time as the user prompt executes through
 * the three council stages.
 *
 * Nodes appear top-down:
 *   User Prompt (root)
 *     └─ Stage 1: Individual model responses (leaf nodes)
 *         └─ Stage 2: Peer rankings + grounding (collapsible)
 *             └─ Evidence: OpenFDA / ClinicalTrials / PubMed
 *                 └─ Stage 3: Chairman synthesis (final node)
 *
 * Each node is clickable → expands a dropdown detail card
 * with stats, metrics, and content snippets.
 */

import { useState, useEffect, useRef } from 'react';
import ExportToolbar from './ExportToolbar';
import './PromptAtlas3D.css';

/* ── Stage colours ──────────────────────────────────────────────── */
const STAGE_COLORS = {
  root:     { bg: '#14b8a6', text: '#0a1628', border: '#0d9488', glow: 'rgba(20, 184, 166, 0.25)' },
  stage1:   { bg: '#3b82f6', text: '#ffffff', border: '#2563eb', glow: 'rgba(59, 130, 246, 0.25)' },
  stage2:   { bg: '#a78bfa', text: '#ffffff', border: '#7c3aed', glow: 'rgba(167, 139, 250, 0.25)' },
  evidence: { bg: '#f59e0b', text: '#0a1628', border: '#d97706', glow: 'rgba(245, 158, 11, 0.25)' },
  stage3:   { bg: '#34d399', text: '#0a1628', border: '#059669', glow: 'rgba(52, 211, 153, 0.25)' },
};

/* ── Tree Node Component ────────────────────────────────────────── */
function TreeNode({ node, depth = 0, onExpand, expandedId }) {
  const isExpanded = expandedId === node.id;
  const colors = STAGE_COLORS[node.type] || STAGE_COLORS.root;
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div className={`tree-branch depth-${depth}`} style={{ '--branch-delay': `${depth * 0.15}s` }}>
      {/* Connector line from parent */}
      {depth > 0 && <div className="tree-connector" style={{ borderColor: colors.border }} />}

      {/* Node box */}
      <div
        className={`tree-node ${isExpanded ? 'expanded' : ''} ${node.loading ? 'loading' : ''} node-${node.type}`}
        style={{
          '--node-bg': colors.bg,
          '--node-text': colors.text,
          '--node-border': colors.border,
          '--node-glow': colors.glow,
        }}
        onClick={() => onExpand(node.id)}
      >
        <div className="tree-node-header">
          <span className="tree-node-icon">{node.icon}</span>
          <span className="tree-node-label">{node.label}</span>
          {node.badge && <span className="tree-node-badge">{node.badge}</span>}
          {node.loading && <span className="tree-node-spinner" />}
          {hasChildren && (
            <span className={`tree-node-chevron ${isExpanded ? 'open' : ''}`}>▾</span>
          )}
        </div>

        {/* Metrics row (always visible if present) */}
        {node.metrics && (
          <div className="tree-node-metrics">
            {node.metrics.map((m, i) => (
              <div className="tree-metric" key={i}>
                <span className="tree-metric-val">{m.value}</span>
                <span className="tree-metric-label">{m.label}</span>
              </div>
            ))}
          </div>
        )}

        {/* Expandable detail dropdown */}
        {isExpanded && node.detail && (
          <div className="tree-node-detail">
            {node.detail}
          </div>
        )}
      </div>

      {/* Children */}
      {hasChildren && (
        <div className="tree-children">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              onExpand={onExpand}
              expandedId={expandedId}
            />
          ))}
        </div>
      )}
    </div>
  );
}


/* ── Build tree data from conversation ──────────────────────────── */
function buildTree(conversation) {
  if (!conversation || !conversation.messages) return null;

  // Find latest assistant message
  const msgs = conversation.messages;
  const lastAssistant = [...msgs].reverse().find((m) => m.role === 'assistant');
  const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
  if (!lastUser) return null;

  const root = {
    id: 'root',
    type: 'root',
    icon: '💬',
    label: 'User Prompt',
    badge: null,
    metrics: null,
    detail: (
      <div className="detail-text">
        {lastUser.content?.slice(0, 300)}{lastUser.content?.length > 300 ? '…' : ''}
      </div>
    ),
    children: [],
    loading: false,
  };

  if (!lastAssistant) {
    root.children.push({
      id: 'stage1-pending',
      type: 'stage1',
      icon: '⏳',
      label: 'Stage 1: Awaiting responses...',
      loading: true,
      children: [],
    });
    return root;
  }

  // ── Stage 1 nodes ─────────────────────────────────────────────
  const s1 = lastAssistant.stage1;
  if (s1 && Array.isArray(s1)) {
    const s1Children = s1.map((resp, i) => {
      const modelShort = (resp.model || 'model').split('/').pop();
      const wordCount = (resp.response || '').split(/\s+/).length;
      return {
        id: `s1-${i}`,
        type: 'stage1',
        icon: '🤖',
        label: modelShort,
        badge: `${wordCount} words`,
        metrics: [
          { value: modelShort.slice(0, 12), label: 'Model' },
          { value: `${wordCount}`, label: 'Words' },
        ],
        detail: (
          <div className="detail-text">
            {(resp.response || '').slice(0, 400)}{(resp.response || '').length > 400 ? '…' : ''}
          </div>
        ),
        children: [],
      };
    });

    root.children.push({
      id: 'stage1-group',
      type: 'stage1',
      icon: '🧠',
      label: 'Stage 1: Individual Responses',
      badge: `${s1.length} models`,
      metrics: [
        { value: s1.length, label: 'Models' },
        { value: s1.reduce((sum, r) => sum + (r.response || '').split(/\s+/).length, 0), label: 'Total words' },
      ],
      children: s1Children,
    });
  } else if (lastAssistant.loading?.stage1) {
    root.children.push({
      id: 'stage1-loading',
      type: 'stage1',
      icon: '⏳',
      label: 'Stage 1: Collecting responses...',
      loading: true,
      children: [],
    });
  }

  // ── Stage 2 nodes ─────────────────────────────────────────────
  const s2 = lastAssistant.stage2;
  const meta = lastAssistant.metadata;
  if (s2 && Array.isArray(s2)) {
    const aggRankings = meta?.aggregate_rankings || [];
    const gs = meta?.grounding_scores;

    const s2Children = s2.map((rank, i) => {
      const modelShort = (rank.model || 'reviewer').split('/').pop();
      return {
        id: `s2-${i}`,
        type: 'stage2',
        icon: '📊',
        label: `${modelShort} — Ranking`,
        metrics: rank.rubric_scores ? [
          { value: Object.keys(rank.rubric_scores).length, label: 'Evaluated' },
        ] : null,
        detail: (
          <div className="detail-text">
            <strong>Parsed ranking:</strong> {(rank.parsed_ranking || []).join(' → ')}<br />
            {rank.ranking?.slice(0, 300)}
          </div>
        ),
        children: [],
      };
    });

    // Grounding score child
    if (gs) {
      s2Children.push({
        id: 's2-grounding',
        type: 'stage2',
        icon: '🎯',
        label: `Grounding: ${Math.round(gs.overall_score)}%`,
        metrics: [
          { value: `${Math.round(gs.overall_score)}%`, label: 'Overall' },
          { value: gs.reviewers_count, label: 'Reviewers' },
        ],
        detail: (
          <div className="detail-text">
            {gs.per_response?.map((r, j) => (
              <div key={j} style={{ marginBottom: 4 }}>
                <strong>#{r.rank}</strong> {(r.model || '').split('/').pop()}:
                {' '}{r.grounding_score}%
                {r.pharma_metrics && (
                  <> — Correctness {r.pharma_metrics.correctness}% · Precision {r.pharma_metrics.precision}% · Recall {r.pharma_metrics.recall}%</>
                )}
              </div>
            ))}
          </div>
        ),
        children: [],
      });
    }

    root.children.push({
      id: 'stage2-group',
      type: 'stage2',
      icon: '⚖️',
      label: 'Stage 2: Peer Rankings',
      badge: gs ? `${Math.round(gs.overall_score)}% grounded` : `${s2.length} reviewers`,
      metrics: [
        { value: s2.length, label: 'Reviewers' },
        ...(aggRankings.length > 0
          ? [{ value: (aggRankings[0]?.model || '').split('/').pop(), label: '#1 Ranked' }]
          : []),
        ...(gs ? [{ value: `${Math.round(gs.overall_score)}%`, label: 'Grounding' }] : []),
      ],
      children: s2Children,
    });
  } else if (lastAssistant.loading?.stage2) {
    root.children.push({
      id: 'stage2-loading',
      type: 'stage2',
      icon: '⏳',
      label: 'Stage 2: Peer ranking...',
      loading: true,
      children: [],
    });
  }

  // ── Evidence node ─────────────────────────────────────────────
  const ev = lastAssistant.evidence;
  if (ev && ev.citations?.length > 0) {
    const evChildren = ev.citations.slice(0, 8).map((c, i) => ({
      id: `ev-${i}`,
      type: 'evidence',
      icon: c.source === 'OpenFDA' ? '💊' : c.source === 'PubMed' ? '📄' : '🏥',
      label: c.title?.slice(0, 60),
      badge: c.source,
      detail: (
        <div className="detail-text">
          <strong>{c.id}</strong> — {c.snippet}<br />
          <a href={c.url} target="_blank" rel="noopener noreferrer" className="evidence-link">
            Open source ↗
          </a>
        </div>
      ),
      children: [],
    }));

    root.children.push({
      id: 'evidence-group',
      type: 'evidence',
      icon: '📚',
      label: 'Evidence & Citations',
      badge: `${ev.citations.length} sources`,
      metrics: [
        { value: ev.citations.length, label: 'Citations' },
        { value: ev.skills_used?.length || 0, label: 'Skills' },
        { value: ev.benchmark?.total_ms ? `${Math.round(ev.benchmark.total_ms)}ms` : '—', label: 'Latency' },
      ],
      children: evChildren,
    });
  }

  // ── Stage 3 node ──────────────────────────────────────────────
  const s3 = lastAssistant.stage3;
  if (s3) {
    const chairShort = (s3.model || 'chairman').split('/').pop();
    const wordCount = (s3.response || '').split(/\s+/).length;
    root.children.push({
      id: 'stage3-group',
      type: 'stage3',
      icon: '👑',
      label: 'Stage 3: Chairman Synthesis',
      badge: chairShort,
      metrics: [
        { value: chairShort, label: 'Chairman' },
        { value: wordCount, label: 'Words' },
        ...(ev?.citations?.length ? [{ value: ev.citations.length, label: 'Citations' }] : []),
      ],
      detail: (
        <div className="detail-text">
          {(s3.response || '').slice(0, 500)}{(s3.response || '').length > 500 ? '…' : ''}
        </div>
      ),
      children: [],
    });
  } else if (lastAssistant.loading?.stage3) {
    root.children.push({
      id: 'stage3-loading',
      type: 'stage3',
      icon: '⏳',
      label: 'Stage 3: Synthesizing...',
      loading: true,
      children: [],
    });
  }

  // ── Infographic node ────────────────────────────────────────────
  const infog = lastAssistant.infographic;
  if (infog) {
    const infogChildren = [];

    // Key metrics as child nodes
    if (infog.key_metrics?.length > 0) {
      infogChildren.push({
        id: 'infog-metrics',
        type: 'stage3',
        icon: '📈',
        label: `${infog.key_metrics.length} Key Metrics`,
        detail: (
          <div className="detail-text atlas-infog-metrics">
            {infog.key_metrics.map((m, i) => (
              <div key={i} className="atlas-infog-metric-row">
                <span className="atlas-infog-metric-icon">{m.icon || '📊'}</span>
                <strong>{m.value}</strong> — {m.label}
              </div>
            ))}
          </div>
        ),
        children: [],
      });
    }

    // Comparison table summary
    if (infog.comparison?.rows?.length > 0) {
      infogChildren.push({
        id: 'infog-comparison',
        type: 'stage3',
        icon: '📋',
        label: `Comparison — ${infog.comparison.rows.length} rows`,
        detail: (
          <div className="detail-text">
            <strong>Columns:</strong> {(infog.comparison.headers || []).join(' · ')}
          </div>
        ),
        children: [],
      });
    }

    // Process steps
    if (infog.process_steps?.length > 0) {
      infogChildren.push({
        id: 'infog-steps',
        type: 'stage3',
        icon: '🔄',
        label: `${infog.process_steps.length}-Step Process`,
        detail: (
          <div className="detail-text">
            {infog.process_steps.map((s, i) => (
              <div key={i} style={{ marginBottom: 4 }}>
                <strong>Step {s.step}:</strong> {s.title}
                {s.description && <> — {s.description}</>}
              </div>
            ))}
          </div>
        ),
        children: [],
      });
    }

    // Highlights count
    if (infog.highlights?.length > 0) {
      infogChildren.push({
        id: 'infog-highlights',
        type: 'stage3',
        icon: '💡',
        label: `${infog.highlights.length} Takeaways`,
        detail: (
          <div className="detail-text">
            {infog.highlights.map((h, i) => (
              <div key={i} style={{ marginBottom: 4 }}>
                {h.type === 'success' ? '✅' : h.type === 'warning' ? '⚠️' : h.type === 'danger' ? '🔴' : 'ℹ️'}
                {' '}{h.text}
              </div>
            ))}
          </div>
        ),
        children: [],
      });
    }

    root.children.push({
      id: 'infographic-group',
      type: 'stage3',
      icon: '📊',
      label: 'Infographic Summary',
      badge: infog.title || 'Visual Data',
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

export default function PromptAtlas3D({ conversation, isOpen, onToggle }) {
  const [expandedId, setExpandedId] = useState(null);
  const panelRef = useRef(null);
  const exportRef = useRef(null);

  const tree = buildTree(conversation);

  // Auto-scroll panel to bottom when new nodes appear
  useEffect(() => {
    if (isOpen && panelRef.current) {
      panelRef.current.scrollTop = panelRef.current.scrollHeight;
    }
  }, [tree, isOpen]);

  const handleExpand = (id) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <>
      {/* Toggle button — always visible */}
      <button
        className={`atlas-toggle-btn ${isOpen ? 'panel-open' : ''}`}
        onClick={onToggle}
        title={isOpen ? 'Close Prompt Atlas' : 'Open Prompt Atlas'}
      >
        <span className="atlas-toggle-icon">{isOpen ? '▶' : '◀'}</span>
        Atlas
      </button>

      {/* Panel */}
      <div className={`prompt-atlas-panel ${isOpen ? '' : 'collapsed'}`}>
        {/* Header */}
        <div className="atlas-header">
          <div className="atlas-header-left">
            <div className="atlas-header-icon">🧬</div>
            <div>
              <h2>LLM Prompts Atlas</h2>
              <div className="atlas-header-subtitle">Decision Tree · Council Flow</div>
            </div>
          </div>
          <ExportToolbar targetRef={exportRef} filenamePrefix="LLMCouncil_Atlas" />
          <button className="atlas-close-btn" onClick={onToggle} title="Close">×</button>
        </div>

        {/* Decision Tree — exportable region */}
        <div className="atlas-export-region" ref={exportRef}>
          {/* Print-only title — visible only during A4 export */}
          <div className="atlas-print-title">
            LLM Council — Prompt Atlas
            <div className="atlas-print-subtitle">
              Decision Tree Flow · Council Pipeline Report
            </div>
          </div>
          <div className="atlas-tree-container" ref={panelRef}>
          {tree ? (
            <TreeNode
              node={tree}
              depth={0}
              onExpand={handleExpand}
              expandedId={expandedId}
            />
          ) : (
            <div className="atlas-empty">
              <div className="atlas-empty-icon">🌳</div>
              <div className="atlas-empty-text">
                Send a prompt to see the council decision tree flow in real-time.
              </div>
            </div>
          )}
        </div>
        </div>{/* end atlas-export-region */}

        {/* Footer */}
        <div className="atlas-footer">
          LLM Council Prompt Atlas v3.0 · Decision Tree Flow · Export Ready
        </div>
      </div>
    </>
  );
}
