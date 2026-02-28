"""
Citation Registry — Auditability & Traceability for LLM Council.

Centralised reference catalogue documenting every academic paper,
framework, dataset, and standard that influenced the system's design.

Usage:
    from backend.citation import get_citation, list_all, get_by_module, format_apa

    cite = get_citation("geng2024chameleons")
    refs  = get_by_module("council")
    print(format_apa("geng2024chameleons"))
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_council.citation")


# ═══════════════════════════════════════════════════════════════════════
# Citation Data Model
# ═══════════════════════════════════════════════════════════════════════

# Each entry:
#   id             — unique short key (author_year_keyword)
#   title          — full paper / resource title
#   authors        — author list (abbreviated for >3 authors)
#   year           — publication year
#   venue          — journal / conference / preprint server
#   arxiv_id       — arXiv identifier (if applicable)
#   doi            — DOI (if applicable)
#   url            — best-effort stable URL
#   abstract_short — 1-sentence summary
#   relevance      — how this reference is used in LLM Council
#   modules        — list of backend modules that implement ideas from this ref

CITATIONS: Dict[str, Dict[str, Any]] = {

    # ── Core Research Papers ─────────────────────────────────────────

    "geng2024chameleons": {
        "id": "geng2024chameleons",
        "title": "Are Large Language Models Chameleons?",
        "authors": "Geng, S., He, J., & Trotta, R.",
        "year": 2024,
        "venue": "arXiv preprint",
        "arxiv_id": "2405.19323",
        "doi": None,
        "url": "https://arxiv.org/abs/2405.19323",
        "abstract_short": (
            "Investigates LLM bias in survey responses; proposes J-index "
            "(Jaccard-inspired similarity) and demonstrates prompt-order "
            "effects on model outputs."
        ),
        "relevance": (
            "Position Debiasing — Stage 2 shuffles response presentation "
            "order per reviewer to mitigate first-position bias in peer "
            "evaluation (§3 Experimental Design, §4 J-index Analysis)."
        ),
        "modules": ["council"],
    },

    "woodruff2026gemini": {
        "id": "woodruff2026gemini",
        "title": "Accelerating Scientific Research with Gemini",
        "authors": "Woodruff, A. et al. (Google DeepMind)",
        "year": 2026,
        "venue": "arXiv preprint",
        "arxiv_id": "2602.03837",
        "doi": None,
        "url": "https://arxiv.org/abs/2602.03837",
        "abstract_short": (
            "Demonstrates iterative refinement, problem decomposition, "
            "adversarial reviewer, and neuro-symbolic verification loops "
            "for scientific reasoning with LLMs."
        ),
        "relevance": (
            "Chairman Self-Reflection / Doubting Thomas — after initial "
            "synthesis the chairman's draft is critiqued by a sceptical "
            "adversarial reviewer; defects trigger a targeted fix pass "
            "(§Adversarial Reviewer Design Pattern)."
        ),
        "modules": ["council", "main"],
    },

    "shi2026erl": {
        "id": "shi2026erl",
        "title": "Experiential Reinforcement Learning",
        "authors": "Shi, R. et al.",
        "year": 2026,
        "venue": "arXiv preprint",
        "arxiv_id": "2602.13949",
        "doi": None,
        "url": "https://arxiv.org/abs/2602.13949",
        "abstract_short": (
            "Introduces ERL with experience-reflection-consolidation loop, "
            "cross-episode reflection memory, gated reflection (τ threshold), "
            "and self-distillation internalization — +81% gains on complex tasks."
        ),
        "relevance": (
            "Gated ECA Adaptation — adaptations fire only when grounding < τ "
            "(default 0.75); prevents overfitting on already-good trajectories. "
            "Also informs the Doubting Thomas self-reflection loop design "
            "(§Gated Reflection, §Experience-Reflection-Consolidation)."
        ),
        "modules": ["memory", "council"],
    },

    "es2023ragas": {
        "id": "es2023ragas",
        "title": "RAGAS: Automated Evaluation of Retrieval Augmented Generation",
        "authors": "Es, S., James, J., Espinosa-Anke, L., & Schockaert, S.",
        "year": 2023,
        "venue": "arXiv preprint / EMNLP 2024",
        "arxiv_id": "2309.15217",
        "doi": "10.18653/v1/2024.eacl-demo.16",
        "url": "https://arxiv.org/abs/2309.15217",
        "abstract_short": (
            "Defines Faithfulness, Context Recall, and Factual Correctness "
            "metrics for RAG pipelines; provides reference scoring framework."
        ),
        "relevance": (
            "RAGAS-aligned grounding metrics — Precision=Faithfulness, "
            "Recall=Context Recall, F1=Factual Correctness as implemented "
            "in grounding.py (§Metric Definitions, verified against RAGAS v0.2)."
        ),
        "modules": ["grounding"],
    },

    "zheng2023judging": {
        "id": "zheng2023judging",
        "title": "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena",
        "authors": "Zheng, L., Chiang, W.-L., Sheng, Y. et al.",
        "year": 2023,
        "venue": "NeurIPS 2023",
        "arxiv_id": "2306.05685",
        "doi": None,
        "url": "https://arxiv.org/abs/2306.05685",
        "abstract_short": (
            "Systematic study of LLM-as-a-Judge for evaluating chatbot "
            "quality; introduces MT-Bench and position bias analysis."
        ),
        "relevance": (
            "Foundational reference for peer-review Stage 2 design — "
            "anonymized evaluation prevents model favouritism; position "
            "bias findings motivate shuffle debiasing."
        ),
        "modules": ["council"],
    },

    "liu2024aligning": {
        "id": "liu2024aligning",
        "title": "Aligning with Human Judgement: The Role of Pairwise Preference in Large Language Model Evaluators",
        "authors": "Liu, Y. et al.",
        "year": 2024,
        "venue": "arXiv preprint",
        "arxiv_id": "2403.16950",
        "doi": None,
        "url": "https://arxiv.org/abs/2403.16950",
        "abstract_short": (
            "Studies pairwise preference alignment in LLM evaluators and "
            "proposes calibration methods for more reliable rankings."
        ),
        "relevance": (
            "Informs the verbalized sampling rubric design in Stage 2 — "
            "per-criterion scoring (0–10) before ranking to reduce "
            "cognitive bias in holistic judgements."
        ),
        "modules": ["council", "grounding"],
    },

    # ── Frameworks & Standards ───────────────────────────────────────

    "ragas_v02": {
        "id": "ragas_v02",
        "title": "RAGAS v0.2 Framework",
        "authors": "Explodinggradients",
        "year": 2024,
        "venue": "GitHub / Documentation",
        "arxiv_id": None,
        "doi": None,
        "url": "https://docs.ragas.io/en/stable/",
        "abstract_short": (
            "Open-source evaluation framework for RAG pipelines; provides "
            "Faithfulness, Context Recall, Factual Correctness metrics."
        ),
        "relevance": (
            "Reference implementation for grounding score formulas — "
            "Precision, Recall, F1 verified against RAGAS v0.2 definitions."
        ),
        "modules": ["grounding"],
    },

    "fastapi": {
        "id": "fastapi",
        "title": "FastAPI — Modern, Fast Web Framework for Building APIs",
        "authors": "Ramírez, S.",
        "year": 2019,
        "venue": "Open Source",
        "arxiv_id": None,
        "doi": None,
        "url": "https://fastapi.tiangolo.com/",
        "abstract_short": (
            "High-performance async Python web framework; handles SSE "
            "streaming, dependency injection, and OpenAPI generation."
        ),
        "relevance": (
            "Core backend framework — all API endpoints, SSE streaming "
            "pipeline, CORS, auth dependency injection."
        ),
        "modules": ["main", "auth"],
    },

    "azure_cosmos_db": {
        "id": "azure_cosmos_db",
        "title": "Azure Cosmos DB — Globally Distributed Multi-Model Database",
        "authors": "Microsoft",
        "year": 2017,
        "venue": "Azure Documentation",
        "arxiv_id": None,
        "doi": None,
        "url": "https://learn.microsoft.com/en-us/azure/cosmos-db/",
        "abstract_short": (
            "NoSQL database with partition-key-based isolation, encryption "
            "at rest, and global distribution."
        ),
        "relevance": (
            "Primary storage backend for conversations, memory, and skills — "
            "partitioned by user_id for data isolation."
        ),
        "modules": ["storage", "memory_store", "skills_store"],
    },

    "msal_browser": {
        "id": "msal_browser",
        "title": "MSAL.js for Single-Page Applications",
        "authors": "Microsoft Identity Platform",
        "year": 2020,
        "venue": "GitHub / npm",
        "arxiv_id": None,
        "doi": None,
        "url": "https://github.com/AzureAD/microsoft-authentication-library-for-js/tree/dev/lib/msal-browser",
        "abstract_short": (
            "Microsoft Authentication Library for browser-based SPAs; "
            "handles Entra ID OAuth 2.0 / OIDC token acquisition."
        ),
        "relevance": (
            "Frontend SSO — MSAL PublicClientApplication acquires Bearer "
            "tokens validated by backend auth.py (RS256 JWT)."
        ),
        "modules": ["auth"],
    },

    "pyjwt": {
        "id": "pyjwt",
        "title": "PyJWT — JSON Web Token Implementation in Python",
        "authors": "Padilla, J. (maintainer)",
        "year": 2015,
        "venue": "PyPI / GitHub",
        "arxiv_id": None,
        "doi": None,
        "url": "https://pyjwt.readthedocs.io/en/stable/",
        "abstract_short": (
            "JWT encoding/decoding library; supports RS256 with "
            "cryptography backend for JWKS validation."
        ),
        "relevance": (
            "Backend Entra ID JWT validation — downloads JWKS, "
            "verifies RS256 signatures, issuer, audience, expiry."
        ),
        "modules": ["auth"],
    },

    "wcag30": {
        "id": "wcag30",
        "title": "Web Content Accessibility Guidelines 3.0 (Working Draft)",
        "authors": "W3C Accessibility Guidelines Working Group",
        "year": 2024,
        "venue": "W3C",
        "arxiv_id": None,
        "doi": None,
        "url": "https://www.w3.org/TR/wcag-3.0/",
        "abstract_short": (
            "Next-generation accessibility standard; introduces APCA "
            "contrast model and outcome-based conformance."
        ),
        "relevance": (
            "Frontend accessibility — dual-theme system (Night/Day) "
            "targeting APCA Lc ≥ 90, focus ring, reduced-motion, "
            "forced-colors, semantic landmarks, 89 automated tests."
        ),
        "modules": [],
    },

    "apca": {
        "id": "apca",
        "title": "Advanced Perceptual Contrast Algorithm (APCA)",
        "authors": "Somers, A.",
        "year": 2022,
        "venue": "W3C / GitHub",
        "arxiv_id": None,
        "doi": None,
        "url": "https://github.com/Myndex/SAPC-APCA",
        "abstract_short": (
            "Perceptual contrast algorithm that replaces WCAG 2.x "
            "contrast ratio with lightness-difference (Lc) model."
        ),
        "relevance": (
            "Frontend contrast validation — Dark theme Lc 93.5, "
            "Light theme Lc 94.7 (verified in automated a11y tests)."
        ),
        "modules": [],
    },

    # ── Design Patterns & Architecture ───────────────────────────────

    "circuit_breaker_pattern": {
        "id": "circuit_breaker_pattern",
        "title": "Circuit Breaker Pattern",
        "authors": "Nygard, M. (Release It!, 2007)",
        "year": 2007,
        "venue": "Pragmatic Bookshelf",
        "arxiv_id": None,
        "doi": None,
        "url": "https://martinfowler.com/bliki/CircuitBreaker.html",
        "abstract_short": (
            "Self-healing pattern that prevents cascading failures by "
            "tracking error rates and temporarily disabling failing services."
        ),
        "relevance": (
            "Resilience subsystem — per-model circuit breakers in "
            "resilience.py skip OPEN-circuit models and attempt fallbacks."
        ),
        "modules": ["resilience", "openrouter"],
    },

    "speculative_execution": {
        "id": "speculative_execution",
        "title": "Speculative Execution / Racing Pattern",
        "authors": "Dean, J. & Barroso, L. A.",
        "year": 2013,
        "venue": "Communications of the ACM, 56(2)",
        "arxiv_id": None,
        "doi": "10.1145/2408776.2408794",
        "url": "https://doi.org/10.1145/2408776.2408794",
        "abstract_short": (
            "Hedged requests / speculative execution to reduce tail "
            "latency in distributed systems."
        ),
        "relevance": (
            "Stage 3 speculative racing — chairman + racer fired in "
            "parallel; first responder wins, loser is cancelled."
        ),
        "modules": ["council"],
    },

    "kill_switch_pattern": {
        "id": "kill_switch_pattern",
        "title": "Kill Switch / Emergency Stop Pattern",
        "authors": "Various (Site Reliability Engineering)",
        "year": 2016,
        "venue": "O'Reilly (Google SRE Book)",
        "arxiv_id": None,
        "doi": None,
        "url": "https://sre.google/sre-book/table-of-contents/",
        "abstract_short": (
            "Emergency stop mechanism for runaway requests; enables "
            "per-session and global halt signals."
        ),
        "relevance": (
            "Kill switch in resilience.py — per-session and global halt "
            "gates checked at every stage boundary."
        ),
        "modules": ["resilience", "council", "main"],
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def get_citation(citation_id: str) -> Optional[Dict[str, Any]]:
    """Return a single citation by ID, or None if not found."""
    return CITATIONS.get(citation_id)


def list_all() -> List[Dict[str, Any]]:
    """Return all citations sorted by year (newest first), then by ID."""
    return sorted(
        CITATIONS.values(),
        key=lambda c: (-c.get("year", 0), c.get("id", "")),
    )


def get_by_module(module_name: str) -> List[Dict[str, Any]]:
    """Return all citations that influence a given backend module."""
    return [
        c for c in CITATIONS.values()
        if module_name in c.get("modules", [])
    ]


def get_by_year(year: int) -> List[Dict[str, Any]]:
    """Return all citations from a specific publication year."""
    return [c for c in CITATIONS.values() if c.get("year") == year]


def search(query: str) -> List[Dict[str, Any]]:
    """Case-insensitive full-text search across title, abstract, and relevance."""
    q = query.lower()
    results = []
    for c in CITATIONS.values():
        searchable = " ".join([
            c.get("title", ""),
            c.get("abstract_short", ""),
            c.get("relevance", ""),
            c.get("id", ""),
        ]).lower()
        if q in searchable:
            results.append(c)
    return results


# ── Formatting Helpers ───────────────────────────────────────────────

def format_apa(citation_id: str) -> Optional[str]:
    """
    Format a citation in APA 7th edition style.

    Example:
        Geng, S., He, J., & Trotta, R. (2024). Are Large Language Models
        Chameleons? arXiv preprint arXiv:2405.19323.
        https://arxiv.org/abs/2405.19323
    """
    c = CITATIONS.get(citation_id)
    if not c:
        return None
    parts = [f"{c['authors']} ({c['year']}). {c['title']}."]
    if c.get("venue"):
        parts.append(f" {c['venue']}.")
    if c.get("arxiv_id"):
        parts.append(f" arXiv:{c['arxiv_id']}.")
    if c.get("doi"):
        parts.append(f" https://doi.org/{c['doi']}")
    elif c.get("url"):
        parts.append(f" {c['url']}")
    return "".join(parts)


def format_bibtex(citation_id: str) -> Optional[str]:
    """
    Format a citation as a BibTeX entry.

    Example:
        @article{geng2024chameleons,
          title   = {Are Large Language Models Chameleons?},
          author  = {Geng, S., He, J., & Trotta, R.},
          year    = {2024},
          journal = {arXiv preprint},
          url     = {https://arxiv.org/abs/2405.19323},
        }
    """
    c = CITATIONS.get(citation_id)
    if not c:
        return None
    entry_type = "article" if c.get("arxiv_id") else "misc"
    lines = [
        f"@{entry_type}{{{c['id']},",
        f"  title   = {{{c['title']}}},",
        f"  author  = {{{c['authors']}}},",
        f"  year    = {{{c['year']}}},",
    ]
    if c.get("venue"):
        lines.append(f"  journal = {{{c['venue']}}},")
    if c.get("doi"):
        lines.append(f"  doi     = {{{c['doi']}}},")
    if c.get("url"):
        lines.append(f"  url     = {{{c['url']}}},")
    if c.get("arxiv_id"):
        lines.append(f"  eprint  = {{{c['arxiv_id']}}},")
    lines.append("}")
    return "\n".join(lines)


def format_markdown_table() -> str:
    """
    Render the full citation registry as a Markdown table.
    Useful for README / documentation generation.
    """
    rows = ["| ID | Title | Year | arXiv | Modules |", "| --- | --- | --- | --- | --- |"]
    for c in list_all():
        arxiv = c.get("arxiv_id") or "—"
        mods = ", ".join(c.get("modules", [])) or "—"
        rows.append(f"| `{c['id']}` | {c['title']} | {c['year']} | {arxiv} | {mods} |")
    return "\n".join(rows)


def generate_references_section() -> str:
    """
    Generate a Markdown REFERENCES section suitable for appending to
    documentation or exported PDFs.
    """
    lines = ["## References\n"]
    for i, c in enumerate(list_all(), 1):
        apa = format_apa(c["id"])
        lines.append(f"{i}. {apa}\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Registry Statistics
# ═══════════════════════════════════════════════════════════════════════

def stats() -> Dict[str, Any]:
    """Return summary statistics about the citation registry."""
    all_cites = list(CITATIONS.values())
    all_modules: set = set()
    for c in all_cites:
        all_modules.update(c.get("modules", []))
    years = [c["year"] for c in all_cites]
    return {
        "total_citations": len(all_cites),
        "year_range": f"{min(years)}–{max(years)}" if years else "—",
        "modules_covered": sorted(all_modules),
        "arxiv_papers": sum(1 for c in all_cites if c.get("arxiv_id")),
        "frameworks": sum(1 for c in all_cites if not c.get("arxiv_id")),
    }
