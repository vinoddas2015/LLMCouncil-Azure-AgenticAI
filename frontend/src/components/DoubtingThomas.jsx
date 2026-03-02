import { useState, memo, useMemo } from 'react';
import './DoubtingThomas.css';

/**
 * Doubting Thomas — Adversarial Self-Reflection Visualization
 *
 * Displays the results of the 2-step adversarial review that
 * runs after Stage 3. Shows per-criterion severity badges,
 * fix instructions, and optionally the full critique text.
 *
 * Reference: arXiv:2602.03837 §Adversarial Reviewer
 */

const SEVERITY_RANK = { PASS: 0, MINOR: 1, MAJOR: 2, CRITICAL: 3 };

/** Map severity to a CSS class */
const severityClass = (sev) => (sev || 'PASS').toLowerCase();

/** Summarise DT result into headline + badge */
function useDTSummary(data) {
  return useMemo(() => {
    if (!data) return { headline: '', badge: '', badgeClass: '' };

    if (data.status === 'running') {
      return { headline: 'Running adversarial self-reflection…', badge: 'Running', badgeClass: 'running' };
    }
    if (data.skipped) {
      return { headline: 'Skipped — response too short for meaningful self-reflection', badge: 'Skipped', badgeClass: 'skipped' };
    }
    if (data.error) {
      return { headline: `Error: ${data.error}`, badge: 'Error', badgeClass: 'skipped' };
    }

    const defects = data.defect_count ?? 0;

    if (data.fix_applied) {
      return {
        headline: `${defects} defect${defects !== 1 ? 's' : ''} found and auto-corrected`,
        badge: 'Fixed',
        badgeClass: 'fixed',
      };
    }

    if (defects === 0) {
      return { headline: 'No defects found — response passed all 5 criteria', badge: 'Pass', badgeClass: 'pass' };
    }

    // Has defects but no fix applied (shouldn't normally happen)
    const maxSev = highestSeverity(data.criteria);
    return {
      headline: `${defects} defect${defects !== 1 ? 's' : ''} detected`,
      badge: maxSev,
      badgeClass: severityClass(maxSev),
    };
  }, [data]);
}

/** Find the highest severity across criteria */
function highestSeverity(criteria) {
  if (!criteria || criteria.length === 0) return 'PASS';
  let max = 'PASS';
  for (const c of criteria) {
    const sev = (c.severity || 'PASS').toUpperCase();
    if ((SEVERITY_RANK[sev] ?? 0) > (SEVERITY_RANK[max] ?? 0)) {
      max = sev;
    }
  }
  return max;
}

/** Determine card variant class */
function cardVariant(data) {
  if (!data || data.skipped || data.status === 'running') return '';
  const defects = data.defect_count ?? 0;
  if (defects === 0 && !data.fix_applied) return 'dt-clean';
  const maxSev = highestSeverity(data.criteria);
  if (maxSev === 'CRITICAL') return 'dt-critical';
  return '';
}

const DoubtingThomas = memo(function DoubtingThomas({ data }) {
  const [expanded, setExpanded] = useState(false);
  const [showCritique, setShowCritique] = useState(false);
  const { headline, badge, badgeClass } = useDTSummary(data);

  if (!data) return null;

  // Running state — spinner only
  if (data.status === 'running') {
    return (
      <div className="dt-card" role="status" aria-label="Doubting Thomas running">
        <div className="dt-running">
          <div className="spinner" />
          <span>Adversarial self-reflection in progress…</span>
        </div>
      </div>
    );
  }

  const hasCriteria = data.criteria && data.criteria.length > 0;
  const hasFixInstructions = data.fix_instructions && data.fix_instructions.length > 0;
  const hasCritique = !!data.critique;
  const canExpand = hasCriteria || hasFixInstructions || hasCritique;

  return (
    <div className={`dt-card ${cardVariant(data)}`}>
      <div
        className="dt-header"
        onClick={() => canExpand && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && canExpand) {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        role="button"
        tabIndex={canExpand ? 0 : -1}
        aria-expanded={canExpand ? expanded : undefined}
        aria-label="Doubting Thomas — adversarial self-reflection results"
      >
        <span className="dt-icon" aria-hidden="true">🧐</span>
        <div className="dt-summary">
          <p className="dt-title">Doubting Thomas</p>
          <p className="dt-subtitle">{headline}</p>
        </div>
        <span className={`dt-badge ${badgeClass}`}>{badge}</span>
        {canExpand && (
          <span className={`dt-chevron ${expanded ? 'open' : ''}`} aria-hidden="true">▶</span>
        )}
      </div>

      {expanded && (
        <div className="dt-body">
          {/* Per-criterion breakdown */}
          {hasCriteria && (
            <div className="dt-criteria-grid" role="list" aria-label="Review criteria">
              {data.criteria.map((c, i) => (
                <div className="dt-criterion" key={i} role="listitem">
                  <span className="dt-criterion-name" title={c.verdict || c.name}>
                    {c.name}
                  </span>
                  <span className={`dt-criterion-severity ${severityClass(c.severity)}`}>
                    {(c.severity || 'PASS').toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Fix instructions */}
          {hasFixInstructions && (
            <div className="dt-fix-section">
              <p className="dt-fix-header">Fix Instructions</p>
              <ul className="dt-fix-list" role="list">
                {data.fix_instructions.map((instr, i) => (
                  <li className="dt-fix-item" key={i} role="listitem">{instr}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Fix applied banner */}
          {data.fix_applied && (
            <div className="dt-fix-applied" role="status">
              ✅ Stage 3 response was automatically revised to address the defects above.
            </div>
          )}

          {/* Expandable critique text */}
          {hasCritique && (
            <>
              <button
                className="dt-critique-toggle"
                onClick={(e) => { e.stopPropagation(); setShowCritique(!showCritique); }}
                aria-expanded={showCritique}
                aria-controls="dt-critique-content"
              >
                {showCritique ? '▾' : '▸'} Full Critique
              </button>
              {showCritique && (
                <div className="dt-critique-text" id="dt-critique-content">
                  {data.critique}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
});

export default DoubtingThomas;
