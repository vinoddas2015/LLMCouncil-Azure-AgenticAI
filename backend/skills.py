"""
Backend Skills Module — Pharma Evidence Retrieval & Benchmarking.

Integrates external knowledge sources to ground LLM Council
responses with verifiable, citable evidence BEFORE the chairman
synthesises the final answer.

  CORE SKILLS (always active):
  1. OpenFDA API            — Drug labels, adverse events, recalls
  2. ClinicalTrials.gov API — Active / completed trials
  3. PubMed / NCBI          — Abstracts via E-Utilities
  4. EMA                    — European Medicines Agency product info
  5. WHO ATC/DDD            — Drug classification / ATC codes
  6. UniProt                — Protein / drug-target data (human)
  7. ChEMBL                 — Compound bioactivity & clinical phase

  WEB SEARCH SKILLS (active when web_search_enabled=True):
  8.  Semantic Scholar       — AI-curated scientific papers + abstracts
  9.  CrossRef / DOI         — Journal article metadata & DOI links
  10. Europe PMC             — Full-text open access literature
  11. DuckDuckGo Scientific  — General web search filtered for .gov / .edu / journals

Each skill returns a list of Citation objects that the chairman
can embed in the final response.

The `run_evidence_skills` orchestrator fires all sources in parallel,
deduplicates, ranks by relevance, and returns a consolidated
evidence bundle.
"""

import asyncio
import httpx
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger("skills")

# ── Timeouts & Limits ────────────────────────────────────────────
SKILL_TIMEOUT = 12.0          # seconds per API call
WEB_SKILL_TIMEOUT = 15.0      # slightly longer for web crawling
MAX_CITATIONS_PER_SKILL = 5   # top-N per source
MAX_TOTAL_CITATIONS = 12      # cap when web search is OFF
MAX_TOTAL_CITATIONS_WEB = 30  # cap when web search is ON (expanded for broader sources)


# ═══════════════════════════════════════════════════════════════════
# Citation data model
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Citation:
    """A single citable evidence item."""
    id: str                   # short key like [FDA-1], [CT-3], [PM-2]
    source: str               # "OpenFDA" | "ClinicalTrials.gov" | "PubMed"
    title: str
    url: str
    snippet: str              # ≤200-char summary
    relevance: float = 0.0    # 0-1 relevance score
    date: str = ""            # publication / update date

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════
# Skill 1: OpenFDA
# https://api.fda.gov/drug/label.json
# https://api.fda.gov/drug/event.json
# ═══════════════════════════════════════════════════════════════════

async def _query_openfda(query: str) -> List[Citation]:
    """Search OpenFDA drug labels + adverse events for evidence."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    search_term = "+AND+".join(keywords[:3])

    endpoints = [
        (
            f"https://api.fda.gov/drug/label.json?search={search_term}&limit=3",
            "label",
        ),
        (
            f"https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:{keywords[0]}&limit=3",
            "event",
        ),
    ]

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        for url, etype in endpoints:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                results = data.get("results", [])
                for i, item in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                    cid = f"FDA-{etype[0].upper()}{i+1}"
                    if etype == "label":
                        brand = (item.get("openfda", {}).get("brand_name", ["Unknown"]))[0] if isinstance(item.get("openfda", {}).get("brand_name"), list) else "Drug Label"
                        snippet_src = item.get("indications_and_usage", [""])[0] if isinstance(item.get("indications_and_usage"), list) else str(item.get("indications_and_usage", ""))
                        snippet = snippet_src[:200].strip()
                        spl_id = item.get("id", "")
                        link = f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query={brand.replace(' ', '+')}"
                        citations.append(Citation(
                            id=cid, source="OpenFDA",
                            title=f"{brand} — FDA Drug Label",
                            url=link, snippet=snippet,
                            relevance=0.7 - i * 0.1,
                        ))
                    else:
                        reactions = item.get("patient", {}).get("reaction", [])
                        reaction_names = ", ".join(r.get("reactionmeddrapt", "") for r in reactions[:4])
                        drug_name = keywords[0]
                        snippet = f"Adverse event report: {reaction_names}"[:200]
                        safety_id = item.get("safetyreportid", "unknown")
                        link = f"https://api.fda.gov/drug/event.json?search=safetyreportid:{safety_id}"
                        citations.append(Citation(
                            id=cid, source="OpenFDA",
                            title=f"{drug_name} — FDA Adverse Event ({safety_id})",
                            url=link, snippet=snippet,
                            relevance=0.6 - i * 0.1,
                        ))
            except Exception as e:
                logger.warning(f"[OpenFDA] {etype} query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 2: ClinicalTrials.gov (v2 API)
# ═══════════════════════════════════════════════════════════════════

async def _query_clinicaltrials(query: str) -> List[Citation]:
    """Search ClinicalTrials.gov for relevant studies."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_expr = " AND ".join(keywords[:4])
    url = (
        f"https://clinicaltrials.gov/api/v2/studies"
        f"?query.term={search_expr}"
        f"&pageSize={MAX_CITATIONS_PER_SKILL}"
        f"&format=json"
        f"&fields=NCTId,BriefTitle,OverallStatus,StartDate,Condition,InterventionName"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[ClinicalTrials] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            studies = data.get("studies", [])
            for i, study in enumerate(studies[:MAX_CITATIONS_PER_SKILL]):
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status_mod = proto.get("statusModule", {})
                nct_id = ident.get("nctId", f"NCT-{i}")
                title = ident.get("briefTitle", "Clinical Trial")
                status = status_mod.get("overallStatus", "Unknown")
                start_date = status_mod.get("startDateStruct", {}).get("date", "")

                conditions = proto.get("conditionsModule", {}).get("conditions", [])
                cond_str = ", ".join(conditions[:3]) if conditions else ""
                snippet = f"Status: {status}. Conditions: {cond_str}"[:200]

                citations.append(Citation(
                    id=f"CT-{i+1}",
                    source="ClinicalTrials.gov",
                    title=f"{title} ({nct_id})",
                    url=f"https://clinicaltrials.gov/study/{nct_id}",
                    snippet=snippet,
                    relevance=0.75 - i * 0.08,
                    date=start_date,
                ))
        except Exception as e:
            logger.warning(f"[ClinicalTrials] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 3: PubMed / NCBI E-Utilities
# ═══════════════════════════════════════════════════════════════════

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

async def _query_pubmed(query: str) -> List[Citation]:
    """Search PubMed for relevant abstracts."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = "+".join(keywords[:4])

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            # Step 1: Search for PMIDs
            search_resp = await client.get(PUBMED_SEARCH, params={
                "db": "pubmed",
                "term": search_term,
                "retmax": MAX_CITATIONS_PER_SKILL,
                "retmode": "json",
                "sort": "relevance",
            })
            if search_resp.status_code != 200:
                return citations
            search_data = search_resp.json()
            pmids = search_data.get("esearchresult", {}).get("idlist", [])
            if not pmids:
                return citations

            # Step 2: Get summaries
            summary_resp = await client.get(PUBMED_SUMMARY, params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json",
            })
            if summary_resp.status_code != 200:
                return citations
            summary_data = summary_resp.json()
            results = summary_data.get("result", {})

            for i, pmid in enumerate(pmids[:MAX_CITATIONS_PER_SKILL]):
                article = results.get(pmid, {})
                if not isinstance(article, dict):
                    continue
                title = article.get("title", "PubMed Article")
                source_journal = article.get("source", "")
                pub_date = article.get("pubdate", "")
                authors = article.get("authors", [])
                first_author = authors[0].get("name", "") if authors else ""
                snippet = f"{first_author} et al. {source_journal} ({pub_date})"[:200]

                citations.append(Citation(
                    id=f"PM-{i+1}",
                    source="PubMed",
                    title=title[:120],
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    snippet=snippet,
                    relevance=0.8 - i * 0.08,
                    date=pub_date,
                ))
        except Exception as e:
            logger.warning(f"[PubMed] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Keyword extraction helpers
# ═══════════════════════════════════════════════════════════════════

_DRUG_PATTERN = re.compile(
    r'\b(?:aspirin|ibuprofen|metformin|atorvastatin|omeprazole|lisinopril|'
    r'amlodipine|simvastatin|losartan|gabapentin|sertraline|montelukast|'
    r'levothyroxine|pantoprazole|rosuvastatin|escitalopram|bupropion|'
    r'fluoxetine|trazodone|prednisone|amoxicillin|azithromycin|doxycycline|'
    r'cephalexin|ciprofloxacin|metronidazole|clindamycin|'
    r'pembrolizumab|nivolumab|trastuzumab|bevacizumab|rituximab|'
    r'adalimumab|infliximab|etanercept|ustekinumab|secukinumab|'
    r'semaglutide|tirzepatide|ozempic|wegovy|mounjaro|'
    r'ribociclib|palbociclib|abemaciclib|olaparib|osimertinib|'
    r'encorafenib|vemurafenib|dabrafenib|trametinib|cobimetinib|'
    r'imatinib|dasatinib|nilotinib|ponatinib|bosutinib|'
    r'sorafenib|lenvatinib|cabozantinib|sunitinib|pazopanib|'
    r'erlotinib|gefitinib|afatinib|lapatinib|neratinib)\b',
    re.IGNORECASE,
)

_STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'shall',
    'should', 'may', 'might', 'must', 'can', 'could', 'of', 'in', 'to',
    'for', 'with', 'on', 'at', 'from', 'by', 'about', 'as', 'into',
    'through', 'during', 'before', 'after', 'above', 'below', 'between',
    'and', 'but', 'or', 'nor', 'not', 'so', 'yet', 'both', 'either',
    'neither', 'each', 'every', 'all', 'any', 'few', 'more', 'most',
    'other', 'some', 'such', 'no', 'only', 'own', 'same', 'than', 'too',
    'very', 'just', 'also', 'what', 'which', 'who', 'whom', 'this',
    'that', 'these', 'those', 'i', 'me', 'my', 'we', 'our', 'you', 'your',
    'he', 'him', 'his', 'she', 'her', 'it', 'its', 'they', 'them', 'their',
    'how', 'when', 'where', 'why', 'tell', 'explain', 'describe', 'please',
}


def _extract_drug_keywords(text: str) -> List[str]:
    """Extract drug-related keywords from query text."""
    drugs = _DRUG_PATTERN.findall(text)
    # Also grab capitalized multi-word terms
    words = re.findall(r'\b[A-Za-z]{3,}\b', text)
    medical = [w for w in words if w.lower() not in _STOP_WORDS]
    # Drugs first, then general medical terms
    seen = set()
    result = []
    for w in drugs + medical:
        low = w.lower()
        if low not in seen:
            seen.add(low)
            result.append(w)
    return result[:6]


def _extract_medical_keywords(text: str) -> List[str]:
    """Extract medical / scientific keywords from query text."""
    words = re.findall(r'\b[A-Za-z]{3,}\b', text)
    medical = [w for w in words if w.lower() not in _STOP_WORDS]
    # Deduplicate preserving order
    seen = set()
    result = []
    for w in medical:
        low = w.lower()
        if low not in seen:
            seen.add(low)
            result.append(w)
    return result[:8]


# ═══════════════════════════════════════════════════════════════════
# Skill 4: EMA (European Medicines Agency)
# https://www.ema.europa.eu — medicine search
# ═══════════════════════════════════════════════════════════════════

async def _query_ema(query: str) -> List[Citation]:
    """Search EMA for European drug authorisation data."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    search_term = "+".join(keywords[:3])
    url = (
        f"https://www.ema.europa.eu/en/search?"
        f"search_api_fulltext={search_term}&f%5B0%5D=content_type%3Amedicine"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url, headers={"Accept": "text/html"})
            if resp.status_code != 200:
                logger.warning(f"[EMA] HTTP {resp.status_code}")
                return citations

            # Parse basic search results from HTML — look for medicine links
            text = resp.text
            # Find medicine page links: /en/medicines/human/EPAR/<name>
            import re as _re
            medicine_links = _re.findall(
                r'href="(/en/medicines/human/EPAR/[^"]+)"[^>]*>([^<]+)', text
            )

            for i, (path, name) in enumerate(medicine_links[:MAX_CITATIONS_PER_SKILL]):
                full_url = f"https://www.ema.europa.eu{path}"
                citations.append(Citation(
                    id=f"EMA-{i+1}",
                    source="EMA",
                    title=f"{name.strip()} — EMA Product Info",
                    url=full_url,
                    snippet=f"European Medicines Agency: {name.strip()}",
                    relevance=0.7 - i * 0.1,
                ))
        except Exception as e:
            logger.warning(f"[EMA] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 5: WHO Essential Medicines & ATC/DDD
# ═══════════════════════════════════════════════════════════════════

async def _query_who(query: str) -> List[Citation]:
    """Search WHO ATC/DDD index for drug classification data."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    search_term = keywords[0]
    url = (
        f"https://www.whocc.no/atc_ddd_index/"
        f"?code=&showdescription=no&name={search_term}"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return citations

            text = resp.text
            import re as _re
            # Parse ATC code rows from the WHO index page
            rows = _re.findall(
                r'<a href="(\?code=[A-Z0-9]+[^"]*)"[^>]*>([^<]+)</a>\s*</td>\s*<td[^>]*>([^<]*)',
                text
            )

            for i, (path, atc_code, name) in enumerate(rows[:MAX_CITATIONS_PER_SKILL]):
                full_url = f"https://www.whocc.no/atc_ddd_index/{path}"
                clean_name = name.strip() or atc_code.strip()
                citations.append(Citation(
                    id=f"WHO-{i+1}",
                    source="WHO ATC",
                    title=f"{clean_name} — ATC {atc_code.strip()}",
                    url=full_url,
                    snippet=f"WHO ATC Classification: {atc_code.strip()} {clean_name}",
                    relevance=0.65 - i * 0.1,
                ))
        except Exception as e:
            logger.warning(f"[WHO] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 6: UniProt (protein / target data)
# ═══════════════════════════════════════════════════════════════════

async def _query_uniprot(query: str) -> List[Citation]:
    """Search UniProt for protein target information."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = "+".join(keywords[:3])
    url = (
        f"https://rest.uniprot.org/uniprotkb/search"
        f"?query={search_term}+AND+organism_id:9606"
        f"&format=json&size={MAX_CITATIONS_PER_SKILL}"
        f"&fields=accession,protein_name,gene_names,organism_name"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url, headers={"Accept": "application/json"})
            if resp.status_code != 200:
                logger.warning(f"[UniProt] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            results = data.get("results", [])
            for i, entry in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                accession = entry.get("primaryAccession", "")
                prot_desc = entry.get("proteinDescription", {})
                rec_name = prot_desc.get("recommendedName", {})
                full_name = rec_name.get("fullName", {}).get("value", "Unknown Protein")
                genes = entry.get("genes", [])
                gene_name = genes[0].get("geneName", {}).get("value", "") if genes else ""

                snippet = f"Protein: {full_name}"
                if gene_name:
                    snippet += f" (Gene: {gene_name})"

                citations.append(Citation(
                    id=f"UP-{i+1}",
                    source="UniProt",
                    title=f"{full_name} [{accession}]",
                    url=f"https://www.uniprot.org/uniprot/{accession}",
                    snippet=snippet[:200],
                    relevance=0.65 - i * 0.08,
                ))
        except Exception as e:
            logger.warning(f"[UniProt] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 7: ChEMBL (bioactivity / compound data)
# ═══════════════════════════════════════════════════════════════════

async def _query_chembl(query: str) -> List[Citation]:
    """Search ChEMBL for compound bioactivity data."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    search_term = keywords[0]
    url = (
        f"https://www.ebi.ac.uk/chembl/api/data/molecule/search.json"
        f"?q={search_term}&limit={MAX_CITATIONS_PER_SKILL}"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[ChEMBL] HTTP {resp.status_code}")
                return citations

            data = resp.json()
            molecules = data.get("molecules", [])
            for i, mol in enumerate(molecules[:MAX_CITATIONS_PER_SKILL]):
                chembl_id = mol.get("molecule_chembl_id", "")
                pref_name = mol.get("pref_name", "") or chembl_id
                mol_type = mol.get("molecule_type", "Unknown")
                max_phase = mol.get("max_phase", "")
                snippet = f"{mol_type}. Max clinical phase: {max_phase}"

                citations.append(Citation(
                    id=f"CB-{i+1}",
                    source="ChEMBL",
                    title=f"{pref_name} ({chembl_id})",
                    url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
                    snippet=snippet[:200],
                    relevance=0.6 - i * 0.08,
                ))
        except Exception as e:
            logger.warning(f"[ChEMBL] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 8: Semantic Scholar
# https://api.semanticscholar.org — AI-curated scientific literature
# ═══════════════════════════════════════════════════════════════════

async def _query_semantic_scholar(query: str) -> List[Citation]:
    """Search Semantic Scholar for highly-cited scientific papers."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:5])
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={search_term}"
        f"&limit={MAX_CITATIONS_PER_SKILL}"
        f"&fields=title,url,abstract,year,citationCount,journal,authors,externalIds"
    )

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[SemanticScholar] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            papers = data.get("data", [])
            for i, paper in enumerate(papers[:MAX_CITATIONS_PER_SKILL]):
                title = paper.get("title", "Scientific Paper")
                paper_url = paper.get("url", "")
                abstract = paper.get("abstract", "") or ""
                year = paper.get("year", "")
                cite_count = paper.get("citationCount", 0)
                journal_info = paper.get("journal", {}) or {}
                journal_name = journal_info.get("name", "") if isinstance(journal_info, dict) else ""
                authors = paper.get("authors", []) or []
                first_author = authors[0].get("name", "") if authors else ""

                # Build informative snippet
                snippet_parts = []
                if first_author:
                    snippet_parts.append(f"{first_author} et al.")
                if journal_name:
                    snippet_parts.append(journal_name)
                if year:
                    snippet_parts.append(f"({year})")
                if cite_count:
                    snippet_parts.append(f"Cited {cite_count}x")
                if abstract:
                    snippet_parts.append(f"— {abstract[:120]}")
                snippet = " ".join(snippet_parts)[:200]

                # Boost relevance by citation count
                base_relevance = 0.85 - i * 0.06
                if cite_count and cite_count > 100:
                    base_relevance = min(base_relevance + 0.1, 0.95)

                citations.append(Citation(
                    id=f"SS-{i+1}",
                    source="Semantic Scholar",
                    title=title[:150],
                    url=paper_url or f"https://www.semanticscholar.org/search?q={search_term}",
                    snippet=snippet,
                    relevance=base_relevance,
                    date=str(year),
                ))
        except Exception as e:
            logger.warning(f"[SemanticScholar] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 9: CrossRef (DOI / journal metadata)
# https://api.crossref.org
# ═══════════════════════════════════════════════════════════════════

async def _query_crossref(query: str) -> List[Citation]:
    """Search CrossRef for journal articles and DOI metadata."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = "+".join(keywords[:5])
    url = (
        f"https://api.crossref.org/works"
        f"?query={search_term}"
        f"&rows={MAX_CITATIONS_PER_SKILL}"
        f"&sort=relevance"
        f"&select=DOI,title,author,published-print,container-title,abstract,URL"
    )

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                url,
                headers={"User-Agent": "LLMCouncilMGA/1.0 (mailto:research@llmcouncil.dev)"},
            )
            if resp.status_code != 200:
                logger.warning(f"[CrossRef] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            for i, item in enumerate(items[:MAX_CITATIONS_PER_SKILL]):
                doi = item.get("DOI", "")
                titles = item.get("title", ["Unknown"])
                title = titles[0] if titles else "CrossRef Article"
                authors_raw = item.get("author", [])
                first_author = ""
                if authors_raw:
                    a = authors_raw[0]
                    first_author = f"{a.get('family', '')} {a.get('given', '')}".strip()
                journal = item.get("container-title", [""])
                journal_name = journal[0] if journal else ""
                pub_date = item.get("published-print", {}).get("date-parts", [[]])
                year = str(pub_date[0][0]) if pub_date and pub_date[0] else ""
                abstract_raw = item.get("abstract", "") or ""
                # Strip JATS XML tags from abstract
                abstract = re.sub(r'<[^>]+>', '', abstract_raw)[:150]

                snippet_parts = []
                if first_author:
                    snippet_parts.append(f"{first_author} et al.")
                if journal_name:
                    snippet_parts.append(journal_name)
                if year:
                    snippet_parts.append(f"({year})")
                if abstract:
                    snippet_parts.append(f"— {abstract}")
                snippet = " ".join(snippet_parts)[:200]

                article_url = item.get("URL", f"https://doi.org/{doi}")

                citations.append(Citation(
                    id=f"CR-{i+1}",
                    source="CrossRef",
                    title=title[:150],
                    url=article_url,
                    snippet=snippet,
                    relevance=0.78 - i * 0.06,
                    date=year,
                ))
        except Exception as e:
            logger.warning(f"[CrossRef] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 10: Europe PMC (open-access full-text search)
# https://www.ebi.ac.uk/europepmc
# ═══════════════════════════════════════════════════════════════════

async def _query_europe_pmc(query: str) -> List[Citation]:
    """Search Europe PMC for open-access biomedical literature."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:5])
    url = (
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={search_term}"
        f"&resultType=core"
        f"&pageSize={MAX_CITATIONS_PER_SKILL}"
        f"&format=json"
        f"&sort=RELEVANCE"
    )

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[EuropePMC] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            results_list = data.get("resultList", {}).get("result", [])
            for i, article in enumerate(results_list[:MAX_CITATIONS_PER_SKILL]):
                pmcid = article.get("pmcid", "")
                pmid = article.get("pmid", "")
                title = article.get("title", "Europe PMC Article")
                journal_title = article.get("journalTitle", "")
                pub_year = article.get("pubYear", "")
                author_string = article.get("authorString", "")
                abstract_text = (article.get("abstractText", "") or "")[:150]
                cited_by = article.get("citedByCount", 0)
                is_open_access = article.get("isOpenAccess", "N") == "Y"

                # Build URL — prefer PMC full text, fallback to PubMed
                if pmcid:
                    article_url = f"https://europepmc.org/article/PMC/{pmcid}"
                elif pmid:
                    article_url = f"https://europepmc.org/article/MED/{pmid}"
                else:
                    article_url = f"https://europepmc.org/search?query={search_term}"

                snippet_parts = []
                if author_string:
                    snippet_parts.append(author_string[:60])
                if journal_title:
                    snippet_parts.append(journal_title)
                if pub_year:
                    snippet_parts.append(f"({pub_year})")
                if is_open_access:
                    snippet_parts.append("[Open Access]")
                if cited_by:
                    snippet_parts.append(f"Cited {cited_by}x")
                if abstract_text:
                    snippet_parts.append(f"— {abstract_text}")
                snippet = " ".join(snippet_parts)[:200]

                base_relevance = 0.82 - i * 0.06
                if cited_by and cited_by > 50:
                    base_relevance = min(base_relevance + 0.08, 0.92)
                if is_open_access:
                    base_relevance = min(base_relevance + 0.03, 0.95)

                citations.append(Citation(
                    id=f"EPMC-{i+1}",
                    source="Europe PMC",
                    title=title[:150],
                    url=article_url,
                    snippet=snippet,
                    relevance=base_relevance,
                    date=str(pub_year),
                ))
        except Exception as e:
            logger.warning(f"[EuropePMC] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 11: DuckDuckGo Scientific Web Search
# Filtered for authoritative domains (.gov, .edu, journals)
# ═══════════════════════════════════════════════════════════════════

# Authoritative scientific domains to prioritise / whitelist
_SCIENCE_DOMAINS = {
    "nih.gov", "fda.gov", "who.int", "cdc.gov", "ema.europa.eu",
    "nature.com", "sciencedirect.com", "thelancet.com", "nejm.org",
    "bmj.com", "springer.com", "wiley.com", "cell.com",
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
    "mayoclinic.org", "medlineplus.gov", "drugs.com",
    "drugbank.com", "rxlist.com", "medscape.com",
    "jamanetwork.com", "cochranelibrary.com",
    "uptodate.com", "clinicalkey.com",
    ".edu",  # all educational institutions
    ".gov",  # all government sites
}


def _is_authoritative(url: str) -> bool:
    """Check if a URL belongs to an authoritative scientific domain."""
    url_lower = url.lower()
    for domain in _SCIENCE_DOMAINS:
        if domain in url_lower:
            return True
    return False


async def _query_duckduckgo_science(query: str) -> List[Citation]:
    """
    Search DuckDuckGo for scientific / pharma web content.

    Uses DuckDuckGo Lite (HTML) to extract results without JS.
    Prioritises authoritative scientific domains.
    """
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    # Add scientific qualifiers to improve result quality
    search_term = " ".join(keywords[:5]) + " site:nih.gov OR site:who.int OR site:fda.gov OR pubmed OR clinical trial"

    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.post(
                url,
                data={"q": search_term, "kl": "us-en"},
                headers=headers,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"[DuckDuckGo] HTTP {resp.status_code}")
                return citations

            html = resp.text

            # Parse result links from DuckDuckGo Lite HTML
            link_pattern = re.compile(
                r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>',
                re.IGNORECASE | re.DOTALL,
            )
            # Snippet pattern: <td class="result-snippet">...</td>
            snippet_pattern = re.compile(
                r'<td[^>]*class="result-snippet"[^>]*>(.+?)</td>',
                re.IGNORECASE | re.DOTALL,
            )

            links = link_pattern.findall(html)
            snippets_raw = snippet_pattern.findall(html)

            for i, (link_url, title_raw) in enumerate(links[:MAX_CITATIONS_PER_SKILL * 2]):
                if len(citations) >= MAX_CITATIONS_PER_SKILL:
                    break

                # Skip non-http links
                if not link_url.startswith("http"):
                    continue

                # Skip DuckDuckGo internal links
                if "duckduckgo.com" in link_url:
                    continue

                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                snippet_html = snippets_raw[i] if i < len(snippets_raw) else ""
                snippet = re.sub(r'<[^>]+>', '', snippet_html).strip()[:200]

                is_auth = _is_authoritative(link_url)
                base_relevance = 0.75 - len(citations) * 0.08
                if is_auth:
                    base_relevance = min(base_relevance + 0.12, 0.90)

                src_label = "Web (.gov/.edu)" if is_auth else "Web Search"

                citations.append(Citation(
                    id=f"WEB-{len(citations)+1}",
                    source=src_label,
                    title=title[:150] or "Web Result",
                    url=link_url,
                    snippet=snippet or f"Scientific web result for: {' '.join(keywords[:3])}",
                    relevance=base_relevance,
                ))
        except Exception as e:
            logger.warning(f"[DuckDuckGo] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 12: arXiv (scientific preprints)
# https://export.arxiv.org/api/query
# ═══════════════════════════════════════════════════════════════════

async def _query_arxiv(query: str) -> List[Citation]:
    """Search arXiv for scientific preprints (physics, biology, CS, math)."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = "+AND+".join(f"all:{kw}" for kw in keywords[:4])
    url = (
        f"https://export.arxiv.org/api/query"
        f"?search_query={search_term}"
        f"&start=0&max_results={MAX_CITATIONS_PER_SKILL}"
        f"&sortBy=relevance&sortOrder=descending"
    )

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[arXiv] HTTP {resp.status_code}")
                return citations
            text = resp.text
            # Parse Atom XML entries
            entries = re.findall(
                r'<entry>(.*?)</entry>', text, re.DOTALL
            )
            for i, entry in enumerate(entries[:MAX_CITATIONS_PER_SKILL]):
                title_m = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
                title = re.sub(r'\s+', ' ', title_m.group(1).strip()) if title_m else "arXiv Paper"
                link_m = re.search(r'<id>(.*?)</id>', entry)
                paper_url = link_m.group(1).strip() if link_m else ""
                summary_m = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
                abstract = re.sub(r'\s+', ' ', summary_m.group(1).strip())[:150] if summary_m else ""
                published_m = re.search(r'<published>(.*?)</published>', entry)
                pub_date = published_m.group(1)[:10] if published_m else ""
                authors = re.findall(r'<name>(.*?)</name>', entry)
                first_author = authors[0] if authors else ""

                snippet_parts = []
                if first_author:
                    snippet_parts.append(f"{first_author} et al.")
                if pub_date:
                    snippet_parts.append(f"({pub_date[:4]})")
                if abstract:
                    snippet_parts.append(f"— {abstract}")
                snippet = " ".join(snippet_parts)[:200]

                citations.append(Citation(
                    id=f"AX-{i+1}",
                    source="arXiv",
                    title=title[:150],
                    url=paper_url or f"https://arxiv.org/search/?query={'+'.join(keywords[:3])}",
                    snippet=snippet,
                    relevance=0.80 - i * 0.06,
                    date=pub_date,
                ))
        except Exception as e:
            logger.warning(f"[arXiv] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 13: Google Patents (via Lens.org)
# https://api.lens.org — patent search
# ═══════════════════════════════════════════════════════════════════

async def _query_patents(query: str) -> List[Citation]:
    """Search for relevant patents via Google Patents public interface."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = "+".join(keywords[:4])
    url = f"https://patents.google.com/xhr/query?url=q%3D{search_term}&exp=&num={MAX_CITATIONS_PER_SKILL}"

    # Fallback: scrape Google Patents HTML search results
    html_url = f"https://patents.google.com/?q={search_term}&oq={search_term}"

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                html_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"[Patents] HTTP {resp.status_code}")
                return citations

            html = resp.text
            # Parse patent result links from HTML
            patent_links = re.findall(
                r'data-result="(\w+)"[^>]*>.*?class="[^"]*result-title[^"]*"[^>]*>([^<]+)',
                html, re.DOTALL
            )
            if not patent_links:
                # Alternative pattern
                patent_links = re.findall(
                    r'href="/patent/([A-Z0-9]+)"[^>]*>\s*<span[^>]*>([^<]+)',
                    html, re.DOTALL
                )

            for i, (patent_id, title_raw) in enumerate(patent_links[:MAX_CITATIONS_PER_SKILL]):
                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                patent_url = f"https://patents.google.com/patent/{patent_id}"

                citations.append(Citation(
                    id=f"PAT-{i+1}",
                    source="Google Patents",
                    title=title[:150] or f"Patent {patent_id}",
                    url=patent_url,
                    snippet=f"Patent {patent_id}: {title[:180]}",
                    relevance=0.70 - i * 0.08,
                ))
        except Exception as e:
            logger.warning(f"[Patents] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 14: Wikipedia / Wikidata
# https://en.wikipedia.org/api/rest_v1/
# ═══════════════════════════════════════════════════════════════════

async def _query_wikipedia(query: str) -> List[Citation]:
    """Search Wikipedia for general knowledge and entity context."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:5])
    url = (
        f"https://en.wikipedia.org/w/api.php"
        f"?action=query&list=search&srsearch={search_term}"
        f"&srlimit={MAX_CITATIONS_PER_SKILL}&format=json"
        f"&srprop=snippet|titlesnippet|timestamp"
    )

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"[Wikipedia] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            for i, article in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                title = article.get("title", "Wikipedia Article")
                snippet_html = article.get("snippet", "")
                snippet = re.sub(r'<[^>]+>', '', snippet_html)[:200]
                timestamp = article.get("timestamp", "")[:10]
                page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

                citations.append(Citation(
                    id=f"WIKI-{i+1}",
                    source="Wikipedia",
                    title=title[:150],
                    url=page_url,
                    snippet=snippet,
                    relevance=0.65 - i * 0.06,
                    date=timestamp,
                ))
        except Exception as e:
            logger.warning(f"[Wikipedia] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 15: ORCID (researcher profiles)
# https://pub.orcid.org/v3.0/
# ═══════════════════════════════════════════════════════════════════

async def _query_orcid(query: str) -> List[Citation]:
    """Search ORCID for researcher profiles related to the query."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:4])
    url = (
        f"https://pub.orcid.org/v3.0/expanded-search/"
        f"?q={search_term}&start=0&rows={MAX_CITATIONS_PER_SKILL}"
    )

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                url,
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning(f"[ORCID] HTTP {resp.status_code}")
                return citations
            data = resp.json()
            results = data.get("expanded-result", []) or []
            for i, researcher in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                orcid_id = researcher.get("orcid-id", "")
                given = researcher.get("given-names", "")
                family = researcher.get("family-names", "")
                name = f"{given} {family}".strip() or orcid_id
                institutions = researcher.get("institution-name", [])
                inst_str = institutions[0] if institutions else ""

                snippet = f"Researcher: {name}"
                if inst_str:
                    snippet += f" ({inst_str})"

                citations.append(Citation(
                    id=f"ORC-{i+1}",
                    source="ORCID",
                    title=f"{name} — ORCID Profile",
                    url=f"https://orcid.org/{orcid_id}",
                    snippet=snippet[:200],
                    relevance=0.55 - i * 0.06,
                ))
        except Exception as e:
            logger.warning(f"[ORCID] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Orchestrator — run all skills in parallel
# ═══════════════════════════════════════════════════════════════════

async def run_evidence_skills(
    user_query: str,
    web_search_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Fire evidence-retrieval skills in parallel.

    Core skills (always fire):
      1. OpenFDA      2. ClinicalTrials.gov  3. PubMed
      4. EMA          5. WHO ATC             6. UniProt
      7. ChEMBL

    Web search skills (only when web_search_enabled=True):
      8. Semantic Scholar  9. CrossRef  10. Europe PMC
      11. DuckDuckGo Scientific

    Returns:
        {
            "citations": [Citation.to_dict(), ...],  # sorted by relevance
            "skills_used": [str, ...],
            "total_found": int,
            "web_search_active": bool,
            "benchmark": { ... }
        }
    """
    t0 = datetime.now()

    # ── Core skills (always fire) ──────────────────────────────────
    tasks = {
        "OpenFDA":              asyncio.create_task(_query_openfda(user_query)),
        "ClinicalTrials.gov":   asyncio.create_task(_query_clinicaltrials(user_query)),
        "PubMed":               asyncio.create_task(_query_pubmed(user_query)),
        "EMA":                  asyncio.create_task(_query_ema(user_query)),
        "WHO ATC":              asyncio.create_task(_query_who(user_query)),
        "UniProt":              asyncio.create_task(_query_uniprot(user_query)),
        "ChEMBL":               asyncio.create_task(_query_chembl(user_query)),
    }

    # ── Web search skills (only when toggled ON) ───────────────────
    if web_search_enabled:
        logger.info("[Skills] Web search ENABLED — adding Semantic Scholar, CrossRef, Europe PMC, DuckDuckGo, arXiv, Patents, Wikipedia, ORCID")
        tasks["Semantic Scholar"] = asyncio.create_task(_query_semantic_scholar(user_query))
        tasks["CrossRef"]         = asyncio.create_task(_query_crossref(user_query))
        tasks["Europe PMC"]       = asyncio.create_task(_query_europe_pmc(user_query))
        tasks["DuckDuckGo Sci"]   = asyncio.create_task(_query_duckduckgo_science(user_query))
        tasks["arXiv"]            = asyncio.create_task(_query_arxiv(user_query))
        tasks["Google Patents"]   = asyncio.create_task(_query_patents(user_query))
        tasks["Wikipedia"]        = asyncio.create_task(_query_wikipedia(user_query))
        tasks["ORCID"]            = asyncio.create_task(_query_orcid(user_query))

    # Await all tasks and collect benchmarks
    results = {}
    benchmarks = {}
    for source_name, task in tasks.items():
        t_start = datetime.now()
        try:
            citations = await task
        except Exception as e:
            logger.warning(f"[{source_name}] Task failed: {e}")
            citations = []
        elapsed = (datetime.now() - t_start).total_seconds() * 1000
        results[source_name] = citations
        bench_key = source_name.lower().replace(".", "").replace(" ", "_") + "_ms"
        benchmarks[bench_key] = round(elapsed, 1)

    # Merge, deduplicate by URL, sort by relevance
    all_citations = []
    for c_list in results.values():
        all_citations.extend(c_list)

    seen_urls = set()
    unique = []
    for c in all_citations:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            unique.append(c)

    unique.sort(key=lambda c: c.relevance, reverse=True)
    cap = MAX_TOTAL_CITATIONS_WEB if web_search_enabled else MAX_TOTAL_CITATIONS
    top = unique[:cap]

    # Re-number IDs sequentially
    for i, c in enumerate(top):
        c.id = f"[{c.id}]"

    total_ms = (datetime.now() - t0).total_seconds() * 1000
    benchmarks["total_ms"] = round(total_ms, 1)

    skills_used = [name for name, cites in results.items() if cites]

    logger.info(
        f"[Skills] Found {len(unique)} citations from {len(skills_used)} sources "
        f"({', '.join(skills_used)}) in {total_ms:.0f}ms"
        f"{' [WEB SEARCH ON]' if web_search_enabled else ''}"
    )

    return {
        "citations": [c.to_dict() for c in top],
        "skills_used": skills_used,
        "total_found": len(unique),
        "web_search_active": web_search_enabled,
        "benchmark": benchmarks,
    }


def format_citations_for_prompt(evidence: Dict[str, Any]) -> str:
    """Format citation evidence into a text block for the chairman prompt."""
    citations = evidence.get("citations", [])
    if not citations:
        return ""

    lines = ["EVIDENCE FROM VERIFIED SOURCES (use these citations in your response):"]
    lines.append("=" * 60)
    for c in citations:
        lines.append(
            f'{c["id"]} {c["source"]} — {c["title"]}\n'
            f'   URL: {c["url"]}\n'
            f'   Summary: {c["snippet"]}'
        )
    lines.append("=" * 60)
    lines.append(
        "CITATION INSTRUCTIONS: When referencing any fact from the above evidence, "
        "include the citation tag (e.g. [FDA-L1], [CT-2], [PM-3], [EMA-1], [WHO-1], [UP-1], [CB-1], "
        "[SS-1], [CR-1], [EPMC-1], [WEB-1], [AX-1], [PAT-1], [WIKI-1], [ORC-1]) inline in your text. "
        "At the end of your response, include a numbered REFERENCES section listing "
        "each citation you used with its full URL."
    )
    return "\n".join(lines)
