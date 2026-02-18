import { useState } from 'react';
import './EnhancePrompt.css';

export default function EnhancePrompt({
  originalPrompt,
  enhancedPrompt,
  onKeepOriginal,
  onUseEnhanced,
}) {
  const [editedPrompt, setEditedPrompt] = useState(enhancedPrompt);

  const handleUseEnhanced = () => {
    onUseEnhanced(editedPrompt);
  };

  return (
    <div className="enhance-prompt-card" role="region" aria-label="Enhance Prompt suggestion">
      <div className="enhance-prompt-icon" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="#0d9488" fillOpacity="0.15"/>
          <path d="M12 3c4.97 0 9 4.03 9 9s-4.03 9-9 9-9-4.03-9-9 4.03-9 9-9z" stroke="#14b8a6" strokeWidth="1.5"/>
          <path d="M9.5 16.5l1-4 3 1.5 1-6" stroke="#14b8a6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <circle cx="12" cy="8" r="1" fill="#14b8a6"/>
        </svg>
      </div>

      <div className="enhance-prompt-body">
        <h3 className="enhance-prompt-title">Enhance Prompt</h3>
        <p className="enhance-prompt-intro">
          I understand your prompt <strong>"{originalPrompt.length > 150 ? originalPrompt.slice(0, 150) + '...' : originalPrompt}"</strong> and made an improved version of it. Feel free to edit it and improve to fit your needs.
        </p>

        <div className="enhance-prompt-editor">
          <span className="enhance-edit-icon" aria-hidden="true">✏️</span>
          <textarea
            className="enhance-prompt-textarea"
            value={editedPrompt}
            onChange={(e) => setEditedPrompt(e.target.value)}
            rows={Math.min(8, Math.max(3, Math.ceil(editedPrompt.length / 90)))}
            aria-label="Enhanced prompt (editable)"
          />
        </div>

        <p className="enhance-prompt-note">
          This revision improves clarity and specificity. It also invites a more detailed and informative response.
        </p>

        <div className="enhance-prompt-actions">
          <button
            className="enhance-btn enhance-btn-secondary"
            onClick={onKeepOriginal}
            aria-label="Keep original prompt"
          >
            Keep original prompt
          </button>
          <button
            className="enhance-btn enhance-btn-primary"
            onClick={handleUseEnhanced}
            aria-label="Use improved prompt"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M22 2L11 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Use improved prompt
          </button>
        </div>
      </div>
    </div>
  );
}
