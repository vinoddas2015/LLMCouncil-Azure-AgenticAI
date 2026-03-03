import { memo, useMemo } from 'react';
import SciMarkdown from './SciMarkdown';
import './Stage3.css';

/**
 * Convert citation tags like [FDA-L1] in markdown to clickable links
 * using the evidence bundle from the skills module.
 *
 * Multi-tier linkification:
 *   1. Explicit citation tags: [FDA-L1], [CT-2], [PM-3]
 *   2. Identifier-based: PubChem CID, DrugBank DB, NCT, PMID, DOI, ChEMBL, UniProt
 *   3. Known source names: PubMed, DailyMed, ClinicalTrials.gov, etc.
 *   4. Drug + DailyMed patterns
 *   5. Bare URLs
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

  // 2. Identifier-based auto-linkification (scientific databases)
  //    These fire even when the LLM writes prose references instead of tags

  // PubChem CID → https://pubchem.ncbi.nlm.nih.gov/compound/{CID}
  result = result.replace(
    /(?<!\[)(?<!\()PubChem\s+CID\s+(\d+)/gi,
    (match, cid) => `[PubChem CID ${cid}](https://pubchem.ncbi.nlm.nih.gov/compound/${cid})`
  );

  // DrugBank DB → https://go.drugbank.com/drugs/{ID}
  result = result.replace(
    /(?<!\[)(?<!\()DrugBank\s+(DB\d+)/gi,
    (match, id) => `[DrugBank ${id}](https://go.drugbank.com/drugs/${id})`
  );

  // NCT numbers → https://clinicaltrials.gov/study/{NCT}
  result = result.replace(
    /(?<!\[)(?<!\()\b(NCT\d{6,})\b/g,
    (match, nct) => `[${nct}](https://clinicaltrials.gov/study/${nct})`
  );

  // PMID → https://pubmed.ncbi.nlm.nih.gov/{PMID}
  result = result.replace(
    /(?<!\[)(?<!\()PMID[:\s]+(\d+)/gi,
    (match, pmid) => `[PMID ${pmid}](https://pubmed.ncbi.nlm.nih.gov/${pmid}/)`
  );

  // DOI → https://doi.org/{DOI}
  result = result.replace(
    /(?<!\[)(?<!\()(?<!")doi[:\s]+(10\.\d{4,}\/[^\s,;)]+)/gi,
    (match, doi) => `[doi:${doi}](https://doi.org/${doi})`
  );

  // ChEMBL compound → https://www.ebi.ac.uk/chembl/compound_report_card/{ID}
  result = result.replace(
    /(?<!\[)(?<!\()\b(CHEMBL\d+)\b/gi,
    (match, id) => `[${id}](https://www.ebi.ac.uk/chembl/compound_report_card/${id}/)`
  );

  // UniProt → https://www.uniprot.org/uniprot/{ID}
  result = result.replace(
    /(?<!\[)(?<!\()UniProt[:\s]+([A-Z][A-Z0-9]{4,9})\b/g,
    (match, id) => `[UniProt ${id}](https://www.uniprot.org/uniprot/${id})`
  );

  // CAS number (link to Common Chemistry)
  result = result.replace(
    /(?<!\[)(?<!\()CAS[:\s#]+(\d{2,7}-\d{2}-\d)/g,
    (match, cas) => `[CAS ${cas}](https://commonchemistry.cas.org/detail?cas_rn=${cas})`
  );

  // FDA label / prescribing information → DailyMed search
  result = result.replace(
    /(?<!\[)(?<!\()FDA\s+(?:Nubeqa|[\w]+)®?\s*(?:prescribing\s+information|label)/gi,
    (match) => {
      const drugMatch = match.match(/FDA\s+([\w]+)®?/i);
      const drug = drugMatch ? drugMatch[1] : '';
      return `[${match}](https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=${encodeURIComponent(drug)})`;
    }
  );

  // 3. Auto-linkify known reference sources mentioned in prose
  const knownSources = [
    {
      pattern: /(?<!\[)(?<!\()((?:FDA\s+label|prescribing\s+information|drug\s+label|label)\s+)?(?:available\s+(?:at|on|from|via)\s+)?(DailyMed)/gi,
      url: 'https://dailymed.nlm.nih.gov/dailymed/',
      label: 'DailyMed',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(PubMed)(?!\s+CID)/gi,
      url: 'https://pubmed.ncbi.nlm.nih.gov/',
      label: 'PubMed',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(ClinicalTrials\.gov)/gi,
      url: 'https://clinicaltrials.gov/',
      label: 'ClinicalTrials.gov',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(FDA\.gov)/gi,
      url: 'https://www.fda.gov/',
      label: 'FDA.gov',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(DrugBank)(?!\s+DB)/gi,
      url: 'https://go.drugbank.com/',
      label: 'DrugBank',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(Semantic\s+Scholar)/gi,
      url: 'https://www.semanticscholar.org/',
      label: 'Semantic Scholar',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(CrossRef)/gi,
      url: 'https://www.crossref.org/',
      label: 'CrossRef',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(Europe\s+PMC)/gi,
      url: 'https://europepmc.org/',
      label: 'Europe PMC',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(PubChem)(?!\s+CID)/gi,
      url: 'https://pubchem.ncbi.nlm.nih.gov/',
      label: 'PubChem',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(EMA|European\s+Medicines\s+Agency)/gi,
      url: 'https://www.ema.europa.eu/',
      label: 'EMA',
    },
    {
      pattern: /(?<!\[)(?<!\()(?:available\s+(?:at|on|from|via)\s+|(?:see|from|via|on)\s+)?(WHO)/gi,
      url: 'https://www.who.int/',
      label: 'WHO',
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

  // 6. Safety-net: linkify italic article titles in numbered reference lists
  //    Catches entries like: "1. **Trial:** Author et al. *Article Title.* Journal. 2024"
  //    Only fires when the backend enrichment hasn't already created a link.
  result = result.replace(
    /^(\s*\d+\.\s+.+?)(?<!\*)\*(?!\*)([^*\n]{15,})\*(?!\*)(\.?\s*)/gm,
    (match, prefix, title, suffix) => {
      // Skip if already linkified (markdown link around the title)
      if (/\]\(https?:/.test(match)) return match;
      const clean = title.replace(/\.$/, '').trim();
      const url = `https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(clean)}`;
      return `${prefix}[*${title}*](${url})${suffix}`;
    }
  );

  return result;
}

/** Stable extraComponents for SciMarkdown — hoisted outside render */
const CITATION_LINK_COMPONENTS = {
  a: ({ href, children, title, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" title={title} className="citation-link" {...props}>
      {children}
    </a>
  ),
};

const Stage3 = memo(function Stage3({ finalResponse, evidence }) {
  // Memoize the expensive 15+ regex-pass citation linkification
  const citations = evidence?.citations || [];
  const linkedResponse = useMemo(
    () => linkifyCitations(finalResponse?.response, citations),
    [finalResponse?.response, citations]
  );

  if (!finalResponse) {
    return null;
  }

  const isStreaming = !finalResponse.response;
  const benchmark = evidence?.benchmark || {};

  return (
    <div className="stage stage3">
      <h3 className="stage-title">Stage 3: Final Council Answer</h3>
      <div className="final-response">
        <div className="chairman-label">
          Chairman: {finalResponse.model ? (finalResponse.model.split('/')[1] || finalResponse.model) : '…'}
          {citations.length > 0 && (
            <span className="citation-badge" title={`${citations.length} citations from ${evidence.skills_used?.join(', ')}`}>
              📚 {citations.length} citations
            </span>
          )}
        </div>

        {isStreaming ? (
          <div className="stage3-streaming-indicator" role="status" aria-label="Chairman is synthesizing the final answer">
            <div className="streaming-waves" aria-hidden="true">
              <span></span><span></span><span></span><span></span><span></span>
            </div>
            <p className="streaming-text">Chairman is synthesizing the final answer…</p>
            <div className="streaming-progress-bar" aria-hidden="true">
              <div className="streaming-progress-fill"></div>
            </div>
          </div>
        ) : (
          <div className="final-text markdown-content">
            <SciMarkdown extraComponents={CITATION_LINK_COMPONENTS}>
              {linkedResponse}
            </SciMarkdown>
          </div>
        )}

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
});

export default Stage3;
