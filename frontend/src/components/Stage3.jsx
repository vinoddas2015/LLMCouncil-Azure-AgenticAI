import SciMarkdown from './SciMarkdown';
import './Stage3.css';

/**
 * Convert citation tags like [FDA-L1] in markdown to clickable links
 * using the evidence bundle from the skills module.
 */
function linkifyCitations(text, citations) {
  if (!citations || !citations.length || !text) return text;

  // Build lookup: "[FDA-L1]" → { url, title, source }
  const lookup = {};
  for (const c of citations) {
    lookup[c.id] = c;
  }

  // Replace citation tags with markdown links
  return text.replace(/\[(FDA-[A-Z]\d+|CT-\d+|PM-\d+)\]/g, (match, tag) => {
    const full = `[${tag}]`;
    const cite = lookup[full];
    if (cite) {
      return `[${tag}](${cite.url} "${cite.source}: ${cite.title}")`;
    }
    return match;
  });
}

export default function Stage3({ finalResponse, evidence }) {
  if (!finalResponse) {
    return null;
  }

  const citations = evidence?.citations || [];
  const benchmark = evidence?.benchmark || {};
  const linkedResponse = linkifyCitations(finalResponse.response, citations);

  return (
    <div className="stage stage3">
      <h3 className="stage-title">Stage 3: Final Council Answer</h3>
      <div className="final-response">
        <div className="chairman-label">
          Chairman: {finalResponse.model.split('/')[1] || finalResponse.model}
          {citations.length > 0 && (
            <span className="citation-badge" title={`${citations.length} citations from ${evidence.skills_used?.join(', ')}`}>
              📚 {citations.length} citations
            </span>
          )}
        </div>
        <div className="final-text markdown-content">
          <SciMarkdown
            extraComponents={{
              a: ({ href, children, title, ...props }) => (
                <a href={href} target="_blank" rel="noopener noreferrer" title={title} className="citation-link" {...props}>
                  {children}
                </a>
              ),
            }}
          >
            {linkedResponse}
          </SciMarkdown>
        </div>

        {/* Evidence sources panel */}
        {citations.length > 0 && (
          <div className="evidence-panel">
            <div className="evidence-header">
              <span className="evidence-title">📋 Evidence Sources</span>
              <span className="evidence-meta">
                {evidence.skills_used?.join(' · ')}
                {benchmark.total_ms && ` · ${Math.round(benchmark.total_ms)}ms`}
              </span>
            </div>
            <div className="evidence-list">
              {citations.map((c, i) => (
                <a
                  key={i}
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="evidence-item"
                  title={c.snippet}
                >
                  <span className="evidence-tag">{c.id}</span>
                  <span className="evidence-source">{c.source}</span>
                  <span className="evidence-item-title">{c.title}</span>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
