import SciMarkdown from './SciMarkdown';
import './Stage3.css';

/**
 * Convert citation tags like [FDA-L1] in markdown to clickable links
 * using the evidence bundle from the skills module.
 */
function linkifyCitations(text, citations) {
  if (!text) return text;

  let result = text;

  // 1. Replace explicit citation tags — [FDA-L1], [CT-2], [PM-3]
  if (citations && citations.length) {
    const lookup = {};
    for (const c of citations) {
      lookup[c.id] = c;
    }

    result = result.replace(/\[(FDA-[A-Z]\d+|CT-\d+|PM-\d+|EMA-\d+|WHO-\d+|UP-\d+|CB-\d+|SS-\d+|CR-\d+|EPMC-\d+|WEB-\d+|AX-\d+|PAT-\d+|WIKI-\d+|ORC-\d+)\]/g, (match, tag) => {
      const full = `[${tag}]`;
      const cite = lookup[full];
      if (cite) {
        return `[${tag}](${cite.url} "${cite.source}: ${cite.title}")`;
      }
      return match;
    });
  }

  // 2. Auto-linkify known reference sources mentioned in prose
  //    "available at DailyMed" → clickable link to DailyMed
  const knownSources = [
    {
      pattern: /(?:(?:FDA\s+label|prescribing\s+information|drug\s+label|label)\s+)?(?:available\s+(?:at|on|from|via)\s+)?(DailyMed)/gi,
      url: 'https://dailymed.nlm.nih.gov/dailymed/',
      label: 'DailyMed',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(PubMed)/gi,
      url: 'https://pubmed.ncbi.nlm.nih.gov/',
      label: 'PubMed',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(ClinicalTrials\.gov)/gi,
      url: 'https://clinicaltrials.gov/',
      label: 'ClinicalTrials.gov',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(FDA\.gov)/gi,
      url: 'https://www.fda.gov/',
      label: 'FDA.gov',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(DrugBank)/gi,
      url: 'https://go.drugbank.com/',
      label: 'DrugBank',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(Semantic\s+Scholar)/gi,
      url: 'https://www.semanticscholar.org/',
      label: 'Semantic Scholar',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(CrossRef)/gi,
      url: 'https://www.crossref.org/',
      label: 'CrossRef',
    },
    {
      pattern: /(?:available\s+(?:at|on|from|via)\s+)?(Europe\s+PMC)/gi,
      url: 'https://europepmc.org/',
      label: 'Europe PMC',
    },
  ];

  for (const source of knownSources) {
    result = result.replace(source.pattern, (match, name) => {
      // Don't double-linkify if already inside a markdown link
      return `[${match}](${source.url})`;
    });
  }

  // 3. Auto-linkify drug-specific "FDA label available at DailyMed" patterns
  //    e.g. "Sotorasib (Lumakras): FDA label available at DailyMed"
  result = result.replace(
    /(\w[\w\s]*?\([\w\s]+?\)):\s*FDA\s+label\s+available\s+at\s+\[([^\]]+)\]\(([^)]+)\)/gi,
    (match, drug, linkText, url) => {
      // Extract brand name from parentheses for DailyMed search
      const brandMatch = drug.match(/\(([^)]+)\)/);
      const brand = brandMatch ? brandMatch[1].trim() : drug.trim();
      const dailyMedUrl = `https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=${encodeURIComponent(brand)}`;
      return `${drug}: [FDA label — ${brand}](${dailyMedUrl})`;
    }
  );

  // 4. Catch bare "FDA label available at DailyMed" that wasn't caught above
  //   by linkifying standalone drug+DailyMed patterns
  result = result.replace(
    /(\w[\w\s]*?\([\w\s]+?\)):\s*FDA\s+label\s+available\s+at\s+DailyMed/gi,
    (match, drug) => {
      const brandMatch = drug.match(/\(([^)]+)\)/);
      const brand = brandMatch ? brandMatch[1].trim() : drug.trim();
      const dailyMedUrl = `https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=${encodeURIComponent(brand)}`;
      return `${drug}: [FDA label — ${brand}](${dailyMedUrl})`;
    }
  );

  // 5. Auto-linkify bare URLs that aren't already in markdown links
  result = result.replace(
    /(?<!\]\()(?<!\()(?<!")(https?:\/\/[^\s)<>"]+)/g,
    (url) => `[${url}](${url})`
  );

  return result;
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
