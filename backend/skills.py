"""
Backend Skills Module — Pharma Evidence Retrieval & Benchmarking.

Integrates three external knowledge sources to ground LLM Council
responses with verifiable, citable evidence BEFORE the chairman
synthesises the final answer:

  1. OpenFDA API   — Drug labels, adverse events, recalls
  2. ClinicalTrials.gov API (v2) — Active / completed trials
  3. PubMed / scientific literature — Abstracts via NCBI E-Utilities

Each skill returns a list of Citation objects that the chairman
can embed in the final response.

The `run_evidence_skills` orchestrator fires all three in parallel,
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
MAX_CITATIONS_PER_SKILL = 5   # top-N per source
MAX_TOTAL_CITATIONS = 12      # cap for chairman prompt size


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
# Orchestrator — run all skills in parallel
# ═══════════════════════════════════════════════════════════════════

async def run_evidence_skills(user_query: str) -> Dict[str, Any]:
    """
    Fire all three evidence-retrieval skills in parallel.

    Returns:
        {
            "citations": [Citation.to_dict(), ...],   # sorted by relevance
            "skills_used": ["OpenFDA", "ClinicalTrials.gov", "PubMed"],
            "total_found": int,
            "benchmark": {
                "openfda_ms": float,
                "clinicaltrials_ms": float,
                "pubmed_ms": float,
                "total_ms": float,
            }
        }
    """
    t0 = datetime.now()

    # Fire all three in parallel
    fda_task = asyncio.create_task(_query_openfda(user_query))
    ct_task = asyncio.create_task(_query_clinicaltrials(user_query))
    pm_task = asyncio.create_task(_query_pubmed(user_query))

    t_fda_start = datetime.now()
    fda_citations = await fda_task
    t_fda = (datetime.now() - t_fda_start).total_seconds() * 1000

    t_ct_start = datetime.now()
    ct_citations = await ct_task
    t_ct = (datetime.now() - t_ct_start).total_seconds() * 1000

    t_pm_start = datetime.now()
    pm_citations = await pm_task
    t_pm = (datetime.now() - t_pm_start).total_seconds() * 1000

    # Merge, deduplicate by URL, sort by relevance
    all_citations = fda_citations + ct_citations + pm_citations
    seen_urls = set()
    unique = []
    for c in all_citations:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            unique.append(c)

    unique.sort(key=lambda c: c.relevance, reverse=True)
    top = unique[:MAX_TOTAL_CITATIONS]

    # Re-number IDs sequentially
    for i, c in enumerate(top):
        c.id = f"[{c.id}]"

    total_ms = (datetime.now() - t0).total_seconds() * 1000

    skills_used = []
    if fda_citations:
        skills_used.append("OpenFDA")
    if ct_citations:
        skills_used.append("ClinicalTrials.gov")
    if pm_citations:
        skills_used.append("PubMed")

    logger.info(
        f"[Skills] Found {len(unique)} citations from {len(skills_used)} sources "
        f"in {total_ms:.0f}ms"
    )

    return {
        "citations": [c.to_dict() for c in top],
        "skills_used": skills_used,
        "total_found": len(unique),
        "benchmark": {
            "openfda_ms": round(t_fda, 1),
            "clinicaltrials_ms": round(t_ct, 1),
            "pubmed_ms": round(t_pm, 1),
            "total_ms": round(total_ms, 1),
        },
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
        "include the citation tag (e.g. [FDA-L1], [CT-2], [PM-3]) inline in your text. "
        "At the end of your response, include a numbered REFERENCES section listing "
        "each citation you used with its full URL."
    )
    return "\n".join(lines)
