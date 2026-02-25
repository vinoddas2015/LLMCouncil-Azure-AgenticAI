import { useState, memo, useMemo } from 'react';
import SciMarkdown from './SciMarkdown';
import GroundingScore from './GroundingScore';
import './Stage2.css';

/** Extract short model name from "provider/model" */
const shortName = (model) => model.split('/')[1] || model;

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;

  let result = text;
  // Replace each "Response X" with the actual model name
  Object.entries(labelToModel).forEach(([label, model]) => {
    const modelShortName = shortName(model);
    result = result.replace(new RegExp(label, 'g'), `**${modelShortName}**`);
  });
  return result;
}

const Stage2 = memo(function Stage2({ rankings, labelToModel, aggregateRankings, groundingScores }) {
  const [activeTab, setActiveTab] = useState(0);

  // Memoize tab labels
  const tabLabels = useMemo(
    () => rankings?.map((r) => shortName(r.model)) ?? [],
    [rankings]
  );

  // Memoize the expensive regex-based de-anonymization per active tab
  const deAnonymizedText = useMemo(
    () => rankings?.[activeTab]
      ? deAnonymizeText(rankings[activeTab].ranking, labelToModel)
      : '',
    [rankings, activeTab, labelToModel]
  );

  if (!rankings || rankings.length === 0) {
    return null;
  }

  return (
    <div className="stage stage2">
      <h3 className="stage-title">Stage 2: Peer Rankings</h3>

      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses (anonymized as Response A, B, C, etc.) and provided rankings.
        Below, model names are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

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
        <div className="ranking-model">
          {rankings[activeTab].model}
        </div>
        <div className="ranking-content markdown-content">
          <SciMarkdown>
            {deAnonymizedText}
          </SciMarkdown>
        </div>

        {rankings[activeTab].parsed_ranking &&
         rankings[activeTab].parsed_ranking.length > 0 && (
          <div className="parsed-ranking">
            <strong>Extracted Ranking:</strong>
            <ol>
              {rankings[activeTab].parsed_ranking.map((label, i) => (
                <li key={i}>
                  {labelToModel && labelToModel[label]
                    ? shortName(labelToModel[label])
                    : label}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      {aggregateRankings && aggregateRankings.length > 0 && (
        <div className="aggregate-rankings">
          <h4>Aggregate Rankings (Street Cred)</h4>
          <p className="stage-description">
            Combined results across all peer evaluations (lower score is better):
          </p>
          <div className="aggregate-list">
            {aggregateRankings.map((agg, index) => (
              <div key={index} className="aggregate-item">
                <span className="rank-position">#{index + 1}</span>
                <span className="rank-model">
                  {shortName(agg.model)}
                </span>
                <span className="rank-score">
                  Avg: {agg.average_rank.toFixed(2)}
                </span>
                <span className="rank-count">
                  ({agg.rankings_count} votes)
                </span>
              </div>
            ))}
          </div>

          {/* Grounding Score — circular confidence bubble */}
          <GroundingScore groundingScores={groundingScores} />
        </div>
      )}
    </div>
  );
});

export default Stage2;
