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
                Peer-reviewed confusion matrix (self-reviews excluded). TP/FP/FN averaged per reviewer for equal distribution. Correctness penalises missing critical info (FN) twice as hard as inaccuracies (FP). F1 is the RAGAS-aligned balanced score.
              </p>
              {per_response.map((r, i) => {
                const pm = r.pharma_metrics;
                if (!pm) return null;
                const shortName = (r.model || '').split('/')[1] || r.model;
                return (
                  <div className="pharma-model-block" key={i}>
                    <span className="pharma-model-name">#{r.rank} {shortName}</span>
                    <div className="pharma-metrics-grid">
                      <PharmaBar label="Correctness" value={pm.correctness} formula="TP/(TP+2×FN+FP) — Pharma-weighted" />
                      <PharmaBar label="F1 (RAGAS)" value={pm.f1} formula="TP/(TP+0.5×(FP+FN)) — RAGAS Factual Correctness" />
                      <PharmaBar label="Precision" value={pm.precision} formula="TP/(TP+FP) — = RAGAS Faithfulness" />
                      <PharmaBar label="Recall" value={pm.recall} formula="TP/(TP+FN) — = RAGAS Context Recall" />
                    </div>
                    <span className="pharma-counts">
                      TP {pm.tp} · FP {pm.fp} · FN {pm.fn}
                      {r.peer_reviews != null && (
                        <> · {r.peer_reviews} peer review{r.peer_reviews !== 1 ? 's' : ''}</>
                      )}
                      {r.verbalized_coverage != null && (
                        <> · VS coverage {Math.round(r.verbalized_coverage * 100)}%</>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Context Awareness (Catastrophic Forgetting Detection) */}
          {per_response && per_response.some(r => r.context_awareness) && (
            <div className="grounding-context-awareness">
              <h5>Context Awareness <span className="ca-subtitle">(Catastrophic Forgetting Detection)</span></h5>
              <p className="pharma-explainer">
                Self-review only: measures whether a model recognises its own claims when reviewing its anonymized response. Low score = forgetting or self-contradiction.
                {groundingScores.ca_enhanced && (
                  <> Multi-round validation with adversarial paragraph shuffling provides stability measurement.</>
                )}
              </p>
              {per_response.map((r, i) => {
                const ca = r.context_awareness;
                if (!ca || ca.score == null) return null;
                const shortName = (r.model || '').split('/')[1] || r.model;
                const displayScore = ca.combined_score != null ? ca.combined_score : ca.score;
                const caPct = Math.round(displayScore);
                const caColor = caPct >= 80 ? 'var(--success)' : caPct >= 60 ? 'var(--warning)' : 'var(--error)';
                const caLabel = caPct >= 80 ? 'Strong' : caPct >= 60 ? 'Moderate' : 'Weak (Forgetting)';
                const hasMultiRound = ca.round1_score != null && ca.round2_score != null;
                return (
                  <div className="ca-model-block" key={i}>
                    <div className="ca-header-row">
                      <span className="pharma-model-name">#{r.rank} {shortName}</span>
                      <span className="ca-score" style={{ color: caColor }}>
                        {caPct}% — {caLabel}
                        {hasMultiRound && ca.stability != null && (
                          <span className="ca-stability-badge" title={`Stability: consistency between Round 1 and Round 2 self-review`}>
                            {' '}· Stability {Math.round(ca.stability)}%
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="ca-bar-track">
                      <div className="ca-bar-fill" style={{ width: `${caPct}%`, background: caColor }} />
                    </div>
                    {hasMultiRound ? (
                      <div className="ca-multi-round">
                        <span className="pharma-counts">
                          R1: {Math.round(ca.round1_score)}%
                          (self-TP {ca.self_tp} · self-FP {ca.self_fp} · self-FN {ca.self_fn})
                        </span>
                        <span className="pharma-counts">
                          R2{ca.shuffled ? ' (shuffled)' : ''}: {Math.round(ca.round2_score)}%
                          (TP {ca.round2_tp} · FP {ca.round2_fp} · FN {ca.round2_fn})
                        </span>
                        {ca.adversarial_delta != null && (
                          <span className="ca-delta" style={{
                            color: Math.abs(ca.adversarial_delta) <= 10 ? 'var(--success)' :
                                   Math.abs(ca.adversarial_delta) <= 25 ? 'var(--warning)' : 'var(--error)'
                          }}>
                            Δ {ca.adversarial_delta > 0 ? '+' : ''}{Math.round(ca.adversarial_delta)}%
                            {Math.abs(ca.adversarial_delta) <= 10 ? ' (stable)' :
                             Math.abs(ca.adversarial_delta) <= 25 ? ' (moderate shift)' : ' (position-sensitive)'}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="pharma-counts">
                        self-TP {ca.self_tp} · self-FP {ca.self_fp} · self-FN {ca.self_fn}
                      </span>
                    )}
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
