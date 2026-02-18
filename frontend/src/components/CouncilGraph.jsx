/**
 * CouncilGraph — Neural Network-style Interactive Graph
 *
 * Visualises the LLM Council pipeline as a directed graph with:
 *   Layer 0: User Prompt (input neuron)
 *   Layer 1: Stage 1 — Individual model responses (parallel neurons)
 *   Layer 2: Stage 2 — Peer rankings + grounding (consolidating neurons)
 *   Layer 3: Evidence citations (branching layer)
 *   Layer 4: Stage 3 — Chairman synthesis (output neuron)
 *   Layer 5: Agent Team signals (downstream analytics layer)
 *
 * Features:
 *   • Drilldown: click any node to expand detail panel
 *   • Animated data-flow edges (pulsing gradient)
 *   • Signal severity colour-coding on edges & nodes
 *   • Node size scales with confidence/word-count
 *   • WCAG 3.0: keyboard-navigable, aria-labels, focus rings
 *
 * @xyflow/react provides the graph engine — we use custom node
 * components and animated edges for the neural-network aesthetic.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './CouncilGraph.css';


/* ════════════════════════════════════════════════════════════════════
   Custom Node Components
   ════════════════════════════════════════════════════════════════════ */

function InputNode({ data }) {
  return (
    <div className={`graph-node node-input ${data.active ? 'active' : ''}`}
      role="button" tabIndex={0} aria-label={data.ariaLabel}>
      <Handle type="source" position={Position.Bottom} />
      <div className="node-icon">{data.icon}</div>
      <div className="node-content">
        <div className="node-label">{data.label}</div>
        {data.sublabel && <div className="node-sublabel">{data.sublabel}</div>}
      </div>
    </div>
  );
}

function NeuronNode({ data }) {
  const sizeClass = data.size === 'lg' ? 'neuron-lg'
    : data.size === 'sm' ? 'neuron-sm' : 'neuron-md';

  return (
    <div
      className={`graph-node node-neuron ${sizeClass} ${data.severity || ''} ${data.active ? 'active' : ''}`}
      style={{ '--node-accent': data.accent || '#60a5fa' }}
      role="button" tabIndex={0} aria-label={data.ariaLabel}
    >
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <div className="neuron-glow" style={{ background: data.accent }} />
      <div className="node-icon">{data.icon}</div>
      <div className="node-content">
        <div className="node-label">{data.label}</div>
        {data.sublabel && <div className="node-sublabel">{data.sublabel}</div>}
        {data.metric && (
          <div className="node-metric" style={{ color: data.accent }}>
            {data.metric}
          </div>
        )}
      </div>
      {data.badge && <div className="node-badge" style={{ background: data.accent }}>{data.badge}</div>}
    </div>
  );
}

function OutputNode({ data }) {
  return (
    <div className={`graph-node node-output ${data.active ? 'active' : ''}`}
      role="button" tabIndex={0} aria-label={data.ariaLabel}>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      <div className="node-icon">{data.icon}</div>
      <div className="node-content">
        <div className="node-label">{data.label}</div>
        {data.sublabel && <div className="node-sublabel">{data.sublabel}</div>}
        {data.metric && <div className="node-metric node-metric-lg">{data.metric}</div>}
      </div>
    </div>
  );
}

function AgentNode({ data }) {
  return (
    <div
      className={`graph-node node-agent ${data.severity || ''} ${data.active ? 'active' : ''}`}
      style={{ '--node-accent': data.accent || '#a78bfa' }}
      role="button" tabIndex={0} aria-label={data.ariaLabel}
    >
      <Handle type="target" position={Position.Top} />
      <div className="node-icon">{data.icon}</div>
      <div className="node-content">
        <div className="node-label">{data.label}</div>
        {data.sublabel && <div className="node-sublabel">{data.sublabel}</div>}
        {data.signals > 0 && (
          <div className="node-signal-count">
            {data.criticalCount > 0 && <span className="signal-dot critical">{data.criticalCount}</span>}
            {data.warningCount > 0 && <span className="signal-dot warning">{data.warningCount}</span>}
            <span className="signal-total">{data.signals} signals</span>
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = {
  input: InputNode,
  neuron: NeuronNode,
  output: OutputNode,
  agent: AgentNode,
};


/* ════════════════════════════════════════════════════════════════════
   Detail Panel (drilldown)
   ════════════════════════════════════════════════════════════════════ */

function DetailPanel({ node, onClose }) {
  if (!node) return null;
  const d = node.data;

  return (
    <div className="graph-detail-panel" role="dialog" aria-label={`Details: ${d.label}`}>
      <div className="detail-header">
        <span className="detail-icon">{d.icon}</span>
        <div>
          <div className="detail-title">{d.label}</div>
          {d.sublabel && <div className="detail-subtitle">{d.sublabel}</div>}
        </div>
        <button className="detail-close" onClick={onClose} aria-label="Close details">×</button>
      </div>
      <div className="detail-body">
        {d.detailMetrics && d.detailMetrics.length > 0 && (
          <div className="detail-metrics">
            {d.detailMetrics.map((m, i) => (
              <div key={i} className="detail-metric-card">
                <span className="detail-metric-icon">{m.icon}</span>
                <span className="detail-metric-value">{m.value}</span>
                <span className="detail-metric-label">{m.label}</span>
              </div>
            ))}
          </div>
        )}
        {d.detailText && <div className="detail-text-block">{d.detailText}</div>}
        {d.detailSignals && d.detailSignals.length > 0 && (
          <div className="detail-signals">
            <div className="detail-section-title">Signals</div>
            {d.detailSignals.map((s, i) => (
              <div key={i} className={`detail-signal signal-${s.severity}`}>
                <span className="detail-signal-dot" />
                <div>
                  <div className="detail-signal-title">{s.title}</div>
                  <div className="detail-signal-detail">{s.detail}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {d.detailEvidence && (
          <div className="detail-evidence">
            <div className="detail-section-title">Evidence</div>
            {d.detailEvidence.map((e, i) => (
              <a key={i} className="detail-evidence-link" href={e.url} target="_blank" rel="noopener noreferrer">
                <span className="detail-ev-tag">{e.id}</span>
                <span className="detail-ev-source">{e.source}</span>
                <span className="detail-ev-title">{e.title}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


/* ════════════════════════════════════════════════════════════════════
   Graph Layout Builder
   ════════════════════════════════════════════════════════════════════ */

const LAYER_Y = { input: 0, stage1: 180, stage2: 380, evidence: 560, stage3: 740, agents: 920 };
const NODE_GAP = 200;

function buildGraphData(conversation, agentTeamData) {
  const nodes = [];
  const edges = [];

  if (!conversation || !conversation.messages) return { nodes, edges };

  const msgs = conversation.messages;
  const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant');
  const lastUser = [...msgs].reverse().find(m => m.role === 'user');
  if (!lastUser) return { nodes, edges };

  const userText = lastUser.content || '';

  /* ── Layer 0: User Prompt ── */
  nodes.push({
    id: 'prompt',
    type: 'input',
    position: { x: 400, y: LAYER_Y.input },
    data: {
      icon: '💬', label: 'User Prompt',
      sublabel: userText.slice(0, 120) + (userText.length > 120 ? '…' : ''),
      ariaLabel: `User prompt: ${userText.slice(0, 200)}`,
      detailText: userText,
    },
  });

  if (!lastAssistant) return { nodes, edges };

  /* ── Layer 1: Stage 1 — Individual Responses ── */
  const s1 = lastAssistant.stage1;
  if (s1 && Array.isArray(s1)) {
    const totalWidth = (s1.length - 1) * NODE_GAP;
    const startX = 400 - totalWidth / 2;

    s1.forEach((resp, i) => {
      const model = (resp.model || 'model').split('/').pop();
      const wc = (resp.response || '').split(/\s+/).length;
      const nodeId = `s1-${i}`;

      nodes.push({
        id: nodeId,
        type: 'neuron',
        position: { x: startX + i * NODE_GAP, y: LAYER_Y.stage1 },
        data: {
          icon: '🤖', label: model.slice(0, 24),
          sublabel: `${wc} words`,
          metric: `${wc}w`,
          accent: '#3b82f6',
          size: wc > 500 ? 'lg' : wc > 200 ? 'md' : 'sm',
          ariaLabel: `Stage 1: ${model}, ${wc} words`,
          detailText: resp.response || '',
          detailMetrics: [
            { icon: '📝', value: wc, label: 'Words' },
            { icon: '🤖', value: model, label: 'Model' },
          ],
        },
      });

      edges.push({
        id: `prompt-${nodeId}`,
        source: 'prompt',
        target: nodeId,
        animated: true,
        style: { stroke: '#3b82f6', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#3b82f6' },
      });
    });
  }

  /* ── Layer 2: Stage 2 — Rankings + Grounding ── */
  const s2 = lastAssistant.stage2;
  const meta = lastAssistant.metadata;
  const gs = meta?.grounding_scores;
  const aggRankings = meta?.aggregate_rankings || [];

  if (s2 && Array.isArray(s2)) {
    // Consolidation node
    nodes.push({
      id: 'ranking',
      type: 'neuron',
      position: { x: 320, y: LAYER_Y.stage2 },
      data: {
        icon: '⚖️', label: 'Peer Rankings',
        sublabel: `${s2.length} reviewers`,
        metric: aggRankings.length > 0 ? `#1: ${(aggRankings[0]?.model || '').split('/').pop().slice(0, 20)}` : null,
        accent: '#a78bfa',
        size: 'lg',
        ariaLabel: `Stage 2: ${s2.length} peer rankings`,
        detailMetrics: [
          { icon: '⚖️', value: s2.length, label: 'Reviewers' },
          ...(aggRankings.length > 0 ? [{ icon: '🏆', value: (aggRankings[0]?.model || '').split('/').pop(), label: '#1 Ranked' }] : []),
        ],
        detailText: aggRankings.map((r, i) => `#${i + 1} ${(r.model || '').split('/').pop()}`).join('\n'),
      },
    });

    // Connect all S1 nodes to ranking
    (s1 || []).forEach((_, i) => {
      edges.push({
        id: `s1-${i}-ranking`,
        source: `s1-${i}`,
        target: 'ranking',
        animated: true,
        style: { stroke: '#a78bfa', strokeWidth: 1.5, opacity: 0.7 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#a78bfa' },
      });
    });

    // Grounding node
    if (gs) {
      nodes.push({
        id: 'grounding',
        type: 'neuron',
        position: { x: 520, y: LAYER_Y.stage2 },
        data: {
          icon: '🎯', label: 'Grounding',
          sublabel: `${Math.round(gs.overall_score)}% verified`,
          metric: `${Math.round(gs.overall_score)}%`,
          accent: gs.overall_score >= 70 ? '#34d399' : gs.overall_score >= 40 ? '#fbbf24' : '#f87171',
          size: 'md',
          ariaLabel: `Grounding score: ${Math.round(gs.overall_score)}%`,
          detailMetrics: [
            { icon: '🎯', value: `${Math.round(gs.overall_score)}%`, label: 'Overall' },
            { icon: '👥', value: gs.reviewers_count, label: 'Reviewers' },
          ],
          detailText: gs.per_response?.map(r =>
            `#${r.rank} ${(r.model || '').split('/').pop()}: ${r.grounding_score}%`
          ).join('\n'),
        },
      });

      edges.push({
        id: 'ranking-grounding',
        source: 'ranking',
        target: 'grounding',
        type: 'straight',
        style: { stroke: '#34d399', strokeWidth: 1.5, strokeDasharray: '6 3' },
      });
    }
  }

  /* ── Layer 3: Evidence ── */
  const ev = lastAssistant.evidence || meta?.evidence;
  if (ev && ev.citations?.length > 0) {
    const citations = ev.citations.slice(0, 10);
    const totalWidth = (citations.length - 1) * 140;
    const startX = 400 - totalWidth / 2;

    citations.forEach((c, i) => {
      const nid = `ev-${i}`;
      nodes.push({
        id: nid,
        type: 'neuron',
        position: { x: startX + i * 140, y: LAYER_Y.evidence },
        data: {
          icon: c.source === 'OpenFDA' ? '💊' : c.source === 'PubMed' ? '📄' : '🏥',
          label: (c.title || '').slice(0, 80),
          sublabel: c.source,
          accent: '#f59e0b',
          size: 'sm',
          ariaLabel: `Citation: ${c.title} from ${c.source}`,
          detailEvidence: [c],
          detailText: c.snippet,
        },
      });

      // Connect from ranking/grounding to evidence
      const sourceId = gs ? 'grounding' : (s2 ? 'ranking' : 'prompt');
      edges.push({
        id: `${sourceId}-${nid}`,
        source: sourceId,
        target: nid,
        animated: true,
        style: { stroke: '#f59e0b', strokeWidth: 1.5, opacity: 0.6 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#f59e0b' },
      });
    });
  }

  /* ── Layer 4: Stage 3 — Chairman ── */
  const s3 = lastAssistant.stage3;
  if (s3) {
    const chairShort = (s3.model || 'chairman').split('/').pop();
    const wc = (s3.response || '').split(/\s+/).length;

    nodes.push({
      id: 'chairman',
      type: 'output',
      position: { x: 400, y: LAYER_Y.stage3 },
      data: {
        icon: '👑', label: 'Chairman Synthesis',
        sublabel: chairShort,
        metric: `${wc} words`,
        ariaLabel: `Stage 3: Chairman ${chairShort}, ${wc} words`,
        detailMetrics: [
          { icon: '👑', value: chairShort, label: 'Chairman' },
          { icon: '📝', value: wc, label: 'Words' },
          ...(ev?.citations?.length ? [{ icon: '📚', value: ev.citations.length, label: 'Citations' }] : []),
        ],
        detailText: s3.response || '',
      },
    });

    // Connect sources to chairman
    const evidenceNodes = (ev?.citations || []).slice(0, 10);
    if (evidenceNodes.length > 0) {
      evidenceNodes.forEach((_, i) => {
        edges.push({
          id: `ev-${i}-chairman`,
          source: `ev-${i}`,
          target: 'chairman',
          animated: true,
          style: { stroke: '#34d399', strokeWidth: 2, opacity: 0.7 },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#34d399' },
        });
      });
    } else {
      // Direct connection from ranking/grounding
      const sourceId = gs ? 'grounding' : (s2 ? 'ranking' : 'prompt');
      edges.push({
        id: `${sourceId}-chairman`,
        source: sourceId,
        target: 'chairman',
        animated: true,
        style: { stroke: '#34d399', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#34d399' },
      });
    }
  }

  /* ── Layer 5: Agent Team ── */
  if (agentTeamData && agentTeamData.agents?.length > 0) {
    const agents = agentTeamData.agents;
    const totalWidth = (agents.length - 1) * 170;
    const startX = 400 - totalWidth / 2;

    agents.forEach((agent, i) => {
      const signals = agent.signals || [];
      const criticalCount = signals.filter(s => s.severity === 'critical').length;
      const warningCount = signals.filter(s => s.severity === 'warning').length;
      const nid = `agent-${i}`;

      const severityAccent = criticalCount > 0 ? '#f87171'
        : warningCount > 0 ? '#fbbf24'
        : '#34d399';

      nodes.push({
        id: nid,
        type: 'agent',
        position: { x: startX + i * 150, y: LAYER_Y.agents },
        data: {
          icon: agent.icon || '🔍',
          label: agent.role || `Agent ${i + 1}`,
          sublabel: (agent.summary || '').slice(0, 150),
          accent: severityAccent,
          severity: criticalCount > 0 ? 'critical' : warningCount > 0 ? 'warning' : '',
          signals: signals.length,
          criticalCount,
          warningCount,
          ariaLabel: `${agent.role}: ${signals.length} signals, ${Math.round(agent.confidence * 100)}% confidence`,
          detailMetrics: [
            { icon: '🔍', value: `${Math.round(agent.confidence * 100)}%`, label: 'Confidence' },
            { icon: '📡', value: signals.length, label: 'Signals' },
          ],
          detailSignals: signals,
          detailText: agent.summary,
        },
      });

      if (s3) {
        edges.push({
          id: `chairman-${nid}`,
          source: 'chairman',
          target: nid,
          animated: criticalCount > 0,
          style: {
            stroke: severityAccent,
            strokeWidth: criticalCount > 0 ? 2.5 : 1.5,
            strokeDasharray: criticalCount > 0 ? undefined : '6 3',
          },
          markerEnd: { type: MarkerType.ArrowClosed, color: severityAccent },
        });
      }
    });
  }

  return { nodes, edges };
}


/* ════════════════════════════════════════════════════════════════════
   MiniMap Node Colour
   ════════════════════════════════════════════════════════════════════ */
function minimapNodeColor(node) {
  switch (node.type) {
    case 'input':  return '#14b8a6';
    case 'output': return '#34d399';
    case 'agent':  return '#a78bfa';
    default:       return node.data?.accent || '#60a5fa';
  }
}


/* ════════════════════════════════════════════════════════════════════
   Static Export Renderer (print / PDF / PNG)
   ────────────────────────────────────────────────────────────────────
   html2canvas cannot reliably capture React Flow's SVG edge layer
   or CSS-transform-positioned nodes.  This component renders a pure
   HTML + inline-SVG snapshot of the same graph data using absolute
   positioning and simple bezier paths — no transforms, no
   backdrop-filter, no animations.  Hidden by default; shown only
   when `.export-print-mode` is applied by ExportToolbar.
   ════════════════════════════════════════════════════════════════════ */

const STATIC_NODE_H = 62;

function staticNodeW(node) {
  switch (node.type) {
    case 'input':  return 280;
    case 'output': return 300;
    case 'agent':  return 220;
    default:       return node.data?.size === 'lg' ? 230
                        : node.data?.size === 'sm' ? 175 : 200;
  }
}

const SEVERITY_BG = { critical: '#fef2f2', warning: '#fffbeb', info: '#eff6ff', success: '#ecfdf5' };
const SEVERITY_BORDER = { critical: '#fca5a5', warning: '#fcd34d', info: '#93c5fd', success: '#6ee7b7' };
const SEVERITY_DOT = { critical: '#ef4444', warning: '#f59e0b', info: '#3b82f6', success: '#22c55e' };

function StaticGraphExport({ nodes, edges }) {
  if (!nodes.length) return null;

  const PAD = 60;
  const sized = nodes.map(n => ({ ...n, w: staticNodeW(n), h: STATIC_NODE_H }));

  const minX = Math.min(...sized.map(n => n.position.x));
  const minY = Math.min(...sized.map(n => n.position.y));
  const maxX = Math.max(...sized.map(n => n.position.x + n.w));
  const maxY = Math.max(...sized.map(n => n.position.y + n.h));

  const graphWidth  = maxX - minX + PAD * 2;
  const graphHeight = maxY - minY + PAD * 2 + 44;

  const ox = x => x - minX + PAD;
  const oy = y => y - minY + PAD;

  function edgeGeo(edge) {
    const src = sized.find(n => n.id === edge.source);
    const tgt = sized.find(n => n.id === edge.target);
    if (!src || !tgt) return null;

    const sameLevel = Math.abs(src.position.y - tgt.position.y) < 20;

    if (sameLevel) {
      const sx = ox(src.position.x + src.w);
      const sy = oy(src.position.y + src.h / 2);
      const tx = ox(tgt.position.x);
      const ty = oy(tgt.position.y + tgt.h / 2);
      return {
        d: `M ${sx} ${sy} L ${tx} ${ty}`,
        arrow: `${tx - 8},${ty - 5} ${tx - 8},${ty + 5} ${tx},${ty}`,
      };
    }

    const sx = ox(src.position.x + src.w / 2);
    const sy = oy(src.position.y + STATIC_NODE_H);
    const tx = ox(tgt.position.x + tgt.w / 2);
    const ty = oy(tgt.position.y);
    const dy = ty - sy;
    return {
      d: `M ${sx} ${sy} C ${sx} ${sy + dy * 0.4}, ${tx} ${ty - dy * 0.4}, ${tx} ${ty}`,
      arrow: `${tx - 5},${ty - 8} ${tx + 5},${ty - 8} ${tx},${ty}`,
    };
  }

  const LEGEND = [
    ['#14b8a6', 'Prompt'], ['#3b82f6', 'Stage 1'], ['#a78bfa', 'Stage 2'],
    ['#f59e0b', 'Evidence'], ['#34d399', 'Chairman'], ['#f87171', 'Agents'],
  ];

  // Collect agent nodes that have detail data for callout cards
  const agentNodes = nodes.filter(n => n.type === 'agent' && n.data);
  const hasCallouts = agentNodes.some(n =>
    (n.data.detailSignals?.length > 0) || n.data.detailText || (n.data.detailMetrics?.length > 0)
  );

  return (
    <div className="static-graph-export" style={{ width: graphWidth }}>

      {/* ═══ Page 1: Graph ═══ */}
      <div className="sg-graph-page" style={{ width: graphWidth, height: graphHeight, position: 'relative' }}>

        {/* SVG edge layer */}
        <svg width={graphWidth} height={graphHeight}
          style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}>
          {edges.map(edge => {
            const geo = edgeGeo(edge);
            if (!geo) return null;
            const c = edge.style?.stroke || '#94a3b8';
            return (
              <g key={edge.id}>
                <path d={geo.d} fill="none" stroke={c}
                  strokeWidth={Math.max((edge.style?.strokeWidth || 1.5) + 0.5, 2)}
                  strokeDasharray={edge.style?.strokeDasharray || 'none'}
                  opacity={Math.max(edge.style?.opacity || 1, 0.55)} />
                <polygon points={geo.arrow} fill={c}
                  opacity={Math.max(edge.style?.opacity || 1, 0.7)} />
              </g>
            );
          })}
        </svg>

        {/* Node cards */}
        {sized.map(node => (
          <div key={node.id}
            className={`sn sn-${node.type} ${node.data?.severity || ''}`}
            style={{ position: 'absolute', left: ox(node.position.x), top: oy(node.position.y), width: node.w }}>
            <span className="sn-icon">{node.data.icon}</span>
            <div className="sn-body">
              <div className="sn-label">{node.data.label}</div>
              {node.data.sublabel && <div className="sn-sub">{node.data.sublabel}</div>}
              {node.data.metric && <div className="sn-metric">{node.data.metric}</div>}
            </div>
            {node.data.signals > 0 && (
              <div className="sn-signals">
                {node.data.criticalCount > 0 && <span className="sn-dot sn-crit">{node.data.criticalCount}</span>}
                {node.data.warningCount > 0 && <span className="sn-dot sn-warn">{node.data.warningCount}</span>}
              </div>
            )}
          </div>
        ))}

        {/* Legend */}
        <div className="sg-legend" style={{ position: 'absolute', bottom: 10, left: PAD }}>
          {LEGEND.map(([color, label]) => (
            <span key={label} className="sg-leg">
              <span className="sg-dot" style={{ background: color }} />{label}
            </span>
          ))}
        </div>
      </div>

      {/* ═══ Page 2: Agent Detail Callouts ═══ */}
      {hasCallouts && (
        <div className="sg-callouts">
          <div className="sg-callouts-title">Agent Analysis Detail</div>
          <div className="sg-callouts-subtitle">Expanded signal breakdown for each council agent</div>

          <div className="sg-callouts-grid">
            {agentNodes.map(node => {
              const d = node.data;
              const signals = d.detailSignals || [];
              const metrics = d.detailMetrics || [];
              return (
                <div key={node.id} className={`sg-card ${d.severity || ''}`}>
                  {/* Card header */}
                  <div className="sg-card-header">
                    <span className="sg-card-icon">{d.icon}</span>
                    <div className="sg-card-title">{d.label}</div>
                    {d.severity && (
                      <span className="sg-card-badge"
                        style={{ background: d.severity === 'critical' ? '#fef2f2'
                          : d.severity === 'warning' ? '#fffbeb' : '#ecfdf5',
                          color: d.severity === 'critical' ? '#dc2626'
                          : d.severity === 'warning' ? '#d97706' : '#059669',
                          border: `1px solid ${d.severity === 'critical' ? '#fca5a5'
                          : d.severity === 'warning' ? '#fcd34d' : '#6ee7b7'}` }}>
                        {d.severity}
                      </span>
                    )}
                  </div>

                  {/* Metrics row */}
                  {metrics.length > 0 && (
                    <div className="sg-card-metrics">
                      {metrics.map((m, i) => (
                        <div key={i} className="sg-card-metric">
                          <span className="sg-cm-icon">{m.icon}</span>
                          <span className="sg-cm-val">{m.value}</span>
                          <span className="sg-cm-lbl">{m.label}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Summary text */}
                  {d.detailText && (
                    <div className="sg-card-text">{d.detailText}</div>
                  )}

                  {/* Signals */}
                  {signals.length > 0 && (
                    <div className="sg-card-signals">
                      <div className="sg-card-section-hd">Signals ({signals.length})</div>
                      {signals.map((s, i) => (
                        <div key={i} className="sg-signal-row"
                          style={{ borderLeft: `3px solid ${SEVERITY_DOT[s.severity] || '#94a3b8'}`,
                            background: SEVERITY_BG[s.severity] || '#f8fafc' }}>
                          <div className="sg-signal-title">{s.title}</div>
                          {s.detail && <div className="sg-signal-detail">{s.detail}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


/* ════════════════════════════════════════════════════════════════════
   Main Component
   ════════════════════════════════════════════════════════════════════ */

export default function CouncilGraph({ conversation, agentTeamData }) {
  const [selectedNode, setSelectedNode] = useState(null);

  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildGraphData(conversation, agentTeamData),
    [conversation, agentTeamData],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges);

  // Sync React Flow state when upstream data changes
  useEffect(() => {
    setNodes(initNodes);
    setEdges(initEdges);
  }, [initNodes, initEdges, setNodes, setEdges]);

  const onNodeClick = useCallback((event, node) => {
    setSelectedNode(prev => prev?.id === node.id ? null : node);
    // Mark clicked node as active, deactivate others
    setNodes(nds => nds.map(n => ({
      ...n,
      data: { ...n.data, active: n.id === node.id },
    })));
  }, [setNodes]);

  if (!initNodes.length) {
    return (
      <div className="graph-empty" role="status">
        <div className="graph-empty-icon">🧠</div>
        <div className="graph-empty-text">
          Send a prompt to visualise the council neural graph.
        </div>
      </div>
    );
  }

  return (
    <div className="council-graph-container" role="region"
      aria-label="Council Neural Network Graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        className="council-reactflow"
      >
        <Background color="var(--graph-grid, rgba(100,116,139,0.08))" gap={24} size={1} />
        <Controls showInteractive={false} className="graph-controls" />
        <MiniMap nodeColor={minimapNodeColor} className="graph-minimap"
          maskColor="var(--graph-minimap-mask, rgba(10,22,40,0.7))" />
      </ReactFlow>
      <DetailPanel node={selectedNode} onClose={() => {
        setSelectedNode(null);
        setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, active: false } })));
      }} />

      {/* Layer legend */}
      <div className="graph-legend" aria-label="Graph layer legend">
        <span className="legend-item"><span className="legend-dot" style={{ background: '#14b8a6' }} /> Prompt</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#3b82f6' }} /> Stage 1</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#a78bfa' }} /> Stage 2</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#f59e0b' }} /> Evidence</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#34d399' }} /> Chairman</span>
        <span className="legend-item"><span className="legend-dot" style={{ background: '#f87171' }} /> Agents</span>
      </div>

      {/* Static snapshot for PDF/PNG export (hidden until export-print-mode) */}
      <StaticGraphExport nodes={initNodes} edges={initEdges} />
    </div>
  );
}
