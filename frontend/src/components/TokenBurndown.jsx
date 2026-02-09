import { useState } from 'react';
import './TokenBurndown.css';

/**
 * Cost / token burndown dashboard.
 * Shows per-stage consumption, per-model breakdown,
 * and gateway-vs-direct savings.
 */
export default function TokenBurndown({ costSummary }) {
  const [expanded, setExpanded] = useState(false);

  if (!costSummary) return null;

  const { totals, per_stage, per_model } = costSummary;
  if (!totals) return null;

  const fmt = (v) => (v != null ? `$${v.toFixed(4)}` : '—');
  const fmtTokens = (v) => (v != null ? v.toLocaleString() : '—');
  const savingsPct = totals.savings_pct != null ? Math.round(totals.savings_pct) : 0;

  return (
    <div className="burndown-card">
      <div className="burndown-header" onClick={() => setExpanded(!expanded)}>
        {/* Token totals */}
        <div className="burndown-stat">
          <span className="burndown-stat-value">{fmtTokens(totals.total_tokens)}</span>
          <span className="burndown-stat-label">Total Tokens</span>
        </div>

        {/* Gateway cost */}
        <div className="burndown-stat">
          <span className="burndown-stat-value cost-value">{fmt(totals.gateway_cost_usd)}</span>
          <span className="burndown-stat-label">Gateway Cost</span>
        </div>

        {/* Savings */}
        <div className="burndown-stat savings-stat">
          <span className="burndown-stat-value savings-value">{fmt(totals.savings_usd)}</span>
          <span className="burndown-stat-label">Saved ({savingsPct}%)</span>
        </div>

        <button
          className="burndown-toggle"
          aria-label={expanded ? 'Collapse cost details' : 'Expand cost details'}
          aria-expanded={expanded}
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>

      {expanded && (
        <div className="burndown-details">
          {/* Per-stage breakdown */}
          {per_stage && per_stage.length > 0 && (
            <div className="burndown-section">
              <h5>Per-Stage Breakdown</h5>
              <table className="burndown-table">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Prompt</th>
                    <th>Completion</th>
                    <th>Total</th>
                    <th>Gateway</th>
                    <th>Direct</th>
                    <th>Saved</th>
                  </tr>
                </thead>
                <tbody>
                  {per_stage.map((s, i) => (
                    <tr key={i}>
                      <td className="stage-name-cell">{s.stage.replace('stage', 'Stage ')}</td>
                      <td>{fmtTokens(s.prompt_tokens)}</td>
                      <td>{fmtTokens(s.completion_tokens)}</td>
                      <td>{fmtTokens(s.total_tokens)}</td>
                      <td className="cost-cell">{fmt(s.gateway_cost_usd)}</td>
                      <td className="cost-cell direct-cell">{fmt(s.direct_cost_usd)}</td>
                      <td className="cost-cell savings-cell">{fmt(s.savings_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Per-model breakdown */}
          {per_model && Object.keys(per_model).length > 0 && (
            <div className="burndown-section">
              <h5>Per-Model Breakdown</h5>
              <div className="model-cost-list">
                {Object.entries(per_model).map(([model, data]) => {
                  const modelShort = model.split('/')[1] || model;
                  const barPct = totals.total_tokens > 0
                    ? Math.round((data.total_tokens / totals.total_tokens) * 100)
                    : 0;
                  return (
                    <div className="model-cost-row" key={model}>
                      <span className="model-cost-name">{modelShort}</span>
                      <div className="model-cost-bar-track">
                        <div
                          className="model-cost-bar-fill"
                          style={{ width: `${barPct}%` }}
                        />
                      </div>
                      <span className="model-cost-tokens">{fmtTokens(data.total_tokens)}</span>
                      <span className="model-cost-price">{fmt(data.gateway_cost_usd)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Direct-vs-Gateway comparison */}
          <div className="burndown-section">
            <h5>Gateway vs Direct Pricing</h5>
            <div className="gateway-comparison">
              <div className="comparison-bar">
                <div className="comparison-label">Direct</div>
                <div className="comparison-track">
                  <div className="comparison-fill direct-fill" style={{ width: '100%' }} />
                </div>
                <div className="comparison-amount">{fmt(totals.direct_cost_usd)}</div>
              </div>
              <div className="comparison-bar">
                <div className="comparison-label">Gateway</div>
                <div className="comparison-track">
                  <div
                    className="comparison-fill gateway-fill"
                    style={{
                      width: totals.direct_cost_usd > 0
                        ? `${Math.round((totals.gateway_cost_usd / totals.direct_cost_usd) * 100)}%`
                        : '0%',
                    }}
                  />
                </div>
                <div className="comparison-amount">{fmt(totals.gateway_cost_usd)}</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
