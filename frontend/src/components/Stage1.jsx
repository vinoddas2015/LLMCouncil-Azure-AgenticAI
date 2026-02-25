import { useState, memo, useMemo } from 'react';
import SciMarkdown from './SciMarkdown';
import './Stage1.css';

/** Extract short model name from "provider/model" */
const shortName = (model) => model.split('/')[1] || model;

const Stage1 = memo(function Stage1({ responses }) {
  const [activeTab, setActiveTab] = useState(0);

  // Memoize tab labels so they don't recalculate on every render
  const tabLabels = useMemo(
    () => responses?.map((r) => shortName(r.model)) ?? [],
    [responses]
  );

  if (!responses || responses.length === 0) {
    return null;
  }

  return (
    <div className="stage stage1">
      <h3 className="stage-title">Stage 1: Individual Responses</h3>

      <div className="tabs">
        {tabLabels.map((label, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="model-name">{responses[activeTab].model}</div>
        <div className="response-text markdown-content">
          <SciMarkdown>{responses[activeTab].response}</SciMarkdown>
        </div>
      </div>
    </div>
  );
});

export default Stage1;
