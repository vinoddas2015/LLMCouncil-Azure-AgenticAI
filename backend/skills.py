"""
Backend Skills Module — Pharma Evidence Retrieval & Benchmarking.

Integrates external knowledge sources to ground LLM Council
responses with verifiable, citable evidence BEFORE the chairman
synthesises the final answer.

  CORE SKILLS (always active):
  1.  OpenFDA API            — Drug labels, adverse events, recalls
  2.  ClinicalTrials.gov API — Active / completed trials
  3.  PubMed / NCBI          — Abstracts via E-Utilities
  4.  EMA                    — European Medicines Agency product info
  5.  WHO ATC/DDD            — Drug classification / ATC codes
  6.  UniProt                — Protein / drug-target data (human)
  7.  ChEMBL                 — Compound bioactivity & clinical phase
  8.  KEGG                   — Pathways, drugs, compounds, DDIs
  9.  Reactome               — Biological pathways & reactions
  10. RxNorm (NIH/NLM)       — Drug concept identifiers & interactions
  11. STRING-DB              — Protein-protein interaction networks
  12. Hubble (Bayer)         — Bayer internal enterprise search

  WEB SEARCH SKILLS (active when web_search_enabled=True):
  13. Semantic Scholar       — AI-curated scientific papers + abstracts
  14. CrossRef / DOI         — Journal article metadata & DOI links
  15. Europe PMC             — Full-text open access literature
  16. DuckDuckGo Scientific  — General web search filtered for .gov / .edu / journals
  17. arXiv                  — Scientific preprints
  18. Google Patents         — Patent search via Google Patents
  19. Wikipedia / Wikidata   — General knowledge & entity context
  20. ORCID                  — Researcher profile search
  21. OpenAlex               — 243M+ scholarly works (CC0 public domain)
  22. Unpaywall              — Open access status & URLs for DOIs
  23. Elsevier / Scopus      — Scopus abstracts & ScienceDirect metadata
  24. bioRxiv                — Biology preprints (Cold Spring Harbor)
  25. medRxiv                — Health sciences preprints (Cold Spring Harbor)
  26. OECD.AI                — AI policy & regulation observatory
  27. Endpoints News         — Biopharma industry news (RSS)
  28. Doctor Penguin         — Healthcare + AI newsletter (Substack)
  21. Unpaywall              — Open access status & URLs for DOIs
  22. Elsevier / Scopus      — Scopus abstracts & ScienceDirect metadata

Each skill returns a list of Citation objects that the chairman
can embed in the final response.

The `run_evidence_skills` orchestrator fires all sources in parallel,
deduplicates, ranks by relevance, and returns a consolidated
evidence bundle.
"""

import asyncio
import httpx
import logging
import os
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from .reranker import rerank_citations

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
# Skill 8: KEGG (Kyoto Encyclopedia of Genes and Genomes)
# https://rest.kegg.jp — Pathways, drugs, compounds, DDIs
# ═══════════════════════════════════════════════════════════════════

async def _query_kegg(query: str) -> List[Citation]:
    """Search KEGG for drug, compound, pathway, and DDI data."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    search_term = keywords[0]

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            # Search KEGG drug database
            resp = await client.get(f"https://rest.kegg.jp/find/drug/{search_term}")
            if resp.status_code == 200 and resp.text.strip():
                lines = resp.text.strip().split("\n")
                for i, line in enumerate(lines[:MAX_CITATIONS_PER_SKILL]):
                    parts = line.split("\t", 1)
                    if len(parts) < 2:
                        continue
                    kegg_id = parts[0].strip()  # e.g. "dr:D00109"
                    name = parts[1].strip()
                    drug_code = kegg_id.replace("dr:", "")
                    citations.append(Citation(
                        id=f"KG-{i+1}",
                        source="KEGG",
                        title=f"{name} ({drug_code})",
                        url=f"https://www.kegg.jp/entry/{drug_code}",
                        snippet=f"KEGG Drug: {name}",
                        relevance=0.70 - i * 0.08,
                    ))
        except Exception as e:
            logger.warning(f"[KEGG] Drug search failed: {e}")

        # Also search compound database
        try:
            if len(keywords) > 1:
                resp2 = await client.get(f"https://rest.kegg.jp/find/compound/{keywords[0]}")
                if resp2.status_code == 200 and resp2.text.strip():
                    lines = resp2.text.strip().split("\n")
                    for i, line in enumerate(lines[:2]):  # limit compound hits
                        parts = line.split("\t", 1)
                        if len(parts) < 2:
                            continue
                        cpd_id = parts[0].strip().replace("cpd:", "")
                        name = parts[1].strip()
                        citations.append(Citation(
                            id=f"KG-C{i+1}",
                            source="KEGG",
                            title=f"{name} ({cpd_id}) — Compound",
                            url=f"https://www.kegg.jp/entry/{cpd_id}",
                            snippet=f"KEGG Compound: {name}",
                            relevance=0.60 - i * 0.1,
                        ))
        except Exception as e:
            logger.warning(f"[KEGG] Compound search failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 9: Reactome (Biological Pathways)
# https://reactome.org/ContentService — Pathways, reactions, diseases
# ═══════════════════════════════════════════════════════════════════

async def _query_reactome(query: str) -> List[Citation]:
    """Search Reactome for biological pathways and reactions."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:4])

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                "https://reactome.org/ContentService/search/query",
                params={
                    "query": search_term,
                    "species": "Homo sapiens",
                    "types": "Pathway,Reaction,Disease",
                    "cluster": "true",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning(f"[Reactome] HTTP {resp.status_code}")
                return citations

            data = resp.json()
            results = data.get("results", [])
            count = 0
            for group in results:
                entries = group.get("entries", [])
                for entry in entries:
                    if count >= MAX_CITATIONS_PER_SKILL:
                        break
                    stable_id = entry.get("stId", "")
                    name = entry.get("name", "Reactome Entry")
                    species = entry.get("species", [""])[0] if entry.get("species") else ""
                    summary = entry.get("summation", [""])[0] if entry.get("summation") else ""
                    exact_type = entry.get("exactType", "")

                    snippet = f"{exact_type}: {summary[:160]}" if summary else f"Reactome {exact_type}: {name}"

                    citations.append(Citation(
                        id=f"RC-{count+1}",
                        source="Reactome",
                        title=f"{name} ({stable_id})",
                        url=f"https://reactome.org/content/detail/{stable_id}",
                        snippet=snippet[:200],
                        relevance=0.72 - count * 0.08,
                    ))
                    count += 1
                if count >= MAX_CITATIONS_PER_SKILL:
                    break
        except Exception as e:
            logger.warning(f"[Reactome] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 10: RxNorm (NIH/NLM)
# https://rxnav.nlm.nih.gov/REST — Drug concepts & interactions
# ═══════════════════════════════════════════════════════════════════

async def _query_rxnorm(query: str) -> List[Citation]:
    """Search RxNorm for drug concept IDs, names, and interactions."""
    citations: List[Citation] = []
    keywords = _extract_drug_keywords(query)
    if not keywords:
        return citations

    drug_name = keywords[0]

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            # Step 1: Get drug concepts
            resp = await client.get(
                "https://rxnav.nlm.nih.gov/REST/drugs.json",
                params={"name": drug_name},
            )
            if resp.status_code != 200:
                logger.warning(f"[RxNorm] HTTP {resp.status_code}")
                return citations

            data = resp.json()
            drug_group = data.get("drugGroup", {})
            concept_groups = drug_group.get("conceptGroup", [])

            count = 0
            for cg in concept_groups:
                for concept in cg.get("conceptProperties", []):
                    if count >= MAX_CITATIONS_PER_SKILL:
                        break
                    rxcui = concept.get("rxcui", "")
                    name = concept.get("name", drug_name)
                    tty = concept.get("tty", "")
                    synonym = concept.get("synonym", "")

                    snippet = f"RxCUI: {rxcui}. Type: {tty}"
                    if synonym:
                        snippet += f". Also: {synonym}"

                    citations.append(Citation(
                        id=f"RX-{count+1}",
                        source="RxNorm",
                        title=f"{name} (RxCUI: {rxcui})",
                        url=f"https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm={rxcui}",
                        snippet=snippet[:200],
                        relevance=0.72 - count * 0.08,
                    ))
                    count += 1
                if count >= MAX_CITATIONS_PER_SKILL:
                    break

            # Step 2: Check drug interactions if we have multiple drug keywords
            if len(keywords) >= 2:
                try:
                    # Get RxCUI for first drug
                    rxcui_resp = await client.get(
                        "https://rxnav.nlm.nih.gov/REST/rxcui.json",
                        params={"name": keywords[0]},
                    )
                    if rxcui_resp.status_code == 200:
                        rxcui_data = rxcui_resp.json()
                        rxcuis = rxcui_data.get("idGroup", {}).get("rxnormId", [])
                        if rxcuis:
                            inter_resp = await client.get(
                                "https://rxnav.nlm.nih.gov/REST/interaction/interaction.json",
                                params={"rxcui": rxcuis[0]},
                            )
                            if inter_resp.status_code == 200:
                                inter_data = inter_resp.json()
                                pairs = inter_data.get("interactionTypeGroup", [])
                                for group in pairs[:1]:
                                    for itype in group.get("interactionType", [])[:2]:
                                        for pair in itype.get("interactionPair", [])[:2]:
                                            desc = pair.get("description", "")
                                            if desc:
                                                citations.append(Citation(
                                                    id=f"RX-DDI",
                                                    source="RxNorm",
                                                    title=f"Drug Interaction: {keywords[0]}",
                                                    url=f"https://rxnav.nlm.nih.gov/REST/interaction/interaction.json?rxcui={rxcuis[0]}",
                                                    snippet=desc[:200],
                                                    relevance=0.78,
                                                ))
                except Exception as e:
                    logger.debug(f"[RxNorm] Interaction lookup: {e}")

        except Exception as e:
            logger.warning(f"[RxNorm] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# Skill 11: STRING-DB (Protein-Protein Interaction Networks)
# https://string-db.org/api — Interactions, enrichment, annotation
# ═══════════════════════════════════════════════════════════════════

async def _query_string_db(query: str) -> List[Citation]:
    """Search STRING-DB for protein interaction networks and enrichment."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    # STRING-DB expects protein/gene identifiers
    identifiers = "\r".join(keywords[:4])

    async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
        try:
            # Resolve identifiers to STRING IDs
            resp = await client.get(
                "https://string-db.org/api/json/get_string_ids",
                params={
                    "identifiers": identifiers,
                    "species": 9606,  # Homo sapiens
                    "limit": MAX_CITATIONS_PER_SKILL,
                },
            )
            if resp.status_code != 200:
                logger.warning(f"[STRING-DB] HTTP {resp.status_code}")
                return citations

            proteins = resp.json()
            if not proteins:
                return citations

            # Get interaction network for resolved proteins
            resolved_ids = "\r".join(p.get("preferredName", "") for p in proteins[:4])
            net_resp = await client.get(
                "https://string-db.org/api/json/network",
                params={
                    "identifiers": resolved_ids,
                    "species": 9606,
                },
            )
            if net_resp.status_code == 200:
                interactions = net_resp.json()
                for i, inter in enumerate(interactions[:MAX_CITATIONS_PER_SKILL]):
                    prot_a = inter.get("preferredName_A", "?")
                    prot_b = inter.get("preferredName_B", "?")
                    score = inter.get("score", 0)
                    citations.append(Citation(
                        id=f"STR-{i+1}",
                        source="STRING-DB",
                        title=f"{prot_a} ↔ {prot_b} (score: {score:.3f})",
                        url=f"https://string-db.org/network/{inter.get('stringId_A', '')}",
                        snippet=f"Protein interaction: {prot_a} ↔ {prot_b}, combined score {score:.3f}",
                        relevance=min(0.75, 0.5 + score * 0.3) - i * 0.05,
                    ))

            # Functional enrichment
            try:
                enrich_resp = await client.get(
                    "https://string-db.org/api/json/enrichment",
                    params={
                        "identifiers": resolved_ids,
                        "species": 9606,
                    },
                )
                if enrich_resp.status_code == 200:
                    enrichments = enrich_resp.json()
                    for j, enr in enumerate(enrichments[:2]):
                        term = enr.get("term", "")
                        desc = enr.get("description", "")
                        pval = enr.get("p_value", 1)
                        category = enr.get("category", "")
                        citations.append(Citation(
                            id=f"STR-E{j+1}",
                            source="STRING-DB",
                            title=f"Enrichment: {desc or term}",
                            url=f"https://string-db.org/cgi/network?identifiers={resolved_ids.replace(chr(13), '%0d')}&species=9606",
                            snippet=f"{category}: {desc} (p={pval:.2e})"[:200],
                            relevance=0.68 - j * 0.1,
                        ))
            except Exception as e:
                logger.debug(f"[STRING-DB] Enrichment: {e}")

        except Exception as e:
            logger.warning(f"[STRING-DB] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# CORE SKILL 12: Hubble Search (Bayer Internal)
# https://search.hubble.int.bayer.com/ — Bayer enterprise search
# Routed via MyGenAssist API authentication (same Bearer token)
# ═══════════════════════════════════════════════════════════════════

async def _query_hubble(query: str) -> List[Citation]:
    """Search Bayer Hubble internal enterprise knowledge base."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return citations

    search_term = " ".join(keywords[:4])
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=12, verify=False) as client:
        try:
            # Primary: Hubble API search endpoint (Bayer internal)
            resp = await client.get(
                "https://search.hubble.int.bayer.com/api/search",
                params={"q": search_term, "limit": 5},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data.get("items", data.get("hits", [])))
                if isinstance(results, dict):
                    results = results.get("hits", results.get("items", []))
                for i, item in enumerate(results[:5]):
                    title = (
                        item.get("title", "")
                        or item.get("name", "")
                        or item.get("headline", "")
                    )
                    if not title:
                        continue
                    url = (
                        item.get("url", "")
                        or item.get("link", "")
                        or item.get("href", "")
                        or f"https://search.hubble.int.bayer.com/?q={search_term}"
                    )
                    snippet = (
                        item.get("snippet", "")
                        or item.get("description", "")
                        or item.get("abstract", "")
                        or item.get("summary", "")
                    )[:200]
                    doc_type = item.get("type", item.get("docType", ""))
                    source_tag = f"Hubble/{doc_type}" if doc_type else "Hubble"

                    citations.append(Citation(
                        id=f"HUB-{i+1}",
                        source=source_tag,
                        title=title[:150],
                        url=url,
                        snippet=snippet or f"Bayer internal result for: {search_term}",
                        relevance=0.82 - i * 0.05,
                    ))
            else:
                logger.debug(f"[Hubble] HTTP {resp.status_code} — may need auth scope")
        except Exception as e:
            logger.warning(f"[Hubble] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 13: Semantic Scholar
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
# WEB SEARCH SKILL 20: OpenAlex (Open Scholarly Metadata)
# https://api.openalex.org — 243M+ works, CC0 public domain
# ═══════════════════════════════════════════════════════════════════

async def _query_openalex(query: str) -> List[Citation]:
    """Search OpenAlex for scholarly works across all disciplines."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:5])

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                "https://api.openalex.org/works",
                params={
                    "search": search_term,
                    "per_page": MAX_CITATIONS_PER_SKILL,
                    "mailto": "research@llmcouncil.dev",
                    "select": "id,doi,title,authorships,publication_year,cited_by_count,primary_location,open_access,abstract_inverted_index",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"[OpenAlex] HTTP {resp.status_code}")
                return citations

            data = resp.json()
            results = data.get("results", [])
            for i, work in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                title = work.get("title", "OpenAlex Work") or "OpenAlex Work"
                doi = work.get("doi", "")
                year = work.get("publication_year", "")
                cited_by = work.get("cited_by_count", 0) or 0
                is_oa = (work.get("open_access", {}) or {}).get("is_oa", False)

                # Extract first author
                authorships = work.get("authorships", []) or []
                first_author = ""
                if authorships:
                    author_info = authorships[0].get("author", {}) or {}
                    first_author = author_info.get("display_name", "")

                # Primary journal
                primary_loc = work.get("primary_location", {}) or {}
                source = primary_loc.get("source", {}) or {}
                journal_name = source.get("display_name", "")

                # Reconstruct abstract from inverted index
                abstract = ""
                aii = work.get("abstract_inverted_index")
                if aii and isinstance(aii, dict):
                    try:
                        word_positions = []
                        for word, positions in aii.items():
                            for pos in positions:
                                word_positions.append((pos, word))
                        word_positions.sort()
                        abstract = " ".join(w for _, w in word_positions)[:150]
                    except Exception:
                        pass

                snippet_parts = []
                if first_author:
                    snippet_parts.append(f"{first_author} et al.")
                if journal_name:
                    snippet_parts.append(journal_name)
                if year:
                    snippet_parts.append(f"({year})")
                if is_oa:
                    snippet_parts.append("[Open Access]")
                if cited_by:
                    snippet_parts.append(f"Cited {cited_by}x")
                if abstract:
                    snippet_parts.append(f"— {abstract}")
                snippet = " ".join(snippet_parts)[:200]

                work_url = doi or work.get("id", f"https://openalex.org/works?search={search_term}")

                base_relevance = 0.82 - i * 0.06
                if cited_by and cited_by > 100:
                    base_relevance = min(base_relevance + 0.08, 0.92)
                if is_oa:
                    base_relevance = min(base_relevance + 0.03, 0.95)

                citations.append(Citation(
                    id=f"OA-{i+1}",
                    source="OpenAlex",
                    title=title[:150],
                    url=work_url,
                    snippet=snippet,
                    relevance=base_relevance,
                    date=str(year),
                ))
        except Exception as e:
            logger.warning(f"[OpenAlex] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 21: Unpaywall (Open Access DOI Resolver)
# https://api.unpaywall.org/v2 — OA status & URLs for DOIs
# ═══════════════════════════════════════════════════════════════════

async def _query_unpaywall(query: str) -> List[Citation]:
    """
    Search Unpaywall for open access versions of papers.
    Works best when the query contains DOIs; otherwise uses
    OpenAlex to find relevant DOIs first, then checks OA status.
    """
    citations: List[Citation] = []

    # Try to extract DOIs directly from query
    doi_pattern = re.compile(r'10\.\d{4,}/[^\s,;)\]]+')
    dois = doi_pattern.findall(query)

    if not dois:
        # Use a quick OpenAlex lookup to find relevant DOIs
        keywords = _extract_medical_keywords(query)
        if not keywords:
            return citations
        search_term = " ".join(keywords[:4])
        try:
            async with httpx.AsyncClient(timeout=SKILL_TIMEOUT, verify=False) as client:
                resp = await client.get(
                    "https://api.openalex.org/works",
                    params={
                        "search": search_term,
                        "per_page": MAX_CITATIONS_PER_SKILL,
                        "mailto": "research@llmcouncil.dev",
                        "select": "doi",
                    },
                )
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    dois = [
                        r["doi"].replace("https://doi.org/", "")
                        for r in results
                        if r.get("doi")
                    ][:MAX_CITATIONS_PER_SKILL]
        except Exception:
            pass

    if not dois:
        return citations

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        for i, doi in enumerate(dois[:MAX_CITATIONS_PER_SKILL]):
            try:
                clean_doi = doi.replace("https://doi.org/", "")
                resp = await client.get(
                    f"https://api.unpaywall.org/v2/{clean_doi}",
                    params={"email": "research@llmcouncil.dev"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                title = data.get("title", "Unpaywall Article") or "Article"
                is_oa = data.get("is_oa", False)
                oa_status = data.get("oa_status", "closed")
                best_loc = data.get("best_oa_location") or {}
                oa_url = best_loc.get("url_for_pdf") or best_loc.get("url") or f"https://doi.org/{clean_doi}"
                journal = data.get("journal_name", "")
                year = data.get("year", "")
                authors_list = data.get("z_authors", []) or []
                first_auth = authors_list[0].get("family", "") if authors_list else ""

                snippet_parts = []
                if first_auth:
                    snippet_parts.append(f"{first_auth} et al.")
                if journal:
                    snippet_parts.append(journal)
                if year:
                    snippet_parts.append(f"({year})")
                snippet_parts.append(f"OA: {oa_status}")
                if is_oa:
                    snippet_parts.append("✓ Open Access available")
                snippet = " ".join(snippet_parts)[:200]

                citations.append(Citation(
                    id=f"UPW-{i+1}",
                    source="Unpaywall",
                    title=title[:150],
                    url=oa_url,
                    snippet=snippet,
                    relevance=0.76 + (0.08 if is_oa else 0) - i * 0.06,
                    date=str(year),
                ))
            except Exception as e:
                logger.debug(f"[Unpaywall] DOI {doi}: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 22: Elsevier / Scopus (Abstracts & Metadata)
# https://api.elsevier.com — Requires free API key from dev.elsevier.com
# ═══════════════════════════════════════════════════════════════════

# Optional: set ELSEVIER_API_KEY in .env for Scopus access
_ELSEVIER_API_KEY = os.environ.get("ELSEVIER_API_KEY", "")


async def _query_elsevier(query: str) -> List[Citation]:
    """Search Elsevier/Scopus for scientific abstracts (requires API key)."""
    citations: List[Citation] = []
    if not _ELSEVIER_API_KEY:
        logger.debug("[Elsevier] No ELSEVIER_API_KEY set — skipping")
        return citations

    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " AND ".join(keywords[:4])

    async with httpx.AsyncClient(timeout=WEB_SKILL_TIMEOUT, verify=False) as client:
        try:
            resp = await client.get(
                "https://api.elsevier.com/content/search/scopus",
                params={
                    "query": search_term,
                    "count": MAX_CITATIONS_PER_SKILL,
                },
                headers={
                    "X-ELS-APIKey": _ELSEVIER_API_KEY,
                    "Accept": "application/json",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"[Elsevier] HTTP {resp.status_code}")
                return citations

            data = resp.json()
            results = data.get("search-results", {}).get("entry", [])
            for i, entry in enumerate(results[:MAX_CITATIONS_PER_SKILL]):
                title = entry.get("dc:title", "Scopus Article") or "Scopus Article"
                doi = entry.get("prism:doi", "")
                journal = entry.get("prism:publicationName", "")
                cover_date = entry.get("prism:coverDate", "")
                cited_by = int(entry.get("citedby-count", 0) or 0)
                creator = entry.get("dc:creator", "")
                scopus_id = entry.get("dc:identifier", "").replace("SCOPUS_ID:", "")
                abstract_text = entry.get("dc:description", "") or ""

                article_url = f"https://doi.org/{doi}" if doi else entry.get("link", [{}])[0].get("@href", "")

                snippet_parts = []
                if creator:
                    snippet_parts.append(creator)
                if journal:
                    snippet_parts.append(journal)
                if cover_date:
                    snippet_parts.append(f"({cover_date[:4]})")
                if cited_by:
                    snippet_parts.append(f"Cited {cited_by}x")
                if abstract_text:
                    snippet_parts.append(f"— {abstract_text[:120]}")
                snippet = " ".join(snippet_parts)[:200]

                base_relevance = 0.80 - i * 0.06
                if cited_by > 50:
                    base_relevance = min(base_relevance + 0.08, 0.92)

                citations.append(Citation(
                    id=f"ELS-{i+1}",
                    source="Elsevier/Scopus",
                    title=title[:150],
                    url=article_url,
                    snippet=snippet,
                    relevance=base_relevance,
                    date=cover_date[:4] if cover_date else "",
                ))
        except Exception as e:
            logger.warning(f"[Elsevier] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 24: bioRxiv
# https://api.biorxiv.org — Biology preprints (Cold Spring Harbor)
# Free REST API, no auth required, JSON response
# ═══════════════════════════════════════════════════════════════════

async def _query_biorxiv(query: str) -> List[Citation]:
    """Search bioRxiv for recent biology preprints by date range + keyword match."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    # bioRxiv API has no keyword search — fetch recent 30 days and filter client-side
    from datetime import timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        try:
            resp = await client.get(
                f"https://api.biorxiv.org/details/biorxiv/{start_date}/{end_date}/0/json",
            )
            if resp.status_code == 200:
                data = resp.json()
                collection = data.get("collection", [])
                kw_lower = [k.lower() for k in keywords]

                # Filter for keyword matches in title/abstract
                matched = []
                for paper in collection:
                    title = paper.get("title", "")
                    abstract = paper.get("abstract", "")
                    text = f"{title} {abstract}".lower()
                    score = sum(1 for k in kw_lower if k in text)
                    if score > 0:
                        matched.append((score, paper))

                matched.sort(key=lambda x: x[0], reverse=True)

                for i, (score, paper) in enumerate(matched[:5]):
                    title = paper.get("title", "Untitled")
                    doi = paper.get("doi", "")
                    authors = paper.get("authors", "")
                    date_str = paper.get("date", "")
                    abstract = paper.get("abstract", "")[:150]
                    category = paper.get("category", "")

                    url = f"https://doi.org/{doi}" if doi else "https://www.biorxiv.org"
                    snippet_parts = []
                    if authors:
                        snippet_parts.append(authors.split(";")[0].strip())
                    if category:
                        snippet_parts.append(f"[{category}]")
                    if abstract:
                        snippet_parts.append(f"— {abstract}")
                    snippet = " ".join(snippet_parts)[:200]

                    citations.append(Citation(
                        id=f"BRX-{i+1}",
                        source="bioRxiv",
                        title=title[:150],
                        url=url,
                        snippet=snippet or f"bioRxiv preprint: {title[:100]}",
                        relevance=0.78 - i * 0.06,
                        date=date_str[:4] if date_str else "",
                    ))
        except Exception as e:
            logger.warning(f"[bioRxiv] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 25: medRxiv
# https://api.biorxiv.org — Health sciences preprints (same API infra)
# Free REST API, no auth required, JSON response
# ═══════════════════════════════════════════════════════════════════

async def _query_medrxiv(query: str) -> List[Citation]:
    """Search medRxiv for recent health sciences preprints."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    from datetime import timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        try:
            resp = await client.get(
                f"https://api.biorxiv.org/details/medrxiv/{start_date}/{end_date}/0/json",
            )
            if resp.status_code == 200:
                data = resp.json()
                collection = data.get("collection", [])
                kw_lower = [k.lower() for k in keywords]

                matched = []
                for paper in collection:
                    title = paper.get("title", "")
                    abstract = paper.get("abstract", "")
                    text = f"{title} {abstract}".lower()
                    score = sum(1 for k in kw_lower if k in text)
                    if score > 0:
                        matched.append((score, paper))

                matched.sort(key=lambda x: x[0], reverse=True)

                for i, (score, paper) in enumerate(matched[:5]):
                    title = paper.get("title", "Untitled")
                    doi = paper.get("doi", "")
                    authors = paper.get("authors", "")
                    date_str = paper.get("date", "")
                    abstract = paper.get("abstract", "")[:150]
                    category = paper.get("category", "")

                    url = f"https://doi.org/{doi}" if doi else "https://www.medrxiv.org"
                    snippet_parts = []
                    if authors:
                        snippet_parts.append(authors.split(";")[0].strip())
                    if category:
                        snippet_parts.append(f"[{category}]")
                    if abstract:
                        snippet_parts.append(f"— {abstract}")
                    snippet = " ".join(snippet_parts)[:200]

                    citations.append(Citation(
                        id=f"MRX-{i+1}",
                        source="medRxiv",
                        title=title[:150],
                        url=url,
                        snippet=snippet or f"medRxiv preprint: {title[:100]}",
                        relevance=0.78 - i * 0.06,
                        date=date_str[:4] if date_str else "",
                    ))
        except Exception as e:
            logger.warning(f"[medRxiv] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 26: OECD.AI Policy Observatory
# https://wp.oecd.ai/wp-json/wp/v2/ — WordPress REST API
# Free, no auth, keyword search via ?search= parameter
# ═══════════════════════════════════════════════════════════════════

async def _query_oecd_ai(query: str) -> List[Citation]:
    """Search OECD.AI for AI policy, regulation, and governance content."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    search_term = " ".join(keywords[:3])

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        try:
            resp = await client.get(
                "https://wp.oecd.ai/wp-json/wp/v2/posts",
                params={
                    "search": search_term,
                    "per_page": 5,
                    "orderby": "relevance",
                    "_fields": "id,date,title,excerpt,link,categories,tags",
                },
            )
            if resp.status_code == 200:
                posts = resp.json()
                for i, post in enumerate(posts[:5]):
                    title_raw = post.get("title", {}).get("rendered", "")
                    # Strip HTML tags from title
                    import re as _re
                    title = _re.sub(r"<[^>]+>", "", title_raw).strip()
                    if not title:
                        continue

                    link = post.get("link", "https://oecd.ai")
                    date_str = post.get("date", "")
                    excerpt_raw = post.get("excerpt", {}).get("rendered", "")
                    excerpt = _re.sub(r"<[^>]+>", "", excerpt_raw).strip()[:200]

                    citations.append(Citation(
                        id=f"OECD-{i+1}",
                        source="OECD.AI",
                        title=title[:150],
                        url=link,
                        snippet=excerpt or f"OECD AI policy: {title[:120]}",
                        relevance=0.75 - i * 0.06,
                        date=date_str[:4] if date_str else "",
                    ))
        except Exception as e:
            logger.warning(f"[OECD.AI] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 27: Endpoints News
# https://endpts.com/feed/ — Biopharma industry news (RSS 2.0)
# Free, no auth, XML/RSS feed
# ═══════════════════════════════════════════════════════════════════

async def _query_endpoints_news(query: str) -> List[Citation]:
    """Search Endpoints News RSS feed for biopharma industry news."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    async with httpx.AsyncClient(timeout=12, verify=False) as client:
        try:
            resp = await client.get("https://endpts.com/feed/")
            if resp.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)

                items = root.findall(".//item")
                kw_lower = [k.lower() for k in keywords]

                scored_items = []
                for item in items:
                    title = (item.findtext("title") or "").strip()
                    desc = (item.findtext("description") or "").strip()
                    text = f"{title} {desc}".lower()
                    score = sum(1 for k in kw_lower if k in text)
                    if score > 0:
                        scored_items.append((score, item))

                scored_items.sort(key=lambda x: x[0], reverse=True)

                for i, (score, item) in enumerate(scored_items[:5]):
                    title = (item.findtext("title") or "Untitled").strip()
                    link = (item.findtext("link") or "https://endpts.com").strip()
                    desc = (item.findtext("description") or "").strip()
                    pub_date = (item.findtext("pubDate") or "").strip()

                    # Strip HTML from description
                    import re as _re
                    desc_clean = _re.sub(r"<[^>]+>", "", desc).strip()[:200]

                    # Extract categories
                    categories = [c.text for c in item.findall("category") if c.text]
                    cat_str = ", ".join(categories[:3])

                    snippet_parts = []
                    if cat_str:
                        snippet_parts.append(f"[{cat_str}]")
                    if desc_clean:
                        snippet_parts.append(desc_clean)
                    snippet = " ".join(snippet_parts)[:200]

                    # Parse year from pubDate
                    year = ""
                    if pub_date:
                        parts = pub_date.split()
                        for p in parts:
                            if len(p) == 4 and p.isdigit():
                                year = p
                                break

                    citations.append(Citation(
                        id=f"EPTS-{i+1}",
                        source="Endpoints News",
                        title=title[:150],
                        url=link,
                        snippet=snippet or f"Biopharma news: {title[:120]}",
                        relevance=0.72 - i * 0.06,
                        date=year,
                    ))
        except Exception as e:
            logger.warning(f"[Endpoints News] Query failed: {e}")

    return citations


# ═══════════════════════════════════════════════════════════════════
# WEB SEARCH SKILL 28: Doctor Penguin
# https://doctorpenguin.substack.com/feed — Healthcare + AI newsletter
# RSS feed (Substack), free, no auth
# ═══════════════════════════════════════════════════════════════════

async def _query_doctor_penguin(query: str) -> List[Citation]:
    """Search Doctor Penguin Substack for healthcare + AI news."""
    citations: List[Citation] = []
    keywords = _extract_medical_keywords(query)
    if not keywords:
        return citations

    async with httpx.AsyncClient(timeout=12, verify=False, follow_redirects=True) as client:
        try:
            # Try Substack feed first (more current), fall back to original
            feed_url = "https://doctorpenguin.substack.com/feed"
            resp = await client.get(feed_url)
            if resp.status_code != 200:
                resp = await client.get("https://doctorpenguin.com/feed")
            if resp.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)

                items = root.findall(".//item")
                kw_lower = [k.lower() for k in keywords]

                scored_items = []
                for item in items:
                    title = (item.findtext("title") or "").strip()
                    # Substack uses content:encoded for full text
                    desc = (item.findtext("description") or "").strip()
                    text = f"{title} {desc}".lower()
                    score = sum(1 for k in kw_lower if k in text)
                    if score > 0:
                        scored_items.append((score, item))

                scored_items.sort(key=lambda x: x[0], reverse=True)

                for i, (score, item) in enumerate(scored_items[:5]):
                    title = (item.findtext("title") or "Untitled").strip()
                    link = (item.findtext("link") or "https://doctorpenguin.com").strip()
                    desc = (item.findtext("description") or "").strip()
                    pub_date = (item.findtext("pubDate") or "").strip()

                    import re as _re
                    desc_clean = _re.sub(r"<[^>]+>", "", desc).strip()[:200]

                    year = ""
                    if pub_date:
                        parts = pub_date.split()
                        for p in parts:
                            if len(p) == 4 and p.isdigit():
                                year = p
                                break

                    citations.append(Citation(
                        id=f"DPNG-{i+1}",
                        source="Doctor Penguin",
                        title=title[:150],
                        url=link,
                        snippet=desc_clean or f"Healthcare AI: {title[:120]}",
                        relevance=0.68 - i * 0.06,
                        date=year,
                    ))
        except Exception as e:
            logger.warning(f"[Doctor Penguin] Query failed: {e}")

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
      7. ChEMBL       8. KEGG                9. Reactome
      10. RxNorm      11. STRING-DB          12. Hubble (Bayer)

    Web search skills (only when web_search_enabled=True):
      13. Semantic Scholar  14. CrossRef      15. Europe PMC
      16. DuckDuckGo Sci   17. arXiv         18. Google Patents
      19. Wikipedia         20. ORCID         21. OpenAlex
      22. Unpaywall         23. Elsevier/Scopus 24. bioRxiv
      25. medRxiv           26. OECD.AI       27. Endpoints News
      28. Doctor Penguin

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
        "KEGG":                 asyncio.create_task(_query_kegg(user_query)),
        "Reactome":             asyncio.create_task(_query_reactome(user_query)),
        "RxNorm":               asyncio.create_task(_query_rxnorm(user_query)),
        "STRING-DB":            asyncio.create_task(_query_string_db(user_query)),
        "Hubble":               asyncio.create_task(_query_hubble(user_query)),
    }

    # ── Web search skills (only when toggled ON) ───────────────────
    if web_search_enabled:
        logger.info("[Skills] Web search ENABLED — adding 16 web search skills")
        tasks["Semantic Scholar"] = asyncio.create_task(_query_semantic_scholar(user_query))
        tasks["CrossRef"]         = asyncio.create_task(_query_crossref(user_query))
        tasks["Europe PMC"]       = asyncio.create_task(_query_europe_pmc(user_query))
        tasks["DuckDuckGo Sci"]   = asyncio.create_task(_query_duckduckgo_science(user_query))
        tasks["arXiv"]            = asyncio.create_task(_query_arxiv(user_query))
        tasks["Google Patents"]   = asyncio.create_task(_query_patents(user_query))
        tasks["Wikipedia"]        = asyncio.create_task(_query_wikipedia(user_query))
        tasks["ORCID"]            = asyncio.create_task(_query_orcid(user_query))
        tasks["OpenAlex"]         = asyncio.create_task(_query_openalex(user_query))
        tasks["Unpaywall"]        = asyncio.create_task(_query_unpaywall(user_query))
        tasks["Elsevier/Scopus"]  = asyncio.create_task(_query_elsevier(user_query))
        tasks["bioRxiv"]          = asyncio.create_task(_query_biorxiv(user_query))
        tasks["medRxiv"]          = asyncio.create_task(_query_medrxiv(user_query))
        tasks["OECD.AI"]          = asyncio.create_task(_query_oecd_ai(user_query))
        tasks["Endpoints News"]   = asyncio.create_task(_query_endpoints_news(user_query))
        tasks["Doctor Penguin"]   = asyncio.create_task(_query_doctor_penguin(user_query))

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

    # Merge and deduplicate by URL
    all_citations = []
    for c_list in results.values():
        all_citations.extend(c_list)

    seen_urls = set()
    unique = []
    for c in all_citations:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            unique.append(c)

    # ── MedCPT Neural Reranking ────────────────────────────────────
    # Replace static per-source relevance with query-aware medical
    # cross-encoder scores from DeepMind MedCPT.
    t_rerank = datetime.now()
    reranker_used = False
    try:
        reranked = await rerank_citations(user_query, unique)
        if reranked is not unique:          # reranker actually ran
            reranker_used = True
            unique = reranked
            logger.info(f"[Skills] MedCPT reranking applied to {len(unique)} citations")
        else:
            # Fallback: keep static sort
            unique.sort(key=lambda c: c.relevance, reverse=True)
    except Exception as e:
        logger.warning(f"[Skills] MedCPT reranking failed ({e}), using static sort")
        unique.sort(key=lambda c: c.relevance, reverse=True)
    rerank_ms = (datetime.now() - t_rerank).total_seconds() * 1000
    benchmarks["medcpt_rerank_ms"] = round(rerank_ms, 1)

    # Cap to citation limit
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
        f"{' [MedCPT reranked]' if reranker_used else ' [static rank]'}"
        f"{' [WEB SEARCH ON]' if web_search_enabled else ''}"
    )

    return {
        "citations": [c.to_dict() for c in top],
        "skills_used": skills_used,
        "total_found": len(unique),
        "web_search_active": web_search_enabled,
        "reranker": {
            "model": "deepmind/medcpt" if reranker_used else None,
            "active": reranker_used,
            "latency_ms": round(rerank_ms, 1),
        },
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
        "[KG-1], [RC-1], [RX-1], [STR-1], [HUB-1], "
        "[SS-1], [CR-1], [EPMC-1], [WEB-1], [AX-1], [PAT-1], [WIKI-1], [ORC-1], "
        "[OA-1], [UPW-1], [ELS-1], [BRX-1], [MRX-1], [OECD-1], [EPTS-1], [DPNG-1]) "
        "inline in your text. "
        "At the end of your response, include a numbered REFERENCES section listing "
        "each citation you used with its full URL."
    )
    return "\n".join(lines)
