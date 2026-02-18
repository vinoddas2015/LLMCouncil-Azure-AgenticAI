/**
 * InfographicPanel — Visual summary infographic from Chairman's response.
 *
 * Renders structured data extracted from the chairman's output as
 * a visually appealing infographic panel with:
 *   - Key metric cards with icons
 *   - Comparison tables (bar-chart style)
 *   - Process/mechanism flow steps
 *   - Highlight cards (success, warning, info, danger)
 */

import { useState, useRef } from 'react';
import ExportToolbar from './ExportToolbar';
import './InfographicPanel.css';

const HIGHLIGHT_STYLES = {
  success: { bg: 'rgba(52, 211, 153, 0.12)', border: '#34d399', icon: '✅' },
  warning: { bg: 'rgba(251, 191, 36, 0.12)', border: '#fbbf24', icon: '⚠️' },
  info:    { bg: 'rgba(96, 165, 250, 0.12)', border: '#60a5fa', icon: 'ℹ️' },
  danger:  { bg: 'rgba(248, 113, 113, 0.12)', border: '#f87171', icon: '🔴' },
};

function MetricCard({ metric }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`infographic-metric-card ${expanded ? 'metric-expanded' : ''}`}
      onClick={() => setExpanded(!expanded)}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded); } }}
      aria-expanded={expanded}
      aria-label={`${metric.value} — ${metric.label}. Click to ${expanded ? 'collapse' : 'expand'}`}
    >
      <span className="metric-icon">{metric.icon || '📊'}</span>
      <div className="metric-body">
        <span className={`metric-value ${expanded ? 'metric-value--full' : ''}`}>
          {metric.value}
        </span>
        <span className={`metric-label ${expanded ? 'metric-label--full' : ''}`}>
          {metric.label}
        </span>
      </div>
      <span className="metric-expand-hint">{expanded ? '▲' : '▼'}</span>
    </div>
  );
}

function ComparisonTable({ comparison }) {
  if (!comparison?.headers || !comparison?.rows) return null;
  return (
    <div className="infographic-comparison">
      <table className="comparison-table">
        <thead>
          <tr>
            {comparison.headers.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className={ci === 0 ? 'row-label' : ''}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProcessSteps({ steps }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="infographic-process">
      <div className="process-flow">
        {steps.map((step, i) => (
          <div key={i} className="process-step">
            <div className="step-number">{step.step}</div>
            <div className="step-content">
              <div className="step-title">{step.title}</div>
              {step.description && (
                <div className="step-desc">{step.description}</div>
              )}
            </div>
            {i < steps.length - 1 && <div className="step-connector">→</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function HighlightCards({ highlights }) {
  if (!highlights || highlights.length === 0) return null;
  return (
    <div className="infographic-highlights">
      {highlights.map((h, i) => {
        const style = HIGHLIGHT_STYLES[h.type] || HIGHLIGHT_STYLES.info;
        return (
          <div
            key={i}
            className={`highlight-card highlight-${h.type}`}
            style={{
              background: style.bg,
              borderLeft: `3px solid ${style.border}`,
            }}
          >
            <span className="highlight-icon">{style.icon}</span>
            <span className="highlight-text">{h.text}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Value Proposition Template — Challenge → Solution → Outcome
   ═══════════════════════════════════════════════════════════════ */

const VP_SECTION_STYLES = {
  challenge: { accent: '#f59e0b', icon: '⚡', label: 'THE CHALLENGE' },
  solution:  { accent: '#3b82f6', icon: '💡', label: 'THE SOLUTION' },
  outcome:   { accent: '#10b981', icon: '🎯', label: 'THE OUTCOME' },
};

function ValuePropositionTemplate({ data }) {
  const sections = data.sections || [];
  const hasMetrics = data.key_metrics && data.key_metrics.length > 0;
  const hasHighlights = data.highlights && data.highlights.length > 0;

  return (
    <>
      {/* VP Header */}
      <div className="vp-header">
        <div className="vp-header-icon">📋</div>
        <div className="vp-header-text">
          <h3 className="vp-title">{data.title || 'Value Proposition'}</h3>
          <span className="vp-subtitle">Pharmaceutical Value Proposition Template</span>
        </div>
      </div>

      {/* Challenge → Solution → Outcome Cards */}
      <div className="vp-sections">
        {sections.map((section, i) => {
          const style = VP_SECTION_STYLES[section.section_type] || VP_SECTION_STYLES.challenge;
          return (
            <div
              key={i}
              className={`vp-section vp-section--${section.section_type}`}
              style={{ borderLeftColor: style.accent }}
            >
              <div className="vp-section-header">
                <span className="vp-section-icon">{style.icon}</span>
                <span className="vp-section-label" style={{ color: style.accent }}>
                  {style.label}
                </span>
              </div>
              {section.content && (
                <p className="vp-section-content">{section.content}</p>
              )}
              {section.bullets && section.bullets.length > 0 && (
                <ul className="vp-section-bullets">
                  {section.bullets.map((b, bi) => (
                    <li key={bi}>
                      <span className="vp-bullet" style={{ color: style.accent }}>&#9658;</span>
                      <span className="vp-bullet-text">{b}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      {/* Metrics row (if available) */}
      {hasMetrics && (
        <div className="infographic-section">
          <div className="section-label">Key Metrics</div>
          <div className="metrics-grid">
            {data.key_metrics.map((metric, i) => (
              <MetricCard key={i} metric={metric} />
            ))}
          </div>
        </div>
      )}

      {/* Highlights */}
      {hasHighlights && (
        <div className="infographic-section">
          <div className="section-label">Key Takeaways</div>
          <HighlightCards highlights={data.highlights} />
        </div>
      )}
    </>
  );
}

export default function InfographicPanel({ data }) {
  const [collapsed, setCollapsed] = useState(false);
  const bodyRef = useRef(null);

  if (!data) return null;

  const isVP = data.type === 'value_proposition' && data.sections?.length > 0;
  const hasMetrics = data.key_metrics && data.key_metrics.length > 0;
  const hasComparison = data.comparison?.headers?.length > 0;
  const hasSteps = data.process_steps && data.process_steps.length > 0;
  const hasHighlights = data.highlights && data.highlights.length > 0;

  // Don't render if no meaningful content
  if (!isVP && !hasMetrics && !hasComparison && !hasSteps && !hasHighlights) return null;

  return (
    <div className={`infographic-panel ${isVP ? 'infographic-panel--vp' : ''}`}>
      <div
        className="infographic-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="infographic-icon">{isVP ? '📋' : '📊'}</span>
        <span className="infographic-title">
          {data.title || 'Visual Summary'}
        </span>
        <span className="infographic-badge">
          {isVP ? 'Value Proposition' : 'Infographic'}
        </span>
        <ExportToolbar targetRef={bodyRef} filenamePrefix={
          isVP ? 'LLMCouncil_ValueProposition' : 'LLMCouncil_Infographic'
        } />
        <span className={`infographic-toggle ${collapsed ? 'collapsed' : ''}`}>
          ▼
        </span>
      </div>

      {!collapsed && (
        <div className="infographic-body" ref={bodyRef}>
          {/* Print-only title — visible only during A4 export capture (non-VP) */}
          {!isVP && (
            <div className="infographic-print-title">
              {data.title || 'Visual Summary'}
              <div className="infographic-print-subtitle">
                LLM Council — Generated Infographic Report
              </div>
            </div>
          )}

          {/* ── Value Proposition Template ── */}
          {isVP ? (
            <ValuePropositionTemplate data={data} />
          ) : (
            <>
              {/* Key Metrics Row */}
              {hasMetrics && (
                <div className="infographic-section">
                  <div className="section-label">Key Metrics</div>
                  <div className="metrics-grid">
                    {data.key_metrics.map((metric, i) => (
                      <MetricCard key={i} metric={metric} />
                    ))}
                  </div>
                </div>
              )}

              {/* Comparison Table */}
              {hasComparison && (
                <div className="infographic-section">
                  <div className="section-label">Comparison</div>
                  <ComparisonTable comparison={data.comparison} />
                </div>
              )}

              {/* Process Steps */}
              {hasSteps && (
                <div className="infographic-section">
                  <div className="section-label">Process / Mechanism</div>
                  <ProcessSteps steps={data.process_steps} />
                </div>
              )}

              {/* Highlights */}
              {hasHighlights && (
                <div className="infographic-section">
                  <div className="section-label">Key Takeaways</div>
                  <HighlightCards highlights={data.highlights} />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
