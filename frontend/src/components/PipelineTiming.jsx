import { useState, useMemo } from 'react';
import './PipelineTiming.css';

/**
 * Pipeline Timing Diagnostics dashboard.
 * Renders timing data emitted within cost_summary.timing.
 *
 * Shows: total time, stage distribution waterfall, per-model latencies,
 * Azure (Bayer myGenAssist) vs Google Direct provider comparison,
 * and bottleneck identification.
 */

const STAGE_LABELS = {
  prompt_guard: 'Prompt Guard',
  memory_recall: 'Memory Recall',
  stage1: 'Stage 1 — Model Responses',
  title_generation: 'Title Generation',
  context_classify: 'Context Classification',
  stage2: 'Stage 2 — Peer Review',
  evidence_retrieval: 'Evidence Retrieval',
  grounding_compute: 'Grounding Compute',
  stage3_streaming: 'Stage 3 — Chairman (Stream)',
  stage3_fallback: 'Stage 3 — Chairman (Fallback)',
  ca_validation: 'CA Validation',
  doubting_thomas: 'Doubting Thomas',
  citation_enrich: 'Citation Enrichment',
  citation_validate: 'Citation Validation',
  agent_team: 'Agent Team',
  learning: 'Learning / Memory',
};

const STAGE_COLORS = {
  prompt_guard: '#94a3b8',
  memory_recall: '#a78bfa',
  stage1: '#60a5fa',
  title_generation: '#94a3b8',
  context_classify: '#94a3b8',
  stage2: '#f59e0b',
  evidence_retrieval: '#34d399',
  grounding_compute: '#f87171',
  stage3_streaming: '#818cf8',
  stage3_fallback: '#818cf8',
  ca_validation: '#fb923c',
  doubting_thomas: '#e879f9',
  citation_enrich: '#22d3ee',
  citation_validate: '#22d3ee',
  agent_team: '#4ade80',
  learning: '#facc15',
};

const STAGE_ORDER = [
  'prompt_guard', 'memory_recall', 'stage1', 'title_generation',
  'context_classify', 'stage2', 'evidence_retrieval', 'grounding_compute',
  'stage3_streaming', 'stage3_fallback', 'ca_validation', 'doubting_thomas',
  'citation_enrich', 'citation_validate', 'agent_team', 'learning',
];

const fmtMs = (ms) => {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};

export default function PipelineTiming({ timing, redisCache }) {
  const [expanded, setExpanded] = useState(false);
  const [showModels, setShowModels] = useState(null); // stage name to expand

  if (!timing || !timing.total_ms) return null;

  const { total_ms, stages, distribution_pct, bottleneck, slowest_models, provider_latencies } = timing;

  // Ordered stages that have data
  const orderedStages = useMemo(() =>
    STAGE_ORDER.filter(s => stages?.[s]),
    [stages]
  );

  const maxStageMs = useMemo(() =>
    Math.max(...orderedStages.map(s => stages[s]?.ms || 0), 1),
    [orderedStages, stages]
  );

  return (
    <div className="timing-card">
      <div className="timing-header" onClick={() => setExpanded(!expanded)}>
        <div className="timing-icon">⏱️</div>
        <div className="timing-headline">
          <span className="timing-total">{fmtMs(total_ms)}</span>
          <span className="timing-label">Pipeline Duration</span>
        </div>
        {bottleneck && (
          <div className="timing-bottleneck">
            <span className="timing-bottleneck-label">Bottleneck</span>
            <span className="timing-bottleneck-value">
              {STAGE_LABELS[bottleneck] || bottleneck}
              {distribution_pct?.[bottleneck] != null && ` (${distribution_pct[bottleneck]}%)`}
            </span>
          </div>
        )}
        {provider_latencies && Object.keys(provider_latencies).length > 1 && (
          <div className="timing-providers-mini">
            {provider_latencies.bayer_mygenassist && (
              <span className="provider-badge bayer" title="Bayer myGenAssist (Azure-hosted)">
                🏢 {fmtMs(provider_latencies.bayer_mygenassist.avg_ms)}
              </span>
            )}
            {provider_latencies.google_direct && (
              <span className="provider-badge google" title="Google AI Studio (Direct)">
                🌐 {fmtMs(provider_latencies.google_direct.avg_ms)}
              </span>
            )}
          </div>
        )}
        <button
          className="timing-toggle"
          aria-label={expanded ? 'Collapse timing details' : 'Expand timing details'}
          aria-expanded={expanded}
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>

      {expanded && (
        <div className="timing-details">
          {/* Waterfall chart */}
          <div className="timing-section">
            <h5 className="timing-section-title">Stage Waterfall</h5>
            <div className="timing-waterfall" role="list">
              {orderedStages.map(stage => {
                const data = stages[stage];
                const pct = distribution_pct?.[stage] || 0;
                const barWidth = Math.max((data.ms / maxStageMs) * 100, 2);
                const isBn = stage === bottleneck;
                const hasModels = data.models && Object.keys(data.models).length > 0;
                const isShowingModels = showModels === stage;
                return (
                  <div
                    key={stage}
                    className={`waterfall-row ${isBn ? 'bottleneck' : ''}`}
                    role="listitem"
                  >
                    <div className="waterfall-label">
                      {STAGE_LABELS[stage] || stage}
                      {isBn && <span className="bn-badge">⚡ Bottleneck</span>}
                    </div>
                    <div className="waterfall-bar-track">
                      <div
                        className="waterfall-bar-fill"
                        style={{
                          width: `${barWidth}%`,
                          backgroundColor: STAGE_COLORS[stage] || '#60a5fa',
                        }}
                      />
                    </div>
                    <div className="waterfall-time">{fmtMs(data.ms)}</div>
                    <div className="waterfall-pct">{pct > 0 ? `${pct}%` : ''}</div>
                    {hasModels && (
                      <button
                        className="waterfall-expand-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowModels(isShowingModels ? null : stage);
                        }}
                        aria-expanded={isShowingModels}
                        aria-label={`${isShowingModels ? 'Hide' : 'Show'} model breakdown for ${STAGE_LABELS[stage]}`}
                      >
                        {isShowingModels ? '−' : '+'}
                      </button>
                    )}
                    {isShowingModels && data.models && (
                      <div className="waterfall-models">
                        {Object.entries(data.models)
                          .sort(([,a], [,b]) => b - a)
                          .map(([model, ms]) => {
                            const modelShort = model.split('/').pop() || model;
                            const modelBarWidth = Math.max((ms / data.ms) * 100, 3);
                            const isGoogle = model.startsWith('google/');
                            return (
                              <div className="model-timing-row" key={model}>
                                <span className={`model-timing-name ${isGoogle ? 'google' : 'bayer'}`}>
                                  {isGoogle ? '🌐' : '🏢'} {modelShort}
                                </span>
                                <div className="model-timing-bar-track">
                                  <div
                                    className="model-timing-bar-fill"
                                    style={{ width: `${modelBarWidth}%` }}
                                  />
                                </div>
                                <span className="model-timing-value">{fmtMs(ms)}</span>
                              </div>
                            );
                          })
                        }
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Provider Comparison */}
          {provider_latencies && Object.keys(provider_latencies).length > 0 && (
            <div className="timing-section">
              <h5 className="timing-section-title">Provider Latency Comparison</h5>
              <p className="timing-section-desc">
                Azure-hosted models via Bayer myGenAssist vs Google AI Studio direct API.
              </p>
              <div className="provider-comparison">
                {provider_latencies.bayer_mygenassist && (
                  <div className="provider-card bayer">
                    <div className="provider-header">
                      <span className="provider-icon">🏢</span>
                      <span className="provider-name">Bayer myGenAssist</span>
                      <span className="provider-tag">Azure-Hosted</span>
                    </div>
                    <div className="provider-avg">
                      <span className="provider-avg-value">{fmtMs(provider_latencies.bayer_mygenassist.avg_ms)}</span>
                      <span className="provider-avg-label">avg per call ({provider_latencies.bayer_mygenassist.count} calls)</span>
                    </div>
                    {provider_latencies.bayer_mygenassist.models && (
                      <div className="provider-models">
                        {provider_latencies.bayer_mygenassist.models.map((m, i) => (
                          <div className="provider-model-pill" key={i}>
                            {(m.model.split('/').pop() || m.model)} — {fmtMs(m.ms)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {provider_latencies.google_direct && (
                  <div className="provider-card google">
                    <div className="provider-header">
                      <span className="provider-icon">🌐</span>
                      <span className="provider-name">Google AI Studio</span>
                      <span className="provider-tag">Direct API</span>
                    </div>
                    <div className="provider-avg">
                      <span className="provider-avg-value">{fmtMs(provider_latencies.google_direct.avg_ms)}</span>
                      <span className="provider-avg-label">avg per call ({provider_latencies.google_direct.count} calls)</span>
                    </div>
                    {provider_latencies.google_direct.models && (
                      <div className="provider-models">
                        {provider_latencies.google_direct.models.map((m, i) => (
                          <div className="provider-model-pill" key={i}>
                            {(m.model.split('/').pop() || m.model)} — {fmtMs(m.ms)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Slowest Models */}
          {slowest_models && Object.keys(slowest_models).length > 0 && (
            <div className="timing-section">
              <h5 className="timing-section-title">Slowest Models per Stage</h5>
              <div className="slowest-list">
                {Object.entries(slowest_models).map(([stage, info]) => (
                  <div className="slowest-row" key={stage}>
                    <span className="slowest-stage">{STAGE_LABELS[stage] || stage}</span>
                    <span className="slowest-model">{(info.model?.split('/').pop()) || info.model}</span>
                    <span className="slowest-time">{fmtMs(info.ms)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Redis Cache Statistics */}
          {redisCache && redisCache.total_requests > 0 && (
            <div className="timing-section">
              <h5 className="timing-section-title">🗄️ Redis Cache (Memory Recall)</h5>
              <div className="redis-stats">
                <div className="redis-stat-row">
                  <span className="redis-stat-label">Hit Rate</span>
                  <span className={`redis-stat-value ${redisCache.hit_rate_pct >= 50 ? 'good' : 'low'}`}>
                    {redisCache.hit_rate_pct}%
                  </span>
                </div>
                <div className="redis-stat-row">
                  <span className="redis-stat-label">Hits / Misses</span>
                  <span className="redis-stat-value">
                    {redisCache.hits} / {redisCache.misses}
                  </span>
                </div>
                {redisCache.errors > 0 && (
                  <div className="redis-stat-row">
                    <span className="redis-stat-label">Errors</span>
                    <span className="redis-stat-value error">{redisCache.errors}</span>
                  </div>
                )}
                <div className="redis-stat-row">
                  <span className="redis-stat-label">Total Requests</span>
                  <span className="redis-stat-value">{redisCache.total_requests}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
