import { useState } from 'react';
import { api } from '../api';
import './LearnUnlearn.css';

/**
 * Inline learn/unlearn control rendered after a council deliberation.
 * Shows memory-gate status (auto-learned / pending) and lets
 * the user confirm, override, or unlearn the decision.
 */
export default function LearnUnlearn({ learningData, onDecisionApplied }) {
  const [busy, setBusy] = useState(false);
  const [appliedAction, setAppliedAction] = useState(null);

  if (!learningData) return null;

  const {
    action,       // "auto_learned" | "pending_user_decision"
    grounding_score,
    auto_learn_threshold,
    message,
    learned,      // { semantic, episodic, procedural } — IDs, or null
  } = learningData;

  const pct = Math.round((grounding_score ?? 0) * 100);
  const threshPct = Math.round((auto_learn_threshold ?? 0.75) * 100);
  const isAutoLearned = action === 'auto_learned';

  const handleAction = async (decision) => {
    setBusy(true);
    try {
      // Apply decision to each non-null memory tier
      for (const [tier, id] of Object.entries(learned || {})) {
        if (id) {
          await api.applyMemoryDecision(decision, tier, id);
        }
      }
      setAppliedAction(decision);
      onDecisionApplied?.(decision);
    } catch (e) {
      console.error('Memory decision failed:', e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`learn-unlearn-bar ${isAutoLearned ? 'auto-learned' : 'pending'}`}>
      <div className="lu-status">
        <span className="lu-icon">{isAutoLearned ? '🧠' : '❓'}</span>
        <span className="lu-message">{message}</span>
      </div>

      <div className="lu-details">
        <span className="lu-score">
          Grounding: <strong>{pct}%</strong> (threshold: {threshPct}%)
        </span>
        {learned?.semantic && <span className="lu-badge semantic">Semantic</span>}
        {learned?.episodic && <span className="lu-badge episodic">Episodic</span>}
        {learned?.procedural && <span className="lu-badge procedural">Procedural</span>}
      </div>

      {!appliedAction && (
        <div className="lu-actions">
          {isAutoLearned ? (
            <>
              <button
                className="lu-btn confirm"
                onClick={() => handleAction('learn')}
                disabled={busy}
              >
                ✅ Keep Learned
              </button>
              <button
                className="lu-btn reject"
                onClick={() => handleAction('unlearn')}
                disabled={busy}
              >
                🚫 Unlearn
              </button>
            </>
          ) : (
            <>
              <button
                className="lu-btn confirm"
                onClick={() => handleAction('learn')}
                disabled={busy}
              >
                ✅ Learn This
              </button>
              <button
                className="lu-btn reject"
                onClick={() => handleAction('unlearn')}
                disabled={busy}
              >
                🚫 Don't Learn
              </button>
            </>
          )}
        </div>
      )}

      {appliedAction && (
        <div className="lu-result">
          {appliedAction === 'learn' ? '✅ Learned into memory' : '🚫 Unlearned — won\'t influence future councils'}
        </div>
      )}
    </div>
  );
}
