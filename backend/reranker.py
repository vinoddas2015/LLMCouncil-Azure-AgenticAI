"""
MedCPT Neural Reranker — Medical-domain citation reranking via DeepMind MedCPT.

Uses the Bayer myGenAssist MedCPT reranker (deepmind/medcpt) to replace
static relevance scores with query-aware neural relevance for pharma evidence.

The reranker is a medical cross-encoder that understands biomedical language,
drug–disease relationships, and clinical context — producing dramatically better
citation ordering than static per-source scoring.

API: POST https://chat.int.bayer.com/api/v2/rerank
Model: deepmind/medcpt (also supports Cohere-rerank-v3-5-mga as fallback)

Integration point:
  run_evidence_skills() → collect citations → **rerank_citations()** → sort → cap → chairman

Graceful degradation: If the reranker fails, the pipeline falls back to the
original static relevance scores (no breakage).
"""

import httpx
import logging
import asyncio
from typing import List, Optional
from dataclasses import dataclass

from .config import OPENROUTER_API_KEY

logger = logging.getLogger("skills.reranker")

# ── Configuration ────────────────────────────────────────────────
RERANK_API_URL = "https://chat.int.bayer.com/api/v2/rerank"
MEDCPT_MODEL = "deepmind/medcpt"
FALLBACK_RERANK_MODEL = "Cohere-rerank-v3-5-mga"
RERANK_TIMEOUT = 10.0  # seconds — reranking should be fast
MAX_RERANK_DOCS = 50   # MedCPT can handle ~100+ but we cap for latency
RERANK_ENABLED = True   # Master toggle — set False to disable without code change

# Minimum score threshold: citations below this are dropped as irrelevant
RELEVANCE_FLOOR = 0.01


async def rerank_citations(
    query: str,
    citations: list,
    top_n: Optional[int] = None,
    model: str = MEDCPT_MODEL,
) -> list:
    """
    Rerank a list of Citation objects using MedCPT neural reranker.

    Args:
        query:     The user's original question (used as the query).
        citations: List of Citation dataclass instances (from skills).
        top_n:     Max citations to return (None = return all, re-scored).
        model:     Reranker model ID on myGenAssist.

    Returns:
        The same Citation list, re-ordered and with `relevance` updated
        to reflect MedCPT scores.  Falls back to the original list on error.
    """
    if not RERANK_ENABLED:
        logger.debug("[MedCPT] Reranking disabled — using static scores.")
        return citations

    if not citations:
        return citations

    # No point reranking a single citation
    if len(citations) <= 1:
        logger.debug("[MedCPT] Only %d citation(s) — skipping rerank.", len(citations))
        return citations

    if not OPENROUTER_API_KEY:
        logger.warning("[MedCPT] No API key — skipping reranking.")
        return citations

    # Build document strings: "SOURCE — Title: Snippet" gives the cross-encoder
    # both source authority signal and content signal.
    documents = [
        f"{c.source} — {c.title}: {c.snippet}"
        for c in citations
    ]

    # Cap to avoid timeout on very large citation sets
    truncated = len(documents) > MAX_RERANK_DOCS
    if truncated:
        documents = documents[:MAX_RERANK_DOCS]
        logger.info(f"[MedCPT] Truncated to {MAX_RERANK_DOCS} docs for reranking.")

    payload = {
        "model": model,
        "query": query,
        "documents": documents,
    }
    if top_n:
        payload["top_n"] = top_n

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(http2=True, timeout=RERANK_TIMEOUT, verify=False) as client:
            response = await client.post(
                RERANK_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("data", [])
        if not results:
            logger.warning("[MedCPT] Empty results — keeping static scores.")
            return citations

        # Build index → score mapping
        score_map = {
            item["index"]: item["score"]
            for item in results
            if "index" in item and "score" in item
        }

        # Update citation relevance scores
        reranked = []
        for i, citation in enumerate(citations[:MAX_RERANK_DOCS]):
            if i in score_map:
                citation.relevance = score_map[i]
            reranked.append(citation)

        # Add back any citations beyond MAX_RERANK_DOCS (keep original scores)
        if truncated:
            reranked.extend(citations[MAX_RERANK_DOCS:])

        # Sort by new neural relevance (descending)
        reranked.sort(key=lambda c: c.relevance, reverse=True)

        # Drop citations below the relevance floor
        before_filter = len(reranked)
        reranked = [c for c in reranked if c.relevance >= RELEVANCE_FLOOR]
        dropped = before_filter - len(reranked)

        if dropped:
            logger.info(
                f"[MedCPT] Dropped {dropped} citation(s) below relevance floor "
                f"({RELEVANCE_FLOOR})."
            )

        logger.info(
            f"[MedCPT] Reranked {len(reranked)} citations "
            f"(top score: {reranked[0].relevance:.4f}, "
            f"bottom: {reranked[-1].relevance:.4f})"
            if reranked else "[MedCPT] All citations filtered out."
        )

        return reranked

    except httpx.TimeoutException:
        logger.warning(
            f"[MedCPT] Timeout after {RERANK_TIMEOUT}s — falling back to static scores."
        )
        return citations

    except httpx.HTTPStatusError as e:
        logger.warning(
            f"[MedCPT] HTTP {e.response.status_code} — "
            f"attempting fallback model {FALLBACK_RERANK_MODEL}..."
        )
        # Try fallback reranker (Cohere)
        if model != FALLBACK_RERANK_MODEL:
            return await rerank_citations(
                query, citations, top_n, model=FALLBACK_RERANK_MODEL,
            )
        logger.warning("[MedCPT] Fallback also failed — using static scores.")
        return citations

    except Exception as e:
        logger.warning(f"[MedCPT] Unexpected error: {e} — using static scores.")
        return citations
