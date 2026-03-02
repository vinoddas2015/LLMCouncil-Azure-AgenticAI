import { useState, useEffect } from 'react';
import { api } from '../api';
import './Settings.css';

export default function Settings({ isOpen, onClose, preferences, onSave }) {
  const [models, setModels] = useState([]);
  const [defaults, setDefaults] = useState({ council_models: [], chairman_model: '' });
  const [selectedCouncil, setSelectedCouncil] = useState([]);
  const [selectedChairman, setSelectedChairman] = useState('');
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [speedMode, setSpeedMode] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState(null);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadModels();
      loadSyncStatus();
    }
  }, [isOpen]);

  useEffect(() => {
    // Initialize from preferences or defaults
    if (preferences.council_models && preferences.council_models.length > 0) {
      setSelectedCouncil(preferences.council_models);
    } else if (defaults.council_models && defaults.council_models.length > 0) {
      setSelectedCouncil(defaults.council_models);
    }

    if (preferences.chairman_model) {
      setSelectedChairman(preferences.chairman_model);
    } else if (defaults.chairman_model) {
      setSelectedChairman(defaults.chairman_model);
    }

    setWebSearchEnabled(!!preferences.web_search_enabled);
    setSpeedMode(!!preferences.speed_mode);
  }, [preferences, defaults]);

  const loadModels = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getModels();
      setModels(data.models);
      setDefaults(data.defaults);
      setGoogleEnabled(!!data.google_enabled);
      
      // Set initial selections from preferences or defaults
      if (preferences.council_models && preferences.council_models.length > 0) {
        setSelectedCouncil(preferences.council_models);
      } else {
        setSelectedCouncil(data.defaults.council_models);
      }
      
      if (preferences.chairman_model) {
        setSelectedChairman(preferences.chairman_model);
      } else {
        setSelectedChairman(data.defaults.chairman_model);
      }
    } catch (err) {
      setError('Failed to load models');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCouncilToggle = (modelId) => {
    setSelectedCouncil(prev => {
      if (prev.includes(modelId)) {
        return prev.filter(id => id !== modelId);
      } else {
        return [...prev, modelId];
      }
    });
  };

  const handleChairmanSelect = (modelId) => {
    setSelectedChairman(modelId);
  };

  const handleSave = () => {
    onSave({
      council_models: selectedCouncil,
      chairman_model: selectedChairman,
      web_search_enabled: webSearchEnabled,
      speed_mode: speedMode,
    });
    onClose();
  };

  const handleReset = () => {
    setSelectedCouncil(defaults.council_models);
    setSelectedChairman(defaults.chairman_model);
    setWebSearchEnabled(false);
    setSpeedMode(false);
  };

  const loadSyncStatus = async () => {
    try {
      const status = await api.getSyncStatus();
      setSyncStatus(status);
    } catch (e) {
      console.error('Failed to load sync status:', e);
    }
  };

  const handleSyncNow = async () => {
    setSyncing(true);
    try {
      await api.syncModels();
      await loadModels();
      await loadSyncStatus();
    } catch (e) {
      console.error('Model sync failed:', e);
    } finally {
      setSyncing(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="settings-overlay" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2 id="settings-title">⚙️ Council Settings</h2>
          <button className="close-btn" onClick={onClose} aria-label="Close settings">×</button>
        </div>

        {loading ? (
          <div className="settings-loading">Loading models...</div>
        ) : error ? (
          <div className="settings-error">{error}</div>
        ) : (
          <div className="settings-content">
            <div className="settings-section">
              <h3>🏛️ Council Members</h3>
              <p className="settings-description">
                Select models to deliberate on your queries. Latest versions are auto-synced.
                {syncStatus?.last_sync && (
                  <span className="sync-info"> Last sync: {new Date(syncStatus.last_sync).toLocaleTimeString()}
                    · {syncStatus.model_count} models
                  </span>
                )}
              </p>

              {/* Bayer myGenAssist models */}
              <h4 className="provider-heading">
                <span className="provider-badge bayer">Bayer</span> myGenAssist
              </h4>
              <div className="model-list">
                {models.filter(m => m.provider !== 'google').map(model => (
                  <label key={model.id} className="model-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedCouncil.includes(model.id)}
                      onChange={() => handleCouncilToggle(model.id)}
                    />
                    <span className="model-info">
                      <span className="model-name">
                        {model.name}
                        {model.family && model.family !== 'other' && (
                          <span className="model-family-tag">{model.family}</span>
                        )}
                      </span>
                      <span className="model-description">{model.description}</span>
                    </span>
                  </label>
                ))}
              </div>

              {/* Google AI Studio models */}
              {googleEnabled && models.some(m => m.provider === 'google') && (
                <>
                  <h4 className="provider-heading">
                    <span className="provider-badge google">Google</span> AI Studio — Direct
                  </h4>
                  <div className="model-list">
                    {models.filter(m => m.provider === 'google').map(model => (
                      <label key={model.id} className="model-checkbox">
                        <input
                          type="checkbox"
                          checked={selectedCouncil.includes(model.id)}
                          onChange={() => handleCouncilToggle(model.id)}
                        />
                        <span className="model-info">
                          <span className="model-name">{model.name}</span>
                          <span className="model-description">{model.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </>
              )}

              {selectedCouncil.length < 2 && (
                <div className="settings-warning">
                  ⚠️ Select at least 2 council members for meaningful peer rankings.
                </div>
              )}
            </div>

            <div className="settings-section">
              <h3>👑 Chairman</h3>
              <p className="settings-description">
                Select the model that will synthesize the final response in Stage 3.
              </p>
              <div className="model-list">
                {models.map(model => (
                  <label key={model.id} className="model-radio">
                    <input
                      type="radio"
                      name="chairman"
                      checked={selectedChairman === model.id}
                      onChange={() => handleChairmanSelect(model.id)}
                    />
                    <span className="model-info">
                      <span className="model-name">
                        {model.name}
                        {model.provider === 'google' && <span className="provider-tag google">Google</span>}
                        {model.family && model.family !== 'other' && (
                          <span className="model-family-tag">{model.family}</span>
                        )}
                      </span>
                      <span className="model-description">{model.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* Web Search toggle moved to input area — see ChatInterface.jsx */}

            <div className="settings-section">
              <h3>⚡ Speed Mode</h3>
              <p className="settings-description">
                Accelerate the council pipeline by streamlining evaluations. Stage 2 uses a simplified ranking prompt (no claim analysis) and reduces model timeouts. Doubting Thomas self-reflection always runs to preserve quality assurance.
              </p>
              <div className="web-search-toggle">
                <div className="toggle-info">
                  <span className="toggle-label">Turbo Pipeline</span>
                  <span className="toggle-description">
                    {speedMode ? '⚡ Speed mode ON — faster responses, streamlined evaluations' : 'Standard pipeline — full rubric evaluation + claim analysis'}
                  </span>
                </div>
                <label className="toggle-switch" aria-label="Toggle speed mode">
                  <input
                    type="checkbox"
                    checked={speedMode}
                    onChange={(e) => setSpeedMode(e.target.checked)}
                  />
                  <span className="toggle-slider"></span>
                </label>
              </div>
            </div>

            <div className="settings-section">
              <h3>🤖 A2A Agent Cards</h3>
              <p className="settings-description">
                Download the full Agent-to-Agent protocol card bundle for all {13} council agents.
                Includes the main council card and individual cards for each specialist agent (BEAT ID: BEAT04059418).
              </p>
              <div className="settings-btn-row">
                <button
                  className="download-agent-cards-btn"
                  onClick={async () => {
                    try { await api.downloadAgentCards(); }
                    catch (e) { console.error('Agent card download failed:', e); }
                  }}
                  aria-label="Download A2A agent cards as JSON"
                >
                  📥 Download Agent Cards
                </button>
                <button
                  className="sync-models-btn"
                  onClick={handleSyncNow}
                  disabled={syncing}
                  aria-label="Sync models from MyGenAssist API"
                >
                  {syncing ? '⏳ Syncing...' : '🔄 Sync Models Now'}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="settings-footer">
          <button className="reset-btn" onClick={handleReset}>
            Reset to Defaults
          </button>
          <div className="footer-actions">
            <button className="cancel-btn" onClick={onClose}>Cancel</button>
            <button 
              className="save-btn" 
              onClick={handleSave}
              disabled={selectedCouncil.length === 0 || !selectedChairman}
            >
              Save Preferences
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
