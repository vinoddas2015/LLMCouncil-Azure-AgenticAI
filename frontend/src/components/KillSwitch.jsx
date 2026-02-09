import { useState } from 'react';
import { api } from '../api';
import './KillSwitch.css';

/**
 * Kill Switch component — provides the end user with an emergency stop button
 * that aborts the current in-flight council session or triggers a global halt.
 *
 * Props:
 *   sessionId  — current active session ID (null if idle)
 *   isLoading  — whether a council session is in progress
 *   onKilled   — callback when kill succeeds
 */
export default function KillSwitch({ sessionId, isLoading, onKilled }) {
  const [killing, setKilling] = useState(false);
  const [showConfirmHalt, setShowConfirmHalt] = useState(false);
  const [haltActive, setHaltActive] = useState(false);

  const handleKillSession = async () => {
    if (!sessionId) return;
    setKilling(true);
    try {
      await api.killSession(sessionId);
      onKilled?.('session');
    } catch (err) {
      console.error('Kill session failed:', err);
    } finally {
      setKilling(false);
    }
  };

  const handleGlobalHalt = async () => {
    setShowConfirmHalt(false);
    setKilling(true);
    try {
      await api.globalHalt('Emergency halt triggered by user');
      setHaltActive(true);
      onKilled?.('global');
    } catch (err) {
      console.error('Global halt failed:', err);
    } finally {
      setKilling(false);
    }
  };

  const handleReleaseHalt = async () => {
    try {
      await api.releaseHalt();
      setHaltActive(false);
    } catch (err) {
      console.error('Release halt failed:', err);
    }
  };

  return (
    <div className="kill-switch-container">
      {/* Primary Kill Button — visible when a session is running */}
      {isLoading && sessionId && (
        <button
          className="kill-switch-btn kill-session"
          onClick={handleKillSession}
          disabled={killing}
          title="Stop the current council session immediately"
        >
          {killing ? (
            <span className="kill-switch-spinner" />
          ) : (
            <>
              <span className="kill-icon">⏹</span>
              <span className="kill-label">Stop</span>
            </>
          )}
        </button>
      )}

      {/* Emergency Global Halt */}
      {!haltActive && (
        <button
          className="kill-switch-btn kill-halt"
          onClick={() => setShowConfirmHalt(true)}
          disabled={killing}
          title="Emergency: halt ALL sessions system-wide"
        >
          <span className="kill-icon">⚠</span>
        </button>
      )}

      {/* Halt active indicator + release */}
      {haltActive && (
        <div className="halt-active-bar">
          <span className="halt-pulse" />
          <span>SYSTEM HALTED</span>
          <button className="release-btn" onClick={handleReleaseHalt}>
            Resume
          </button>
        </div>
      )}

      {/* Confirmation modal for global halt */}
      {showConfirmHalt && (
        <div className="kill-confirm-overlay" onClick={() => setShowConfirmHalt(false)}>
          <div className="kill-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <h3>⚠ Emergency Global Halt</h3>
            <p>
              This will <strong>immediately abort ALL active council sessions</strong> and
              block new ones until you release the halt.
            </p>
            <p>Use only in emergencies (e.g. runaway costs, incorrect model behavior).</p>
            <div className="kill-confirm-actions">
              <button className="cancel-btn" onClick={() => setShowConfirmHalt(false)}>
                Cancel
              </button>
              <button className="confirm-halt-btn" onClick={handleGlobalHalt}>
                Confirm Halt
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
