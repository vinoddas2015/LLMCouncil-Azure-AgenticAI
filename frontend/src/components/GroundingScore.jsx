import { useState } from 'react';
import './GroundingScore.css';

/** Small pharma metric bar with label, value, and formula tooltip. */
function PharmaBar({ label, value, formula }) {
  const pct = Math.round(value ?? 0);
  const color = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--error)';
  return (
    <div className="pharma-bar-row" title={formula}>
      <span className="pharma-bar-label">{label}</span>
      <div className="pharma-bar-track">
        <div className="pharma-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="pharma-bar-value" style={{ color }}>{pct}%</span>
    </div>
  );
}

/**
 * Circular grounding-score bubble with per-criteria breakdown.
 * Inspired by compliance-evidence card UX (circular gauge + metric bars).
 */
export default function GroundingScore({ groundingScores }) {
  const [expanded, setExpanded] = useState(false);

  if (!groundingScores) return null;

  const { overall_score, per_response, criteria_definitions, council_size, reviewers_count } = groundingScores;

  // overall_score comes from backend already as 0–100 (e.g. 76.7)
  const pct = Math.round(overall_score);
  const pctFraction = overall_score / 100;   // 0–1 for SVG ring

  // SVG circle params
  const radius = 54;
  const stroke = 7;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pctFraction * circumference);

  // Color tier
  const tierColor = pct >= 80 ? 'var(--success)' : pct >= 60 ? 'var(--warning)' : 'var(--error)';
  const tierLabel = pct >= 80 ? 'High' : pct >= 60 ? 'Moderate' : 'Low';

  return (
    <div className="grounding-card">
      <div className="grounding-header" onClick={() => setExpanded(!expanded)}>
        <div className="grounding-bubble-wrap">
          <svg className="grounding-ring" width="130" height="130" viewBox="0 0 130 130">
            {/* Track */}
            <circle
              cx="65" cy="65" r={radius}
              fill="none"
              stroke="var(--bg-surface)"
              strokeWidth={stroke}
            />
            {/* Progress */}
            <circle
              className="grounding-progress"
              cx="65" cy="65" r={radius}
              fill="none"
              stroke={tierColor}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              transform="rotate(-90 65 65)"
            />
          </svg>
          <div className="grounding-pct">
            <span className="grounding-number" style={{ color: tierColor }}>{pct}</span>
            <span className="grounding-symbol">%</span>
          </div>
        </div>
        <div className="grounding-meta">
          <span className="grounding-label">Grounding Score</span>
          <span className="grounding-tier" style={{ color: tierColor }}>{tierLabel} Confidence</span>
          <span className="grounding-info">{reviewers_count} reviewers &middot; {council_size} models</span>
        </div>
        <button
          className="grounding-toggle"
          aria-label={expanded ? 'Collapse details' : 'Expand details'}
          aria-expanded={expanded}
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>

      {expanded && (
        <div className="grounding-details">
          {/* Criteria bars */}
          {criteria_definitions && (
            <div className="grounding-criteria">
              <h5>Rubric Criteria</h5>
              {/* criteria_definitions is an ARRAY of {id, name, weight, description} */}
              {(Array.isArray(criteria_definitions) ? criteria_definitions : []).map((def) => {
                const criteriaId = def.id;   // e.g. "relevancy"
                // Backend criteria values are already 0–100
                const avgScore = per_response && per_response.length > 0
                  ? per_response.reduce((sum, r) => sum + (r.criteria?.[criteriaId] ?? 0), 0) / per_response.length
                  : 0;
                const barPct = Math.round(avgScore);
                return (
                  <div className="criteria-row" key={criteriaId}>
                    <div className="criteria-label-row">
                      <span className="criteria-name">{def.name}</span>
                      <span className="criteria-weight">{Math.round(def.weight * 100)}%</span>
                      <span className="criteria-value">{barPct}%</span>
                    </div>
                    <div className="criteria-bar-track">
                      <div
                        className="criteria-bar-fill"
                        style={{ width: `${barPct}%`, background: tierColor }}
                      />
                    </div>
                    <span className="criteria-desc">{def.description}</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Per-model grounding scores */}
          {per_response && per_response.length > 0 && (
            <div className="grounding-models">
              <h5>Per-Model Grounding</h5>
              {per_response.map((r, i) => {
                // grounding_score is already 0–100 from backend
                const mPct = Math.round(r.grounding_score);
                const mColor = mPct >= 80 ? 'var(--success)' : mPct >= 60 ? 'var(--warning)' : 'var(--error)';
                return (
                  <div className="model-grounding-row" key={i}>
                    <span className="model-grounding-rank">#{r.rank}</span>
                    <span className="model-grounding-name">{(r.model || '').split('/')[1] || r.model}</span>
                    <div className="model-grounding-bar-track">
                      <div className="model-grounding-bar-fill" style={{ width: `${mPct}%`, background: mColor }} />
                    </div>
                    <span className="model-grounding-pct" style={{ color: mColor }}>{mPct}%</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Pharma Safety Metrics */}
          {per_response && per_response.some(r => r.pharma_metrics) && (
            <div className="grounding-pharma">
              <h5>Pharma Safety Metrics</h5>
              <p className="pharma-explainer">
                Correctness penalises missing critical info (FN) twice as hard as inaccuracies (FP).
              </p>
              {per_response.map((r, i) => {
                const pm = r.pharma_metrics;
                if (!pm) return null;
                const shortName = (r.model || '').split('/')[1] || r.model;
                return (
                  <div className="pharma-model-block" key={i}>
                    <span className="pharma-model-name">#{r.rank} {shortName}</span>
                    <div className="pharma-metrics-grid">
                      <PharmaBar label="Correctness" value={pm.correctness} formula="TP/(TP+2×FN+FP)" />
                      <PharmaBar label="Precision" value={pm.precision} formula="TP/(TP+FP)" />
                      <PharmaBar label="Recall" value={pm.recall} formula="TP/(TP+FN)" />
                    </div>
                    <span className="pharma-counts">
                      TP {pm.tp} · FP {pm.fp} · FN {pm.fn}
                      {r.verbalized_coverage != null && (
                        <> · VS coverage {Math.round(r.verbalized_coverage * 100)}%</>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
