import { useState, useEffect } from 'react';
import { api } from '../api';
import './Settings.css';

export default function Settings({ isOpen, onClose, preferences, onSave }) {
  const [models, setModels] = useState([]);
  const [defaults, setDefaults] = useState({ council_models: [], chairman_model: '' });
  const [selectedCouncil, setSelectedCouncil] = useState([]);
  const [selectedChairman, setSelectedChairman] = useState('');
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      loadModels();
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
  }, [preferences, defaults]);

  const loadModels = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getModels();
      setModels(data.models);
      setDefaults(data.defaults);
      
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
    });
    onClose();
  };

  const handleReset = () => {
    setSelectedCouncil(defaults.council_models);
    setSelectedChairman(defaults.chairman_model);
    setWebSearchEnabled(false);
  };

  if (!isOpen) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>⚙️ Council Settings</h2>
          <button className="close-btn" onClick={onClose}>×</button>
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
                Select which models will participate in Stage 1 (individual responses) and Stage 2 (peer rankings).
                At least 2 models are recommended.
              </p>
              <div className="model-list">
                {models.map(model => (
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
                      <span className="model-name">{model.name}</span>
                      <span className="model-description">{model.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* Web Search toggle moved to input area — see ChatInterface.jsx */}
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
