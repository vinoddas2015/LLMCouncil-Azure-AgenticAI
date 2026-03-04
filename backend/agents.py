"""
Agent Team for LLM Council — Specialized Role-Based Analysis.

Each agent is a focused expert that analyses the council pipeline
from a distinct perspective.  Agents run post-pipeline and produce
structured insights that feed into the Prompt Atlas dashboard.

Agent Roster (9 Core + 3 VP-mode)
──────────────────────────────────
  🔬  Research Analyst     — Extracts key findings, data density, topic coverage
  🛡️  Fact Checker         — Validates claims against evidence, detects hallucinations
  ⚠️  Risk Assessor        — Evaluates safety signals, regulatory compliance flags
  🔍  Pattern Scout        — Detects recurring themes, emerging signals across sessions
  💡  Insight Synthesizer  — Generates novel connections and strategic observations
  📊  Quality Auditor      — Scores response quality, completeness, actionability
  🔗  Citation Supervisor  — Validates references, enriches with PubMed/DOI links
  🧰  Skills Manager       — Monitors 28-skill evidence pipeline health & diversity
  🧠  Memory Orchestrator  — Orchestrates 3-tier memory (Semantic/Episodic/Procedural)

VP-mode (activated for value-proposition queries):
  🏷️  Market Positioning   — Competitive landscape & differentiation
  🏥  Clinical Value       — Clinical evidence strength & safety profile
  📣  Messaging Strategist — Communication strategy & audience targeting

All agents are pure async functions — stateless per-request, horizontally
scalable, and suitable for serverless deployment.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_council.agents")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Agent Result Schema                                                ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _agent_result(
    agent_id: str,
    role: str,
    icon: str,
    signals: List[Dict[str, Any]],
    summary: str,
    confidence: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Standard envelope for every agent output."""
    return {
        "agent_id": agent_id,
        "role": role,
        "icon": icon,
        "summary": summary,
        "confidence": round(min(1.0, max(0.0, confidence)), 3),
        "signals": signals,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _signal(
    kind: str,
    severity: str,
    title: str,
    detail: str,
    evidence: Optional[str] = None,
) -> Dict[str, Any]:
    """Standard signal entry."""
    s = {
        "kind": kind,        # e.g. "pattern", "risk", "insight", "quality", "fact"
        "severity": severity, # "info" | "success" | "warning" | "critical"
        "title": title,
        "detail": detail,
    }
    if evidence:
        s["evidence"] = evidence
    return s


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🔬 Research Analyst Agent                                          ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def research_analyst_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Analyses research depth: topic coverage, data density, evidence breadth.
    """
    signals = []

    # ── Topic Coverage ──────────────────────────────────────────────
    total_words = sum(
        len((r.get("response") or "").split()) for r in stage1_results
    )
    model_count = len(stage1_results)
    avg_words = total_words // max(model_count, 1)

    if avg_words > 400:
        signals.append(_signal(
            "pattern", "success",
            "High Research Depth",
            f"Average {avg_words} words/model across {model_count} models — comprehensive coverage.",
        ))
    elif avg_words < 100:
        signals.append(_signal(
            "pattern", "warning",
            "Low Response Depth",
            f"Average {avg_words} words/model — responses may lack detail.",
        ))

    # ── Evidence Integration ────────────────────────────────────────
    citations = (evidence_bundle or {}).get("citations", [])
    skills_used = (evidence_bundle or {}).get("skills_used", [])
    if citations:
        source_types = set(c.get("source", "unknown") for c in citations)
        signals.append(_signal(
            "insight", "info",
            f"{len(citations)} Evidence Sources",
            f"Skills: {', '.join(skills_used)}. Source types: {', '.join(source_types)}.",
        ))
    else:
        signals.append(_signal(
            "pattern", "warning",
            "No Supporting Evidence",
            "No external citations retrieved — answer relies purely on model training data.",
        ))

    # ── Synthesis Quality ───────────────────────────────────────────
    s3_text = (stage3_result or {}).get("response", "")
    s3_words = len(s3_text.split())
    has_tables = "| " in s3_text and " | " in s3_text
    has_refs = bool(re.search(r'\[(?:FDA|CT|PM|EMA|WHO|UP|CB|KG|RC|RX|STR|HUB|WEB|SS|CR|EPMC|AX|PAT|WIKI|ORC|OA|UPW|ELS|BRX|MRX|OECD|EPTS|DPNG)-\w+\]', s3_text))
    has_math = "$" in s3_text or "\\(" in s3_text
    has_smiles = "```smiles" in s3_text

    richness_features = sum([has_tables, has_refs, has_math, has_smiles])
    if richness_features >= 3:
        signals.append(_signal(
            "insight", "success",
            "Rich Scientific Output",
            f"Synthesis includes tables, references, equations, and/or molecular structures.",
        ))

    confidence = min(1.0, (avg_words / 400) * 0.5 + (len(citations) / 10) * 0.3 + (richness_features / 4) * 0.2)

    return _agent_result(
        agent_id="research_analyst",
        role="Research Analyst",
        icon="🔬",
        signals=signals,
        summary=f"{model_count} models · {total_words} total words · {len(citations)} citations",
        confidence=confidence,
        metadata={
            "total_words": total_words,
            "avg_words_per_model": avg_words,
            "model_count": model_count,
            "citation_count": len(citations),
            "richness_features": richness_features,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🛡️ Fact Checker Agent                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def fact_checker_agent(
    stage2_results: List[Dict[str, Any]],
    grounding_scores: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validates claims, checks for hallucination signals, and
    assesses inter-model agreement.
    """
    signals = []

    # ── Grounding Score Analysis ────────────────────────────────────
    overall = grounding_scores.get("overall_score", 0)
    per_response = grounding_scores.get("per_response", [])

    if overall >= 80:
        signals.append(_signal(
            "fact", "success",
            f"Strong Grounding: {overall:.0f}%",
            "High inter-model agreement — claims are well-supported across reviewers.",
        ))
    elif overall >= 60:
        signals.append(_signal(
            "fact", "warning",
            f"Moderate Grounding: {overall:.0f}%",
            "Some disagreement among reviewers — critical claims should be verified.",
        ))
    else:
        signals.append(_signal(
            "fact", "critical",
            f"Low Grounding: {overall:.0f}%",
            "Significant disagreement — high hallucination risk. Manual review required.",
        ))

    # ── Claim Analysis Across Reviewers ─────────────────────────────
    total_tp, total_fp, total_fn = 0, 0, 0
    for s2 in stage2_results:
        claims = s2.get("claim_counts", {})
        for label, counts in claims.items():
            total_tp += counts.get("tp", 0)
            total_fp += counts.get("fp", 0)
            total_fn += counts.get("fn", 0)

    if total_fp > 0:
        signals.append(_signal(
            "risk", "warning" if total_fp <= 3 else "critical",
            f"{total_fp} False Positive Claims Detected",
            "Reviewers flagged potentially incorrect or hallucinated claims.",
            evidence=f"TP: {total_tp}, FP: {total_fp}, FN: {total_fn}",
        ))

    if total_fn > 0:
        signals.append(_signal(
            "risk", "warning",
            f"{total_fn} Missing Claims (False Negatives)",
            "Important information was omitted by one or more responses.",
        ))

    if total_fp == 0 and total_fn == 0 and total_tp > 0:
        signals.append(_signal(
            "fact", "success",
            "Clean Claim Profile",
            f"All {total_tp} claims verified — no hallucinations or omissions detected.",
        ))

    # ── Score Variance ──────────────────────────────────────────────
    if per_response:
        scores = [r.get("grounding_score", 0) for r in per_response]
        if max(scores) - min(scores) > 30:
            signals.append(_signal(
                "pattern", "warning",
                "High Response Score Variance",
                f"Scores range from {min(scores):.0f}% to {max(scores):.0f}% — models strongly disagree.",
            ))

    confidence = overall / 100.0

    return _agent_result(
        agent_id="fact_checker",
        role="Fact Checker",
        icon="🛡️",
        signals=signals,
        summary=f"Grounding: {overall:.0f}% · TP: {total_tp} · FP: {total_fp} · FN: {total_fn}",
        confidence=confidence,
        metadata={
            "overall_grounding": overall,
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  ⚠️ Risk Assessor Agent                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def risk_assessor_agent(
    user_query: str,
    stage3_result: Dict[str, Any],
    grounding_scores: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates pharmaceutical safety signals, regulatory flags,
    and compliance indicators.
    """
    signals = []
    s3_text = (stage3_result or {}).get("response", "").lower()

    # ── Safety Signal Detection ─────────────────────────────────────
    safety_keywords = {
        "black box warning": "critical",
        "contraindication": "warning",
        "adverse event": "warning",
        "drug interaction": "warning",
        "hepatotoxicity": "critical",
        "cardiotoxicity": "critical",
        "nephrotoxicity": "critical",
        "teratogenic": "critical",
        "fatal": "critical",
        "withdrawn": "critical",
        "recalled": "critical",
        "fda warning": "warning",
        "ema warning": "warning",
        "off-label": "info",
        "phase i": "info",
        "phase ii": "info",
        "phase iii": "info",
        "phase iv": "info",
        "post-marketing": "info",
    }

    detected_safety = []
    for keyword, severity in safety_keywords.items():
        if keyword in s3_text:
            detected_safety.append((keyword, severity))

    critical_count = sum(1 for _, s in detected_safety if s == "critical")
    warning_count = sum(1 for _, s in detected_safety if s == "warning")

    if critical_count > 0:
        signals.append(_signal(
            "risk", "critical",
            f"{critical_count} Critical Safety Signal(s)",
            f"Detected: {', '.join(k for k, s in detected_safety if s == 'critical')}",
        ))

    if warning_count > 0:
        signals.append(_signal(
            "risk", "warning",
            f"{warning_count} Safety Warning(s)",
            f"Detected: {', '.join(k for k, s in detected_safety if s == 'warning')}",
        ))

    if critical_count == 0 and warning_count == 0:
        signals.append(_signal(
            "risk", "success",
            "No Safety Signals Detected",
            "No critical safety keywords found in the synthesis.",
        ))

    # ── Regulatory Phase Indicators ─────────────────────────────────
    phases = [kw for kw, _ in detected_safety if kw.startswith("phase ")]
    if phases:
        signals.append(_signal(
            "insight", "info",
            f"Clinical Trial Phase(s): {', '.join(p.title() for p in phases)}",
            "Clinical development stage referenced in the response.",
        ))

    # ── Evidence Grounding for Safety ───────────────────────────────
    overall = grounding_scores.get("overall_score", 0)
    if critical_count > 0 and overall < 70:
        signals.append(_signal(
            "risk", "critical",
            "Safety Claims Under-Grounded",
            f"Critical safety signals with only {overall:.0f}% grounding — high risk of inaccuracy.",
        ))

    risk_score = min(1.0, critical_count * 0.3 + warning_count * 0.15)
    confidence = max(0.0, 1.0 - risk_score)

    return _agent_result(
        agent_id="risk_assessor",
        role="Risk Assessor",
        icon="⚠️",
        signals=signals,
        summary=f"Safety: {critical_count} critical, {warning_count} warnings · {len(phases)} phases",
        confidence=confidence,
        metadata={
            "critical_signals": critical_count,
            "warning_signals": warning_count,
            "safety_keywords": [k for k, _ in detected_safety],
            "phases_detected": phases,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🔍 Pattern Scout Agent                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def pattern_scout_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    aggregate_rankings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Detects patterns across model responses: consensus areas, divergence
    points, and emerging themes.
    """
    signals = []

    # ── Consensus Detection ─────────────────────────────────────────
    if aggregate_rankings:
        top_model = aggregate_rankings[0]
        bottom_model = aggregate_rankings[-1]
        rank_spread = bottom_model.get("average_rank", 0) - top_model.get("average_rank", 0)

        top_name = (top_model.get("model", "unknown").split("/").pop())
        signals.append(_signal(
            "pattern", "info",
            f"Top Ranked: {top_name}",
            f"Average rank {top_model.get('average_rank', 0):.1f} across {top_model.get('rankings_count', 0)} reviews.",
        ))

        if rank_spread < 1.0:
            signals.append(_signal(
                "pattern", "success",
                "Strong Model Consensus",
                f"Rank spread: {rank_spread:.2f} — models broadly agree on response quality.",
            ))
        elif rank_spread > 2.5:
            signals.append(_signal(
                "pattern", "warning",
                "Divergent Rankings",
                f"Rank spread: {rank_spread:.2f} — significant disagreement among reviewers.",
            ))

    # ── Theme Detection (keyword frequency across responses) ────────
    all_text = " ".join((r.get("response") or "").lower() for r in stage1_results)
    pharma_themes = {
        "mechanism of action": 0, "pharmacokinetics": 0, "pharmacodynamics": 0,
        "clinical trial": 0, "safety profile": 0, "efficacy": 0,
        "bioavailability": 0, "half-life": 0, "dosing": 0,
        "metabolism": 0, "side effect": 0, "adverse": 0,
        "regulation": 0, "approval": 0, "indication": 0,
    }
    detected_themes = []
    for theme in pharma_themes:
        count = all_text.count(theme)
        if count > 0:
            pharma_themes[theme] = count
            detected_themes.append(theme)

    if detected_themes:
        top_themes = sorted(detected_themes, key=lambda t: pharma_themes[t], reverse=True)[:5]
        signals.append(_signal(
            "pattern", "info",
            f"{len(detected_themes)} Pharma Themes Detected",
            f"Top: {', '.join(t.title() for t in top_themes)}",
        ))

    # ── Rubric Trend Analysis ───────────────────────────────────────
    avg_rubric = {}
    rubric_count = 0
    for s2 in stage2_results:
        rubric = s2.get("rubric_scores", {})
        for label, scores in rubric.items():
            for crit, val in scores.items():
                avg_rubric.setdefault(crit, []).append(val)
            rubric_count += 1

    if avg_rubric:
        weakest = min(avg_rubric, key=lambda k: sum(avg_rubric[k]) / len(avg_rubric[k]))
        weakest_score = sum(avg_rubric[weakest]) / len(avg_rubric[weakest])
        strongest = max(avg_rubric, key=lambda k: sum(avg_rubric[k]) / len(avg_rubric[k]))
        strongest_score = sum(avg_rubric[strongest]) / len(avg_rubric[strongest])

        signals.append(_signal(
            "insight", "info",
            f"Strongest: {strongest.replace('_', ' ').title()} ({strongest_score:.0%})",
            f"Weakest: {weakest.replace('_', ' ').title()} ({weakest_score:.0%})",
        ))

    confidence = 0.5 + len(detected_themes) * 0.03 + (0.2 if aggregate_rankings else 0)

    return _agent_result(
        agent_id="pattern_scout",
        role="Pattern Scout",
        icon="🔍",
        signals=signals,
        summary=f"{len(detected_themes)} themes · {len(aggregate_rankings)} ranked models",
        confidence=min(1.0, confidence),
        metadata={
            "themes_detected": detected_themes,
            "rank_spread": (aggregate_rankings[-1].get("average_rank", 0) - aggregate_rankings[0].get("average_rank", 0)) if len(aggregate_rankings) >= 2 else 0,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  💡 Insight Synthesizer Agent                                       ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def insight_synthesizer_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    aggregate_rankings: List[Dict[str, Any]],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generates strategic insights by cross-referencing model outputs,
    evidence, and ranking patterns.
    """
    signals = []

    # ── Cross-Model Unique Insights ─────────────────────────────────
    # Identify information that appears in only one model's response
    model_texts = [(r.get("model", "").split("/").pop(), r.get("response", "")) for r in stage1_results]

    # Check if top-ranked model contributed unique information
    if aggregate_rankings and len(model_texts) >= 2:
        top_model_name = aggregate_rankings[0].get("model", "").split("/").pop()
        bottom_model_name = aggregate_rankings[-1].get("model", "").split("/").pop() if len(aggregate_rankings) > 1 else None

        top_words = set(model_texts[0][1].lower().split()) if model_texts else set()
        all_other_words = set()
        for name, text in model_texts[1:]:
            all_other_words.update(text.lower().split())

        unique_to_top = len(top_words - all_other_words)
        if unique_to_top > 50:
            signals.append(_signal(
                "insight", "info",
                "Top Model Offers Unique Perspective",
                f"{unique_to_top} unique terms in the #1 ranked response — distinctive analysis.",
            ))

    # ── Evidence to Response Gap Analysis ───────────────────────────
    citations = (evidence_bundle or {}).get("citations", [])
    s3_text = (stage3_result or {}).get("response", "")

    if citations:
        referenced = sum(1 for c in citations if c.get("id", "") in s3_text)
        unreferenced = len(citations) - referenced
        if unreferenced > 0:
            signals.append(_signal(
                "insight", "warning",
                f"{unreferenced} Unused Citations",
                "Evidence was retrieved but not referenced in the final synthesis — potential knowledge gap.",
            ))
        if referenced > 0:
            signals.append(_signal(
                "insight", "success",
                f"{referenced}/{len(citations)} Citations Integrated",
                "Chairman synthesis actively references retrieved evidence.",
            ))

    # ── Query Complexity Assessment ─────────────────────────────────
    query_words = len(user_query.split())
    has_comparison = any(w in user_query.lower() for w in ["compare", "versus", "vs", "difference", "between"])
    has_mechanism = any(w in user_query.lower() for w in ["mechanism", "how does", "pathway", "process"])
    has_safety = any(w in user_query.lower() for w in ["safety", "side effect", "risk", "adverse", "toxicity"])

    complexity_factors = sum([
        query_words > 20, has_comparison, has_mechanism, has_safety
    ])
    complexity_label = ["Simple", "Moderate", "Complex", "Highly Complex", "Expert-Level"][min(complexity_factors, 4)]
    signals.append(_signal(
        "insight", "info",
        f"Query Complexity: {complexity_label}",
        f"{query_words} words, {complexity_factors} complexity factor(s).",
    ))

    confidence = min(1.0, 0.4 + len(signals) * 0.12)

    return _agent_result(
        agent_id="insight_synthesizer",
        role="Insight Synthesizer",
        icon="💡",
        signals=signals,
        summary=f"Complexity: {complexity_label} · {len(citations)} citations · {len(signals)} insights",
        confidence=confidence,
        metadata={
            "query_complexity": complexity_label,
            "complexity_factors": complexity_factors,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📊 Quality Auditor Agent                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def quality_auditor_agent(
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    cost_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Audits response quality, completeness, and cost-effectiveness.
    """
    signals = []

    # ── Rubric Score Analysis ───────────────────────────────────────
    all_scores = {}
    for s2 in stage2_results:
        rubric = s2.get("rubric_scores", {})
        for label, scores in rubric.items():
            for crit, val in scores.items():
                all_scores.setdefault(crit, []).append(val)

    if all_scores:
        overall_avg = sum(
            sum(vs) / len(vs) for vs in all_scores.values()
        ) / len(all_scores)

        if overall_avg >= 0.8:
            signals.append(_signal(
                "quality", "success",
                f"High Quality Score: {overall_avg:.0%}",
                "Rubric evaluation shows strong performance across all criteria.",
            ))
        elif overall_avg >= 0.6:
            signals.append(_signal(
                "quality", "info",
                f"Moderate Quality: {overall_avg:.0%}",
                "Room for improvement in some evaluation criteria.",
            ))
        else:
            signals.append(_signal(
                "quality", "warning",
                f"Below-Average Quality: {overall_avg:.0%}",
                "Multiple criteria scored below expectations.",
            ))

        # Identify weakest criterion
        for crit, vals in all_scores.items():
            avg = sum(vals) / len(vals)
            if avg < 0.5:
                signals.append(_signal(
                    "quality", "warning",
                    f"Weak: {crit.replace('_', ' ').title()} ({avg:.0%})",
                    "This criterion needs attention for response improvement.",
                ))
    else:
        overall_avg = 0.5

    # ── Stage 3 Completeness ────────────────────────────────────────
    s3_text = (stage3_result or {}).get("response", "")
    s3_words = len(s3_text.split())
    has_headers = bool(re.search(r'^#{1,4}\s', s3_text, re.MULTILINE))
    has_structure = has_headers or "**" in s3_text
    has_conclusion = any(
        w in s3_text.lower()
        for w in ["in conclusion", "in summary", "to summarize", "overall", "key takeaway"]
    )

    completeness_score = sum([
        s3_words > 200,
        s3_words > 500,
        has_structure,
        has_conclusion,
    ]) / 4.0

    if completeness_score >= 0.75:
        signals.append(_signal(
            "quality", "success",
            "Complete & Well-Structured",
            f"{s3_words} words with headings and conclusion.",
        ))
    elif completeness_score <= 0.25:
        signals.append(_signal(
            "quality", "warning",
            "Synthesis May Be Incomplete",
            f"Only {s3_words} words — may lack depth or structure.",
        ))

    # ── Cost Efficiency ─────────────────────────────────────────────
    if cost_summary:
        total_tokens = cost_summary.get("total_tokens", 0)
        total_cost = cost_summary.get("total_cost_usd", 0)
        if total_tokens > 0 and total_cost > 0:
            signals.append(_signal(
                "quality", "info",
                f"Cost: ${total_cost:.4f} · {total_tokens:,} tokens",
                f"Across {cost_summary.get('models_used', 0)} models.",
            ))

    confidence = min(1.0, overall_avg * 0.6 + completeness_score * 0.4)

    return _agent_result(
        agent_id="quality_auditor",
        role="Quality Auditor",
        icon="📊",
        signals=signals,
        summary=f"Quality: {overall_avg:.0%} · Completeness: {completeness_score:.0%}",
        confidence=confidence,
        metadata={
            "overall_quality": round(overall_avg, 3),
            "completeness_score": round(completeness_score, 3),
            "synthesis_words": s3_words,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Query Mode Detection                                               ║
# ╚══════════════════════════════════════════════════════════════════════╝

VP_KEYWORDS = [
    "value proposition", "value prop", "competitive differentiation",
    "positioning", "market positioning", "brand messaging",
    "key messages", "messaging framework", "messaging strategy",
    "elevator pitch", "commercial strategy", "launch strategy",
    "product profile", "target product profile", "TPP",
    "competitive landscape", "competitor analysis", "competitive advantage",
    "unique selling", "USP", "unmet need", "patient population",
    "template", "one-pager", "sell sheet", "sales aid",
]

def detect_query_mode(user_query: str) -> str:
    """
    Detect the query mode based on keyword analysis.

    Returns:
        "value_proposition" — when user seeks VP / competitive / messaging content
        "pharma_pipeline"   — when 3+ pharma pipeline domains are detected (full pipeline)
        "pharma_intel"      — when 1+ pharma intelligence domains are detected
        "standard"          — default pharma council mode
    """
    q = user_query.lower()
    vp_score = sum(1 for kw in VP_KEYWORDS if kw in q)
    # Also trigger on structural indicators
    if any(phrase in q for phrase in [
        "challenge", "solution", "outcome",
        "mechanism of action", "clinical benefit",
        "safety profile", "target patient",
    ]):
        vp_score += 1

    if vp_score >= 2:
        return "value_proposition"

    # ── Check pharma intelligence domains ──
    pi_domains = detect_pharma_intel_query(q)
    active_domains = [d for d, v in pi_domains.items() if v]

    # 3+ domains → full pharma pipeline (all 7 agents)
    if len(active_domains) >= 3:
        return "pharma_pipeline"
    if len(active_domains) >= 1:
        return "pharma_intel"

    return "standard"


# ── Pharma Intelligence domain detection (used by agents) ─────────
_PI_AGENT_PATTERNS = {
    "ci": re.compile(
        r'competitor|competitive\s*intelligence|pipeline\s*track|'
        r'pfizer|alnylam|ionis|bridgebio|competitor\s*launch',
        re.IGNORECASE,
    ),
    "compliance": re.compile(
        r'compliance|promotional|off.?label|warning\s*letter|DDMAC|OPDP|'
        r'fair\s*balance|misleading|lanham|regulatory\s*action',
        re.IGNORECASE,
    ),
    "pubwatch": re.compile(
        r'pubwatch|new\s*data|recent\s*publicat|latest\s*(study|publicat)|'
        r'emerging\s*data|what.?s\s*new|publication\s*monitor',
        re.IGNORECASE,
    ),
    "claim_impact": re.compile(
        r'claim\s*impact|rx\s*uplift|prescription\s*impact|commercial\s*impact|'
        r'NNT\b|number\s*needed|endpoint\s*impact|formulary\s*impact',
        re.IGNORECASE,
    ),
    "market_access": re.compile(
        r'market\s*access|pricing|reimbursement|HTA\b|NICE\b|ICER\b|'
        r'AMNOG|G.BA|cost.?effective|QALY|generic\s*entry|payer',
        re.IGNORECASE,
    ),
    "product_expert": re.compile(
        r'acoramidis|tafamidis|vyndaqel|vutrisiran|amvuttra|'
        r'eplontersen|wainua|attr.?cm|attr.?pn|transthyretin|'
        r'cardiac\s*amyloid',
        re.IGNORECASE,
    ),
    "campaign": re.compile(
        r'campaign|press\s*release|PR\s*strategy|communication\s*plan|'
        r'key\s*message|media\s*brief|sales\s*aid|leave.?behind|'
        r'social\s*media|congress\s*presentation|brand\s*messaging|'
        r'headline|creative|channel\s*strategy',
        re.IGNORECASE,
    ),
    "education": re.compile(
        r'medical\s*education|MSL|training\s*material|slide\s*deck|'
        r'learning\s*objective|scientific\s*dialogue|HCP\s*training|'
        r'field\s*medical|advisory\s*board|KOL|key\s*opinion|'
        r'medical\s*affairs|scientific\s*exchange|same.day',
        re.IGNORECASE,
    ),
    "performance": re.compile(
        r'performance|analytics|LLM\s*visibility|search\s*optimiz|'
        r'favorability|sentiment|impact\s*monitor|KPI|'
        r'real.?time\s*impact|discoverability|search\s*rank',
        re.IGNORECASE,
    ),
}


def detect_pharma_intel_query(query: str) -> Dict[str, bool]:
    """Detect which pharma intelligence domains are relevant."""
    return {domain: bool(pat.search(query)) for domain, pat in _PI_AGENT_PATTERNS.items()}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🏷️  Market Positioning Agent (Value Proposition mode)              ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def market_positioning_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Analyses competitive positioning: differentiation, unmet needs,
    market landscape, and messaging gaps.
    """
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Differentiation Check ──
    diff_keywords = [
        "differentiat", "unique", "first-in-class", "best-in-class",
        "superior", "novel", "advantage", "unlike", "compared to",
    ]
    diff_count = sum(1 for kw in diff_keywords if kw in s3_lower)
    if diff_count >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Strong Differentiation: {diff_count} Positioning Claims",
            "The synthesis clearly articulates competitive advantages.",
        ))
    elif diff_count == 0:
        signals.append(_signal(
            "insight", "critical",
            "Missing Competitive Differentiation",
            "No differentiation language found — the value proposition lacks competitive positioning.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            f"Weak Differentiation ({diff_count} mention{'s' if diff_count != 1 else ''})",
            "Consider strengthening language around what makes this product unique vs. competitors.",
        ))

    # ── Unmet Need Articulation ──
    need_keywords = ["unmet need", "gap", "limitation", "current standard", "inadequa", "suboptimal"]
    need_count = sum(1 for kw in need_keywords if kw in s3_lower)
    if need_count >= 2:
        signals.append(_signal(
            "insight", "success",
            "Clear Unmet Need Articulation",
            "The response establishes why this product is needed in the market.",
        ))
    elif need_count == 0:
        signals.append(_signal(
            "insight", "warning",
            "Unmet Need Not Addressed",
            "Value propositions should articulate the therapeutic gap the product fills.",
        ))

    # ── Target Audience Definition ──
    audience_keywords = [
        "patient population", "target patient", "indicated for",
        "adults with", "patients with", "hcp", "healthcare professional",
        "oncolog", "cardiolog", "neurolog", "urolog",
    ]
    audience_hits = sum(1 for kw in audience_keywords if kw in s3_lower)
    if audience_hits >= 2:
        signals.append(_signal(
            "insight", "success",
            "Target Audience Well-Defined",
            "Clear identification of patient population and/or HCP audience.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "Target Audience Unclear",
            "Define the specific patient population and healthcare decision-makers.",
        ))

    # ── Competitor Mentions ──
    # Check if specific competitor drugs or classes are mentioned
    competitor_patterns = [
        r'\b(?:vs\.?|versus|compared to|competitor)\b',
        r'\b(?:standard of care|SOC|current treatment|existing therap)',
    ]
    comp_count = sum(
        len(re.findall(p, s3, re.IGNORECASE)) for p in competitor_patterns
    )
    if comp_count >= 2:
        signals.append(_signal(
            "insight", "success",
            f"Competitive Context: {comp_count} Comparisons",
            "Value proposition includes head-to-head competitive framing.",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            "Limited Competitive Framing",
            "Consider adding explicit competitor comparisons to strengthen positioning.",
        ))

    # Confidence based on differentiation depth
    confidence = min(1.0, 0.3 + diff_count * 0.1 + need_count * 0.1 + audience_hits * 0.08)

    return _agent_result(
        agent_id="market_positioning",
        role="Market Positioning",
        icon="🏷️",
        signals=signals,
        summary=f"Differentiation: {diff_count} claims · Unmet need: {'✓' if need_count >= 2 else '✗'} · Audience: {'✓' if audience_hits >= 2 else '✗'}",
        confidence=confidence,
        metadata={
            "differentiation_count": diff_count,
            "unmet_need_count": need_count,
            "audience_hits": audience_hits,
            "competitor_comparisons": comp_count,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  💊 Clinical Value Agent (Value Proposition mode)                   ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def clinical_value_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates clinical value dimensions: MoA clarity, efficacy data,
    safety narrative, and outcome evidence strength.
    """
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Mechanism of Action ──
    moa_keywords = [
        "mechanism of action", "moa", "binds to", "inhibit", "stabiliz",
        "agonist", "antagonist", "blockade", "modulate", "target",
        "receptor", "enzyme", "pathway", "kinase", "transthyretin",
    ]
    moa_count = sum(1 for kw in moa_keywords if kw in s3_lower)
    if moa_count >= 4:
        signals.append(_signal(
            "fact", "success",
            f"MoA Well-Described ({moa_count} terms)",
            "Mechanism of action is clearly articulated with scientific depth.",
        ))
    elif moa_count >= 2:
        signals.append(_signal(
            "fact", "info",
            f"MoA Partially Described ({moa_count} terms)",
            "Consider adding more detail on molecular target and downstream effects.",
        ))
    else:
        signals.append(_signal(
            "fact", "critical",
            "Missing Mechanism of Action",
            "Value propositions for pharmaceuticals MUST include MoA. This is a critical gap.",
        ))

    # ── Efficacy Evidence ──
    efficacy_keywords = [
        "efficacy", "response rate", "survival", "endpoint", "primary outcome",
        "hazard ratio", "HR", "CI", "confidence interval", "p-value", "p <",
        "statistically significant", "ATTR-ACT", "phase III", "phase 3",
        "mortality", "hospitalization", "composite endpoint",
    ]
    efficacy_count = sum(1 for kw in efficacy_keywords if kw in s3_lower)
    if efficacy_count >= 5:
        signals.append(_signal(
            "fact", "success",
            f"Strong Efficacy Data ({efficacy_count} data points)",
            "Robust clinical evidence with statistical endpoints and trial data.",
        ))
    elif efficacy_count >= 2:
        signals.append(_signal(
            "fact", "info",
            f"Moderate Efficacy Data ({efficacy_count} data points)",
            "Key trial results present but could benefit from more quantitative detail.",
        ))
    else:
        signals.append(_signal(
            "fact", "warning",
            "Weak Efficacy Evidence",
            "Value proposition needs stronger clinical outcome data to be persuasive.",
        ))

    # ── Safety Profile ──
    safety_keywords = [
        "safety", "adverse", "side effect", "tolerab", "well-tolerated",
        "contraindica", "warning", "precaution", "black box",
        "discontinu", "serious adverse", "treatment-emergent",
    ]
    safety_count = sum(1 for kw in safety_keywords if kw in s3_lower)
    if safety_count >= 3:
        signals.append(_signal(
            "fact", "success",
            f"Safety Profile Addressed ({safety_count} mentions)",
            "Balanced safety narrative including tolerability and key adverse events.",
        ))
    elif safety_count == 0:
        signals.append(_signal(
            "fact", "critical",
            "No Safety Information",
            "ALL pharmaceutical value propositions MUST address safety. Critical omission.",
        ))
    else:
        signals.append(_signal(
            "fact", "warning",
            f"Limited Safety Data ({safety_count} mention{'s' if safety_count != 1 else ''})",
            "Safety profile should be more comprehensively addressed.",
        ))

    # ── Clinical Trial Evidence Quality ──
    nct_matches = re.findall(r'NCT\d{8}', s3)
    trial_names = re.findall(r'(?:ATTR-ACT|APOLLO|ENDEAVOR|HELIOS|CARDIGAN|ATTRibute)', s3, re.IGNORECASE)
    if nct_matches or trial_names:
        signals.append(_signal(
            "fact", "success",
            f"Specific Trials Referenced: {len(nct_matches)} NCT + {len(trial_names)} named",
            f"Trials: {', '.join(set(nct_matches + trial_names))[:100]}",
        ))
    else:
        signals.append(_signal(
            "fact", "info",
            "No Specific Trial IDs",
            "Including NCT numbers or trial names strengthens evidence credibility.",
        ))

    confidence = min(1.0, 0.2 + moa_count * 0.06 + efficacy_count * 0.06 + safety_count * 0.06)

    return _agent_result(
        agent_id="clinical_value",
        role="Clinical Value",
        icon="💊",
        signals=signals,
        summary=f"MoA: {moa_count} terms · Efficacy: {efficacy_count} pts · Safety: {safety_count}",
        confidence=confidence,
        metadata={
            "moa_count": moa_count,
            "efficacy_count": efficacy_count,
            "safety_count": safety_count,
            "trials_referenced": len(nct_matches) + len(trial_names),
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📣 Messaging Strategist Agent (Value Proposition mode)             ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def messaging_strategist_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluates messaging quality: clarity, emotional resonance,
    audience appropriateness, and template structure.
    """
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Template Structure Detection ──
    has_challenge = any(w in s3_lower for w in ["challenge", "problem", "unmet need", "current limitation"])
    has_solution = any(w in s3_lower for w in ["solution", "approach", "how it works", "value proposition"])
    has_outcome = any(w in s3_lower for w in ["outcome", "result", "impact", "benefit", "transform"])

    structure_score = sum([has_challenge, has_solution, has_outcome])
    if structure_score == 3:
        signals.append(_signal(
            "insight", "success",
            "Complete Challenge → Solution → Outcome Structure",
            "The response follows the ideal value proposition framework.",
        ))
    elif structure_score >= 2:
        missing = []
        if not has_challenge: missing.append("Challenge")
        if not has_solution: missing.append("Solution")
        if not has_outcome: missing.append("Outcome")
        signals.append(_signal(
            "insight", "warning",
            f"Partial Structure — Missing: {', '.join(missing)}",
            "Consider restructuring to include Challenge → Solution → Outcome flow.",
        ))
    else:
        signals.append(_signal(
            "insight", "critical",
            "No Value Proposition Structure Detected",
            "Response lacks the Challenge → Solution → Outcome framework.",
        ))

    # ── Emotional Resonance & Patient Focus ──
    patient_focus = [
        "patient", "quality of life", "qol", "survivor", "caregiver",
        "hope", "empower", "live longer", "well-being", "burden",
        "meaningful", "purpose", "storytelling", "human",
    ]
    patient_hits = sum(1 for kw in patient_focus if kw in s3_lower)
    if patient_hits >= 4:
        signals.append(_signal(
            "insight", "success",
            f"Strong Patient-Centric Messaging ({patient_hits} indicators)",
            "The value proposition connects clinical data with patient impact.",
        ))
    elif patient_hits >= 2:
        signals.append(_signal(
            "insight", "info",
            f"Moderate Patient Focus ({patient_hits} indicators)",
            "More patient stories or QoL language could strengthen the message.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "Low Patient Voice",
            "Value propositions should connect science to human impact. Include patient-centric language.",
        ))

    # ── Audience Segmentation ──
    audiences = {
        "HCP": ["hcp", "physician", "doctor", "prescriber", "clinician", "oncologist"],
        "Payer": ["payer", "cost-effective", "pharmacoeconom", "QALY", "ICER", "budget impact"],
        "Patient": ["patient education", "patient-facing", "plain language", "health literacy"],
        "Internal": ["training", "field force", "sales team", "brand team", "medical affairs"],
    }
    detected_audiences = []
    for name, kws in audiences.items():
        if any(kw in s3_lower for kw in kws):
            detected_audiences.append(name)

    if len(detected_audiences) >= 2:
        signals.append(_signal(
            "insight", "success",
            f"Multi-Audience: {', '.join(detected_audiences)}",
            "Messaging addresses multiple stakeholder groups.",
        ))
    elif len(detected_audiences) == 1:
        signals.append(_signal(
            "insight", "info",
            f"Single Audience: {detected_audiences[0]}",
            "Consider adapting messages for additional audiences (HCP, Payer, Patient, Internal).",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "No Clear Audience Targeting",
            "Value propositions should specify which audience the messaging targets.",
        ))

    # ── Conciseness & Readability ──
    word_count = len(s3.split())
    sentence_count = len(re.findall(r'[.!?]+', s3))
    avg_sentence = word_count / max(sentence_count, 1)

    if avg_sentence <= 25:
        signals.append(_signal(
            "insight", "success",
            f"Good Readability (avg {avg_sentence:.0f} words/sentence)",
            "Concise sentences make the value proposition scannable and memorable.",
        ))
    elif avg_sentence > 40:
        signals.append(_signal(
            "insight", "warning",
            f"Low Readability (avg {avg_sentence:.0f} words/sentence)",
            "Long sentences reduce impact. Aim for 15-25 words per sentence.",
        ))

    confidence = min(1.0, 0.25 + structure_score * 0.15 + patient_hits * 0.05 + len(detected_audiences) * 0.08)

    return _agent_result(
        agent_id="messaging_strategist",
        role="Messaging Strategist",
        icon="📣",
        signals=signals,
        summary=f"Structure: {structure_score}/3 · Patient focus: {patient_hits} · Audiences: {len(detected_audiences)}",
        confidence=confidence,
        metadata={
            "structure_score": structure_score,
            "has_challenge": has_challenge,
            "has_solution": has_solution,
            "has_outcome": has_outcome,
            "patient_focus_count": patient_hits,
            "detected_audiences": detected_audiences,
            "avg_sentence_length": round(avg_sentence, 1),
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🔗 Citation Supervisor Agent                                       ║
# ╚══════════════════════════════════════════════════════════════════════╝

# ── Known journal abbreviations → full publisher URLs ────────────────
_JOURNAL_URLS: Dict[str, str] = {
    "n engl j med": "https://www.nejm.org",
    "new england journal of medicine": "https://www.nejm.org",
    "lancet": "https://www.thelancet.com",
    "jama": "https://jamanetwork.com",
    "bmj": "https://www.bmj.com",
    "nature": "https://www.nature.com",
    "science": "https://www.science.org",
    "proc natl acad sci": "https://www.pnas.org",
    "pnas": "https://www.pnas.org",
    "cell": "https://www.cell.com",
    "circulation": "https://www.ahajournals.org/journal/circ",
    "j clin oncol": "https://ascopubs.org/journal/jco",
    "blood": "https://ashpublications.org/blood",
    "j am chem soc": "https://pubs.acs.org/journal/jacsat",
    "ann intern med": "https://www.acpjournals.org/journal/aim",
    "eur heart j": "https://academic.oup.com/eurheartj",
    "j med chem": "https://pubs.acs.org/journal/jmcmar",
}


def _parse_references_section(text: str) -> List[Dict[str, Any]]:
    """
    Extract individual reference entries from a REFERENCES section in
    markdown text.  Returns a list of dicts:
        {index, raw, title, authors, journal_hint, year, has_url}
    """
    refs: List[Dict[str, Any]] = []
    # Find the REFERENCES section (case-insensitive)
    ref_match = re.search(
        r'(?:^|\n)#+\s*REFERENCES?\s*\n([\s\S]+?)(?:\n#+\s|\Z)',
        text, re.IGNORECASE,
    )
    if not ref_match:
        # Also try bold-header variant: **REFERENCES**
        ref_match = re.search(
            r'(?:^|\n)\*\*REFERENCES?\*\*\s*\n([\s\S]+?)(?:\n\*\*|\n#+\s|\Z)',
            text, re.IGNORECASE,
        )
    if not ref_match:
        return refs

    block = ref_match.group(1)

    # Split into numbered entries: "1. ...", "2. ...", etc.
    entries = re.split(r'\n\s*(?=\d+\.\s)', block)

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        idx_m = re.match(r'^(\d+)\.\s+', entry)
        idx = int(idx_m.group(1)) if idx_m else 0
        raw = entry

        # Extract italic title: *Some Title Here.* (not bold **...**)
        title_m = re.search(r'(?<!\*)\*(?!\*)([^*]{10,})\*(?!\*)', entry)
        title = title_m.group(1).rstrip('. ').strip() if title_m else ""

        # Extract authors (text before italic title)
        authors = ""
        if title_m:
            pre = entry[:title_m.start()]
            # Remove the index prefix
            pre = re.sub(r'^\d+\.\s+', '', pre)
            # Remove bold label like **ATTR-ACT Trial:**
            pre = re.sub(r'\*\*[^*]+\*\*:?\s*', '', pre)
            authors = pre.strip().rstrip(',').strip()

        # Extract year: four digits that look like a year (1900-2099)
        year_m = re.search(r'\b((?:19|20)\d{2})\b', entry)
        year = year_m.group(1) if year_m else ""

        # Check for journal abbreviation (text after closing * and before year)
        journal_hint = ""
        if title_m:
            post = entry[title_m.end():]
            # Take text up to the year
            j_m = re.match(r'\.?\s*([A-Za-z][A-Za-z\s&.]+?)\.?\s*\d{4}', post)
            if j_m:
                journal_hint = j_m.group(1).strip().rstrip('.')

        has_url = bool(re.search(r'https?://', entry))

        refs.append({
            "index": idx,
            "raw": raw,
            "title": title,
            "authors": authors,
            "journal_hint": journal_hint,
            "year": year,
            "has_url": has_url,
        })

    return refs


def _build_pubmed_url(title: str, authors: str = "", year: str = "") -> str:
    """Construct a PubMed search URL from article metadata."""
    from urllib.parse import quote_plus
    parts = []
    if title:
        parts.append(title)
    if authors:
        # Take first author surname
        first_author = authors.split(",")[0].split(" ")[-1].strip()
        if first_author and len(first_author) > 2:
            parts.append(first_author)
    if year:
        parts.append(year)
    query = " ".join(parts)
    return f"https://pubmed.ncbi.nlm.nih.gov/?term={quote_plus(query)}"


def enrich_stage3_citations(text: str) -> str:
    """
    Post-process Stage 3 markdown to ensure all REFERENCES have clickable
    links.  Detects bibliographic reference entries with italic article
    titles and wraps them in PubMed search links when no URL is present.

    Also linkifies standalone DOI patterns and bare PMIDs found anywhere in
    the text.

    This function is called in the SSE pipeline BEFORE the response is
    emitted to the frontend, so the user always sees clickable references.
    """
    if not text:
        return text

    from urllib.parse import quote_plus

    result = text

    # ── 1. Numbered reference entries: italic titles → PubMed ────────
    #    Pattern: "N. ...Author et al. *Article Title Here.* Journal. YYYY"
    #    Only matches italic text ≥15 chars in a numbered list item that
    #    doesn't already contain a markdown link around the title.
    def _linkify_ref_title(m):
        prefix = m.group(1)
        title  = m.group(2)
        suffix = m.group(3) or ""
        # Don't double-linkify
        if "](http" in prefix[-40:] or "](http" in (suffix or "")[:10]:
            return m.group(0)
        clean = title.rstrip(". ").strip()
        url = _build_pubmed_url(clean)
        return f"{prefix}[*{title}*]({url}){suffix}"

    result = re.sub(
        r'^(\s*\d+\.\s+.+?)(?<!\*)\*(?!\*)([^*\n]{15,})\*(?!\*)(\.?\s*)',
        _linkify_ref_title,
        result,
        flags=re.MULTILINE,
    )

    # ── 2. DOI patterns anywhere: doi:10.xxxx/... ────────────────────
    result = re.sub(
        r'(?<!\[)(?<!\()(?<!")(?:doi|DOI)[:\s]+(10\.\d{4,}/[^\s,;)\]]+)',
        lambda m: f"[doi:{m.group(1)}](https://doi.org/{m.group(1)})",
        result,
    )

    # ── 3. PMID mentions: PMID: 12345678 ────────────────────────────
    result = re.sub(
        r'(?<!\[)(?<!\()PMID[:\s]+(\d+)',
        lambda m: f"[PMID {m.group(1)}](https://pubmed.ncbi.nlm.nih.gov/{m.group(1)}/)",
        result,
        flags=re.IGNORECASE,
    )

    # ── 4. Bare URLs not already in markdown links ───────────────────
    result = re.sub(
        r'(?<!\]\()(?<!\()(?<!")(https?://[^\s)<>"]+)',
        lambda m: f"[{m.group(1)}]({m.group(1)})",
        result,
    )

    return result


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🔗 Async Citation URL Validator                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def _check_url(client, url: str, timeout: float = 8.0) -> Dict[str, Any]:
    """
    HEAD-check a single URL. Returns {url, reachable, status_code, redirect_url}.
    Falls back to GET with stream=True if HEAD is rejected (405/403).
    """
    import httpx

    for method in ("HEAD", "GET"):
        try:
            if method == "HEAD":
                resp = await client.head(url, timeout=timeout, follow_redirects=True)
            else:
                # GET with stream to avoid downloading large bodies
                resp = await client.get(url, timeout=timeout, follow_redirects=True)

            final_url = str(resp.url) if resp.url != url else None
            # Accept 2xx and 3xx as reachable
            if resp.status_code < 400:
                return {"url": url, "reachable": True, "status_code": resp.status_code, "redirect_url": final_url}

            # 405 Method Not Allowed → retry with GET
            if method == "HEAD" and resp.status_code in (405, 403):
                continue

            return {"url": url, "reachable": False, "status_code": resp.status_code, "redirect_url": None}
        except Exception:
            if method == "HEAD":
                continue
            return {"url": url, "reachable": False, "status_code": 0, "redirect_url": None}

    return {"url": url, "reachable": False, "status_code": 0, "redirect_url": None}


async def validate_and_fix_citations(text: str) -> str:
    """
    Async post-processor that verifies all URLs in the text are reachable.
    Broken URLs (4xx, 5xx, timeout) are replaced with PubMed search
    fallback links built from surrounding context (title, author, year).

    Called in the SSE pipeline AFTER enrich_stage3_citations() so all
    references already have links.

    Strategy:
      1. Extract all markdown links: [label](url)
      2. Fire parallel HEAD checks (max 15 concurrent, 8s timeout each)
      3. For broken links, build a PubMed search fallback from the label text
      4. Replace broken URLs in-place

    Total added latency: typically < 3s (parallel HEAD checks with timeout).
    """
    import httpx
    from urllib.parse import quote_plus

    if not text:
        return text

    # ── 1. Collect all markdown links ────────────────────────────────
    # Pattern: [any label](https://...)
    link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)')
    matches = list(link_pattern.finditer(text))
    if not matches:
        return text

    # Deduplicate URLs (same URL may appear multiple times)
    unique_urls = list({m.group(2) for m in matches})

    # Skip PubMed search URLs — these are our own generated fallbacks
    urls_to_check = [u for u in unique_urls if "pubmed.ncbi.nlm.nih.gov/?term=" not in u]
    if not urls_to_check:
        return text

    # ── 2. Parallel HEAD checks ──────────────────────────────────────
    logger.info(f"[Citation Validator] Checking {len(urls_to_check)} URLs...")
    url_results: Dict[str, Dict[str, Any]] = {}

    try:
        async with httpx.AsyncClient(
            http2=True,
            verify=False,
            limits=httpx.Limits(max_connections=15, max_keepalive_connections=5),
            headers={"User-Agent": "LLMCouncil-CitationValidator/1.0"},
        ) as client:
            tasks = [_check_url(client, url) for url in urls_to_check]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, dict):
                    url_results[r["url"]] = r
    except Exception as e:
        logger.warning(f"[Citation Validator] Client error: {e}")
        return text  # Non-fatal — return original text

    # ── 3. Replace broken URLs with PubMed fallbacks ─────────────────
    broken_count = 0
    fixed_count = 0

    def _replace_broken_link(m):
        nonlocal broken_count, fixed_count
        label = m.group(1)
        url = m.group(2)
        result = url_results.get(url)

        if result is None:
            return m.group(0)  # URL wasn't checked (PubMed fallback), keep as-is

        if result["reachable"]:
            return m.group(0)  # URL works, keep it

        broken_count += 1

        # Extract context from label for PubMed search
        # Strip markdown formatting from label
        clean_label = re.sub(r'[*_`]', '', label).strip()

        # If it's a DOI link, extract the DOI and try doi.org
        if "doi.org" in url:
            # DOI links should work — if doi.org is down, keep the link
            return m.group(0)

        # Build PubMed search URL from label context
        # Extract potential title (italic text in label) or use full label
        search_terms = clean_label
        # Trim to first 120 chars (PubMed search limit)
        if len(search_terms) > 120:
            search_terms = search_terms[:120]
        pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/?term={quote_plus(search_terms)}"

        fixed_count += 1
        return f"[{label}]({pubmed_url})"

    result = link_pattern.sub(_replace_broken_link, text)

    if broken_count > 0:
        logger.info(
            f"[Citation Validator] {broken_count} broken URL(s) detected, "
            f"{fixed_count} replaced with PubMed fallbacks"
        )

    return result


async def citation_supervisor_agent(
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    🔗 Citation Supervisor — validates and enriches reference links.

    Parses the REFERENCES section from Stage 3 output, verifies every
    entry has a clickable URL, and generates PubMed / DOI lookup links
    for entries that lack them.  Reports citation quality signals so
    the user can see how well-sourced the answer is.
    """
    signals: List[Dict[str, Any]] = []
    s3_text = (stage3_result or {}).get("response", "")

    if not s3_text:
        return _agent_result(
            agent_id="citation_supervisor",
            role="Citation Supervisor",
            icon="🔗",
            signals=[_signal("fact", "warning", "No Stage 3 Output", "Nothing to analyse.")],
            summary="No output",
            confidence=0.0,
        )

    # ── Parse REFERENCES section ─────────────────────────────────────
    refs = _parse_references_section(s3_text)
    total_refs = len(refs)
    linked_refs = sum(1 for r in refs if r["has_url"])
    unlinked_refs = total_refs - linked_refs

    # ── Check for inline citation tags ───────────────────────────────
    inline_tags = re.findall(
        r'\[(?:FDA|CT|PM|EMA|WHO|UP|CB|KG|RC|RX|STR|HUB|SS|CR|EPMC|WEB|AX|PAT|WIKI|ORC|OA|UPW|ELS|BRX|MRX|OECD|EPTS|DPNG)-\w+\]',
        s3_text,
    )
    unique_tags = set(inline_tags)
    evidence_citations = (evidence_bundle or {}).get("citations", [])
    evidence_ids = {c.get("id", "") for c in evidence_citations}
    # Tags actually backed by evidence
    grounded_tags = unique_tags & evidence_ids

    # ── Check for DOI / PMID in body text ────────────────────────────
    body_dois = re.findall(r'doi[:\s]+(10\.\d{4,}/[^\s,;)\]]+)', s3_text, re.I)
    body_pmids = re.findall(r'PMID[:\s]+(\d+)', s3_text, re.I)

    # ── Enriched reference metadata ──────────────────────────────────
    enriched: List[Dict[str, Any]] = []
    for r in refs:
        entry: Dict[str, Any] = {
            "index": r["index"],
            "title": r["title"],
            "authors": r["authors"],
            "journal": r["journal_hint"],
            "year": r["year"],
            "has_url": r["has_url"],
        }
        if not r["has_url"] and r["title"]:
            entry["pubmed_url"] = _build_pubmed_url(
                r["title"], r["authors"], r["year"]
            )
        enriched.append(entry)

    # ── Build signals ────────────────────────────────────────────────

    # Overall reference presence
    if total_refs == 0:
        signals.append(_signal(
            "fact", "warning",
            "No REFERENCES Section Found",
            "The synthesis does not include a REFERENCES section.  "
            "Users cannot verify the underlying evidence.",
        ))
    else:
        signals.append(_signal(
            "fact", "info",
            f"{total_refs} Reference(s) Detected",
            f"Found {total_refs} numbered entries in the REFERENCES section.",
        ))

    # Linkage quality
    if total_refs > 0 and unlinked_refs > 0:
        signals.append(_signal(
            "fact", "warning",
            f"{unlinked_refs}/{total_refs} References Lack URLs",
            "Some references are plain text without clickable links.  "
            "The Citation Supervisor has auto-generated PubMed lookup links.",
        ))
    elif total_refs > 0 and unlinked_refs == 0:
        signals.append(_signal(
            "fact", "success",
            "All References Have URLs",
            "Every reference entry already contains a clickable link.",
        ))

    # Inline citations
    if unique_tags:
        if grounded_tags == unique_tags:
            signals.append(_signal(
                "fact", "success",
                f"{len(unique_tags)} Inline Citation(s) Grounded",
                "All inline citation tags match evidence sources retrieved by the skills module.",
            ))
        else:
            orphan = unique_tags - grounded_tags
            signals.append(_signal(
                "fact", "warning",
                f"{len(orphan)} Orphan Citation Tag(s)",
                f"Tags without matching evidence: {', '.join(sorted(orphan))}",
            ))
    else:
        signals.append(_signal(
            "fact", "info",
            "No Inline Citation Tags",
            "The synthesis does not use [TAG] style inline citations.  "
            "Consider using evidence tags for traceability.",
        ))

    # DOI / PMID presence
    if body_dois or body_pmids:
        signals.append(_signal(
            "fact", "success",
            f"{len(body_dois)} DOI(s), {len(body_pmids)} PMID(s) Found",
            "Persistent identifiers detected — these are auto-linkified for the user.",
        ))

    # Confidence score
    if total_refs == 0 and not unique_tags:
        conf = 0.2
    else:
        link_ratio = linked_refs / max(total_refs, 1)
        tag_ratio = len(grounded_tags) / max(len(unique_tags), 1) if unique_tags else 0.5
        conf = 0.3 + link_ratio * 0.35 + tag_ratio * 0.35

    return _agent_result(
        agent_id="citation_supervisor",
        role="Citation Supervisor",
        icon="🔗",
        signals=signals,
        summary=(
            f"{total_refs} refs · {linked_refs} linked · "
            f"{len(unique_tags)} inline tags · {len(body_dois)} DOIs"
        ),
        confidence=min(1.0, conf),
        metadata={
            "total_references": total_refs,
            "linked_references": linked_refs,
            "unlinked_references": unlinked_refs,
            "enriched_references": enriched,
            "inline_tags": sorted(unique_tags),
            "grounded_tags": sorted(grounded_tags),
            "doi_count": len(body_dois),
            "pmid_count": len(body_pmids),
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧰 Skills Manager Agent                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝

# ── Skill registry (canonical list for health monitoring) ──────────
CORE_SKILLS = [
    {"id": "openfda",         "name": "OpenFDA",            "tag": "FDA",  "type": "core"},
    {"id": "clinicaltrials",  "name": "ClinicalTrials.gov", "tag": "CT",   "type": "core"},
    {"id": "pubmed",          "name": "PubMed",             "tag": "PM",   "type": "core"},
    {"id": "ema",             "name": "EMA",                "tag": "EMA",  "type": "core"},
    {"id": "who_atc",         "name": "WHO ATC",            "tag": "WHO",  "type": "core"},
    {"id": "uniprot",         "name": "UniProt",            "tag": "UP",   "type": "core"},
    {"id": "chembl",          "name": "ChEMBL",             "tag": "CB",   "type": "core"},
    {"id": "kegg",            "name": "KEGG",               "tag": "KG",   "type": "core"},
    {"id": "reactome",        "name": "Reactome",           "tag": "RC",   "type": "core"},
    {"id": "rxnorm",          "name": "RxNorm",             "tag": "RX",   "type": "core"},
    {"id": "string_db",       "name": "STRING-DB",          "tag": "STR",  "type": "core"},
    {"id": "hubble",          "name": "Hubble",             "tag": "HUB",  "type": "core"},
]

WEB_SKILLS = [
    {"id": "semantic_scholar", "name": "Semantic Scholar",  "tag": "SS",   "type": "web"},
    {"id": "crossref",         "name": "CrossRef",          "tag": "CR",   "type": "web"},
    {"id": "europe_pmc",       "name": "Europe PMC",        "tag": "EPMC", "type": "web"},
    {"id": "duckduckgo_sci",   "name": "DuckDuckGo Sci",    "tag": "WEB",  "type": "web"},
    {"id": "arxiv",            "name": "arXiv",             "tag": "AX",   "type": "web"},
    {"id": "google_patents",   "name": "Google Patents",    "tag": "PAT",  "type": "web"},
    {"id": "wikipedia",        "name": "Wikipedia",         "tag": "WIKI", "type": "web"},
    {"id": "orcid",            "name": "ORCID",             "tag": "ORC",  "type": "web"},
    {"id": "openalex",         "name": "OpenAlex",          "tag": "OA",   "type": "web"},
    {"id": "unpaywall",        "name": "Unpaywall",         "tag": "UPW",  "type": "web"},
    {"id": "elsevier",         "name": "Elsevier/Scopus",   "tag": "ELS",  "type": "web"},
    {"id": "biorxiv",          "name": "bioRxiv",           "tag": "BRX",  "type": "web"},
    {"id": "medrxiv",          "name": "medRxiv",           "tag": "MRX",  "type": "web"},
    {"id": "oecd_ai",          "name": "OECD.AI",           "tag": "OECD", "type": "web"},
    {"id": "endpoints_news",   "name": "Endpoints News",    "tag": "EPTS", "type": "web"},
    {"id": "doctor_penguin",   "name": "Doctor Penguin",    "tag": "DPNG", "type": "web"},
]

ALL_SKILLS = CORE_SKILLS + WEB_SKILLS


async def skills_manager_agent(
    evidence_bundle: Optional[Dict[str, Any]] = None,
    web_search_enabled: bool = False,
) -> Dict[str, Any]:
    """
    🧰 Skills Manager — monitors skill health, coverage, and performance.

    Analyses which skills returned results, which failed silently,
    overall evidence diversity, and provides recommendations for
    skill configuration improvements.
    """
    signals: List[Dict[str, Any]] = []

    if not evidence_bundle:
        return _agent_result(
            agent_id="skills_manager",
            role="Skills Manager",
            icon="🧰",
            signals=[_signal("quality", "warning", "No Evidence Bundle", "Skills were not executed for this query.")],
            summary="No skills data available",
            confidence=0.0,
        )

    skills_used = set(evidence_bundle.get("skills_used", []))
    citations = evidence_bundle.get("citations", [])
    benchmark = evidence_bundle.get("benchmark", {})
    total_found = evidence_bundle.get("total_found", 0)
    reranker_info = evidence_bundle.get("reranker", {})

    # ── Skill Coverage Analysis ─────────────────────────────────────
    expected_core = {s["name"] for s in CORE_SKILLS}
    active_core = skills_used & expected_core
    missing_core = expected_core - skills_used

    if len(active_core) == len(expected_core):
        signals.append(_signal(
            "quality", "success",
            f"All {len(expected_core)} Core Skills Active",
            f"Every core evidence source returned results: {', '.join(sorted(active_core))}.",
        ))
    elif len(missing_core) <= 2:
        signals.append(_signal(
            "quality", "info",
            f"{len(active_core)}/{len(expected_core)} Core Skills Active",
            f"Silent failures on: {', '.join(sorted(missing_core))}. "
            f"Query may not have relevant data in those sources.",
        ))
    else:
        signals.append(_signal(
            "quality", "warning",
            f"Low Core Coverage: {len(active_core)}/{len(expected_core)}",
            f"Multiple core skills returned no results: {', '.join(sorted(missing_core))}. "
            f"Check API connectivity or query relevance.",
        ))

    # ── Web Search Coverage ─────────────────────────────────────────
    if web_search_enabled:
        expected_web = {s["name"] for s in WEB_SKILLS}
        active_web = skills_used & expected_web
        missing_web = expected_web - skills_used

        if len(active_web) >= len(expected_web) - 2:
            signals.append(_signal(
                "quality", "success",
                f"Web Search: {len(active_web)}/{len(expected_web)} Active",
                f"Strong web coverage with {len(active_web)} sources.",
            ))
        else:
            signals.append(_signal(
                "quality", "info",
                f"Web Search: {len(active_web)}/{len(expected_web)} Active",
                f"Some web skills returned no results: {', '.join(sorted(missing_web))}.",
            ))
    else:
        signals.append(_signal(
            "quality", "info",
            "Web Search Disabled",
            f"{len(WEB_SKILLS)} additional web skills are available when web search is enabled.",
        ))

    # ── Evidence Diversity ──────────────────────────────────────────
    source_types = set(c.get("source", "unknown") for c in citations)
    if len(source_types) >= 5:
        signals.append(_signal(
            "insight", "success",
            f"High Evidence Diversity: {len(source_types)} Sources",
            f"Citations span {', '.join(sorted(source_types))} — strong multi-source grounding.",
        ))
    elif len(source_types) >= 3:
        signals.append(_signal(
            "insight", "info",
            f"Moderate Diversity: {len(source_types)} Sources",
            f"Evidence from: {', '.join(sorted(source_types))}.",
        ))
    elif total_found > 0:
        signals.append(_signal(
            "insight", "warning",
            f"Low Diversity: {len(source_types)} Source(s)",
            "Most evidence comes from a single source type — consider enabling web search.",
        ))

    # ── Performance Benchmarks ──────────────────────────────────────
    total_ms = benchmark.get("total_ms", 0)
    slowest_skill = ""
    slowest_ms = 0
    for key, val in benchmark.items():
        if key.endswith("_ms") and key != "total_ms" and key != "medcpt_rerank_ms":
            if val > slowest_ms:
                slowest_ms = val
                slowest_skill = key.replace("_ms", "").replace("_", " ").title()

    if total_ms > 0:
        if total_ms < 5000:
            signals.append(_signal(
                "quality", "success",
                f"Fast Evidence Retrieval: {total_ms:.0f}ms",
                f"All skills completed within {total_ms/1000:.1f}s.",
            ))
        elif total_ms < 15000:
            signals.append(_signal(
                "quality", "info",
                f"Evidence Retrieval: {total_ms:.0f}ms",
                f"Slowest skill: {slowest_skill} ({slowest_ms:.0f}ms).",
            ))
        else:
            signals.append(_signal(
                "quality", "warning",
                f"Slow Evidence Retrieval: {total_ms:.0f}ms",
                f"Bottleneck: {slowest_skill} ({slowest_ms:.0f}ms). Consider timeout tuning.",
            ))

    # ── Reranker Status ─────────────────────────────────────────────
    if reranker_info.get("active"):
        rerank_ms = reranker_info.get("latency_ms", 0)
        signals.append(_signal(
            "quality", "success",
            f"MedCPT Reranker Active ({rerank_ms:.0f}ms)",
            "Neural reranking improved citation relevance ordering.",
        ))
    else:
        signals.append(_signal(
            "quality", "info",
            "Static Ranking (MedCPT Inactive)",
            "Citations use per-source static relevance scores.",
        ))

    # ── Confidence ──────────────────────────────────────────────────
    coverage_ratio = len(active_core) / max(len(expected_core), 1)
    diversity_ratio = min(len(source_types) / 5.0, 1.0)
    conf = 0.3 + coverage_ratio * 0.35 + diversity_ratio * 0.25 + (0.1 if reranker_info.get("active") else 0)

    return _agent_result(
        agent_id="skills_manager",
        role="Skills Manager",
        icon="🧰",
        signals=signals,
        summary=(
            f"{len(skills_used)}/{len(ALL_SKILLS)} skills · "
            f"{total_found} citations · {len(source_types)} source types · "
            f"{total_ms:.0f}ms"
        ),
        confidence=min(1.0, conf),
        metadata={
            "total_skills": len(ALL_SKILLS),
            "core_skills": len(CORE_SKILLS),
            "web_skills": len(WEB_SKILLS),
            "skills_active": sorted(skills_used),
            "skills_silent": sorted(missing_core) if 'missing_core' in dir() else [],
            "source_diversity": len(source_types),
            "total_citations": total_found,
            "total_latency_ms": total_ms,
            "reranker_active": reranker_info.get("active", False),
            "web_search_enabled": web_search_enabled,
            "skill_registry": ALL_SKILLS,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧠 Memory Orchestrator Agent                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def memory_orchestrator_agent(
    user_query: str,
    stage3_result: Dict[str, Any],
    grounding_scores: Dict[str, Any],
    cost_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    🧠 Memory Orchestrator — monitors and orchestrates the three memory tiers
    (Semantic, Episodic, Procedural).

    Analyses memory utilisation, detects knowledge drift, evaluates
    learn/unlearn patterns, and provides health signals for each tier.
    """
    from .memory import get_memory_manager

    signals: List[Dict[str, Any]] = []
    mm = get_memory_manager()

    # ── Gather memory statistics ────────────────────────────────────
    try:
        stats = mm.stats()
    except Exception as e:
        logger.warning(f"[MemoryOrchestrator] Stats error: {e}")
        stats = {"semantic": {"total": 0, "active": 0, "unlearned": 0},
                 "episodic": {"total": 0, "active": 0, "unlearned": 0},
                 "procedural": {"total": 0, "active": 0, "unlearned": 0}}

    sem = stats.get("semantic", {})
    epi = stats.get("episodic", {})
    proc = stats.get("procedural", {})

    total_active = sem.get("active", 0) + epi.get("active", 0) + proc.get("active", 0)
    total_unlearned = sem.get("unlearned", 0) + epi.get("unlearned", 0) + proc.get("unlearned", 0)
    total_all = sem.get("total", 0) + epi.get("total", 0) + proc.get("total", 0)

    # ── Tier Health: Semantic Memory ────────────────────────────────
    if sem.get("active", 0) > 10:
        signals.append(_signal(
            "insight", "success",
            f"Semantic Memory: {sem['active']} Active Facts",
            "Rich domain knowledge base — council decisions benefit from accumulated facts.",
        ))
    elif sem.get("active", 0) > 0:
        signals.append(_signal(
            "insight", "info",
            f"Semantic Memory: {sem['active']} Active Facts",
            "Domain knowledge is accumulating. More deliberations will enrich the knowledge base.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "Semantic Memory Empty",
            "No domain facts stored yet. Run council deliberations and approve 'Learn' to build knowledge.",
        ))

    # ── Tier Health: Episodic Memory ────────────────────────────────
    if epi.get("active", 0) > 5:
        signals.append(_signal(
            "pattern", "success",
            f"Episodic Memory: {epi['active']} Deliberations",
            "Strong deliberation history — council can reference past decisions for consistency.",
        ))
    elif epi.get("active", 0) > 0:
        signals.append(_signal(
            "pattern", "info",
            f"Episodic Memory: {epi['active']} Deliberations",
            "Past deliberations recorded. History grows with each council session.",
        ))
    else:
        signals.append(_signal(
            "pattern", "info",
            "Episodic Memory: Starting Fresh",
            "No past deliberations stored. First council run — building session history.",
        ))

    # ── Tier Health: Procedural Memory ──────────────────────────────
    if proc.get("active", 0) > 3:
        signals.append(_signal(
            "insight", "success",
            f"Procedural Memory: {proc['active']} Workflows",
            "Learned procedures available — council uses established workflows for similar tasks.",
        ))
    elif proc.get("active", 0) > 0:
        signals.append(_signal(
            "insight", "info",
            f"Procedural Memory: {proc['active']} Workflows",
            "Some learned procedures stored. Ask 'how-to' style queries to build more.",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            "No Learned Procedures",
            "No procedural patterns stored. Procedures are learned from 'how-to' queries with high grounding.",
        ))

    # ── Unlearned / Drift Detection ─────────────────────────────────
    if total_unlearned > 0:
        unlearn_ratio = total_unlearned / max(total_all, 1)
        if unlearn_ratio > 0.3:
            signals.append(_signal(
                "risk", "warning",
                f"High Unlearn Rate: {total_unlearned}/{total_all} ({unlearn_ratio:.0%})",
                "Many memories have been unlearned — possible knowledge drift or quality issues.",
            ))
        else:
            signals.append(_signal(
                "risk", "info",
                f"{total_unlearned} Unlearned Memories",
                "Some memories were deprecated by user action — healthy knowledge curation.",
            ))

    # ── Memory Recall for Current Query ─────────────────────────────
    try:
        recalled = mm.recall_for_query(user_query, limit_per_tier=3)
        recall_total = recalled.get("total", 0)
        if recall_total > 0:
            sem_hits = len(recalled.get("semantic", []))
            epi_hits = len(recalled.get("episodic", []))
            proc_hits = len(recalled.get("procedural", []))
            signals.append(_signal(
                "insight", "success",
                f"Memory Augmentation: {recall_total} Retrieved",
                f"Semantic: {sem_hits}, Episodic: {epi_hits}, Procedural: {proc_hits} — "
                f"council was augmented with prior knowledge.",
            ))
        else:
            signals.append(_signal(
                "pattern", "info",
                "No Prior Memory Retrieved",
                "This query did not match any stored memories — answering from scratch.",
            ))
    except Exception as e:
        logger.debug(f"[MemoryOrchestrator] Recall test: {e}")
        signals.append(_signal(
            "quality", "info",
            "Memory Recall Unavailable",
            "Could not test memory retrieval for the current query.",
        ))

    # ── Grounding → Learning Readiness ──────────────────────────────
    overall_grounding = grounding_scores.get("overall_score", 0) / 100.0
    if overall_grounding >= 0.6:
        signals.append(_signal(
            "quality", "success",
            f"Learning Ready (Grounding: {overall_grounding:.0%})",
            "Grounding score exceeds threshold — this deliberation qualifies for automatic learning.",
        ))
    elif overall_grounding >= 0.4:
        signals.append(_signal(
            "quality", "info",
            f"Borderline Learning (Grounding: {overall_grounding:.0%})",
            "Grounding is moderate — semantic facts may be stored but with lower confidence.",
        ))
    else:
        signals.append(_signal(
            "quality", "warning",
            f"Too Low for Learning (Grounding: {overall_grounding:.0%})",
            "Grounding score below threshold — this session will NOT auto-learn to prevent bad data.",
        ))

    # ── Context Awareness Trends ────────────────────────────────────
    try:
        ca_trends = mm.get_ca_trends_all_models(limit_per_model=5)
        if ca_trends:
            degrading_models = []
            for model, snapshots in ca_trends.items():
                if len(snapshots) >= 2:
                    latest = snapshots[0].get("score") or snapshots[0].get("combined_score", 0)
                    oldest = snapshots[-1].get("score") or snapshots[-1].get("combined_score", 0)
                    if latest and oldest and (oldest - latest) > 0.15:
                        degrading_models.append(model)
            if degrading_models:
                signals.append(_signal(
                    "risk", "warning",
                    f"CA Degradation Detected: {len(degrading_models)} Model(s)",
                    f"Models showing declining self-awareness: {', '.join(degrading_models[:3])}. "
                    f"May indicate catastrophic forgetting.",
                ))
            elif len(ca_trends) > 0:
                signals.append(_signal(
                    "pattern", "success",
                    f"CA Tracking: {len(ca_trends)} Models Monitored",
                    "Context awareness trends stable across tracked models.",
                ))
    except Exception as e:
        logger.debug(f"[MemoryOrchestrator] CA trends: {e}")

    # ── Confidence ──────────────────────────────────────────────────
    has_memories = 1 if total_active > 0 else 0
    has_trend = 1 if total_all > 5 else 0
    conf = 0.3 + has_memories * 0.2 + has_trend * 0.15 + min(overall_grounding, 1.0) * 0.35

    return _agent_result(
        agent_id="memory_orchestrator",
        role="Memory Orchestrator",
        icon="🧠",
        signals=signals,
        summary=(
            f"S:{sem.get('active', 0)} E:{epi.get('active', 0)} P:{proc.get('active', 0)} active · "
            f"{total_unlearned} unlearned · grounding {overall_grounding:.0%}"
        ),
        confidence=min(1.0, conf),
        metadata={
            "tiers": {
                "semantic": sem,
                "episodic": epi,
                "procedural": proc,
            },
            "total_active": total_active,
            "total_unlearned": total_unlearned,
            "total_memories": total_all,
            "grounding_score": overall_grounding,
            "learning_eligible": overall_grounding >= 0.5,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🖼️  Image Quality Monitor Agent                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def image_quality_monitor_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    cost_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Monitors image generation subsystem health, provider availability,
    and export readiness.  Reports on image quality capabilities.
    """
    import os
    signals = []
    metadata: Dict[str, Any] = {}

    # ── Provider availability check ────────────────────────────────
    google_key = bool(os.getenv("GOOGLE_API_KEY"))
    azure_endpoint = bool(os.getenv("AZURE_OPENAI_ENDPOINT"))
    azure_key = bool(os.getenv("AZURE_OPENAI_KEY"))

    providers_available = []
    providers_unavailable = []

    if google_key:
        providers_available.append("Google Imagen 4.0 Fast")
        providers_available.append("Gemini Flash Image")
    else:
        providers_unavailable.append("Google Imagen 4.0 Fast")
        providers_unavailable.append("Gemini Flash Image")

    if azure_endpoint and azure_key:
        providers_available.append("Azure DALL-E")
    else:
        providers_unavailable.append("Azure DALL-E (not configured)")

    if providers_available:
        signals.append(_signal(
            "quality", "success",
            f"{len(providers_available)} Image Providers Online",
            f"Active: {', '.join(providers_available)}.",
        ))
    else:
        signals.append(_signal(
            "quality", "critical",
            "No Image Providers Available",
            "Export DOCX/PPTX will generate text-only documents. Set GOOGLE_API_KEY to enable.",
        ))

    # ── Image cache stats ──────────────────────────────────────────
    try:
        from .image_gen import _image_cache, _MAX_CACHE_SIZE
        cache_count = len(_image_cache)
        cache_pct = (cache_count / _MAX_CACHE_SIZE) * 100 if _MAX_CACHE_SIZE else 0
        signals.append(_signal(
            "quality", "info",
            f"Image Cache: {cache_count}/{_MAX_CACHE_SIZE}",
            f"Cache utilization: {cache_pct:.0f}%. Cached images avoid re-generation on repeated exports.",
        ))
        metadata["cache_count"] = cache_count
        metadata["cache_max"] = _MAX_CACHE_SIZE
    except ImportError:
        signals.append(_signal(
            "quality", "warning",
            "Image Gen Module Not Loaded",
            "backend/image_gen.py could not be imported — export images will be unavailable.",
        ))

    # ── Export readiness assessment ────────────────────────────────
    model_count = len(stage1_results)
    # Estimate total images needed for a full export
    estimated_images = 3 + model_count  # 3 heroes + 1 per model (stage1 only for estimate)
    est_time_sec = estimated_images * 8  # ~8s per image average

    if providers_available:
        signals.append(_signal(
            "insight", "info",
            f"Export Ready: ~{estimated_images} Images",
            f"Full PPTX/DOCX export would generate ~{estimated_images} contextual images "
            f"(~{est_time_sec}s with parallel 4x). Every slide gets a unique visual.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "Text-Only Export Mode",
            "No image providers configured — exports will be text-only without visual enhancement.",
        ))

    # ── Content richness for image prompts ─────────────────────────
    total_chars = sum(len(r.get("response", "")) for r in stage1_results)
    avg_chars = total_chars // max(model_count, 1)
    if avg_chars > 500:
        signals.append(_signal(
            "quality", "success",
            "Rich Content for Image Prompts",
            f"Average {avg_chars} chars/model — sufficient context for high-quality image generation.",
        ))
    elif avg_chars < 100:
        signals.append(_signal(
            "quality", "warning",
            "Sparse Content for Images",
            f"Average {avg_chars} chars/model — image prompts may lack context specificity.",
        ))

    metadata["providers_available"] = providers_available
    metadata["providers_unavailable"] = providers_unavailable
    metadata["estimated_images"] = estimated_images

    conf = 0.9 if providers_available else 0.3

    return _agent_result(
        agent_id="image_quality_monitor",
        role="Image Quality Monitor",
        icon="\U0001f5bc\ufe0f",
        signals=signals,
        summary=(
            f"{len(providers_available)} providers active · "
            f"~{estimated_images} images per export · "
            f"cache {metadata.get('cache_count', 0)}/{metadata.get('cache_max', 50)}"
        ),
        confidence=conf,
        metadata=metadata,
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🎯  Competitive Intelligence Agent (Pharma Intel)                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def competitive_intelligence_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyses competitor pipeline activity, launches, and messaging gaps."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Competitor Coverage Check ──
    competitors = {
        "pfizer": ["tafamidis", "vyndaqel", "vyndamax"],
        "alnylam": ["vutrisiran", "amvuttra", "patisiran", "onpattro"],
        "ionis": ["eplontersen", "wainua", "inotersen", "tegsedi"],
        "bridgebio": ["acoramidis"],
    }
    covered = {}
    for company, drugs in competitors.items():
        mentioned = [d for d in drugs if d in s3_lower]
        if mentioned:
            covered[company] = mentioned

    if len(covered) >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Comprehensive Competitor Coverage ({len(covered)} Companies)",
            f"Analysis covers: {', '.join(covered.keys())}",
        ))
    elif len(covered) == 0:
        signals.append(_signal(
            "gap", "warning",
            "No Competitor Coverage Detected",
            "The synthesis lacks competitor analysis. Consider requesting competitive landscape data.",
        ))
    else:
        missing = [c for c in competitors if c not in covered]
        signals.append(_signal(
            "gap", "info",
            f"Partial Competitor Coverage ({len(covered)}/{len(competitors)})",
            f"Missing: {', '.join(missing)}. May need deeper CI analysis.",
        ))

    # ── Pipeline Activity Signals ──
    pipeline_terms = ["phase 2", "phase 3", "phase ii", "phase iii", "pivotal", "registrational", "nda", "bla", "maa"]
    pipeline_mentions = sum(1 for t in pipeline_terms if t in s3_lower)
    if pipeline_mentions >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Rich Pipeline Data ({pipeline_mentions} Stage References)",
            "Response includes specific clinical development stage information.",
        ))

    # ── Evidence Support ──
    ci_cites = 0
    if evidence_bundle:
        for c in evidence_bundle.get("citations", []):
            src = c.get("source", "")
            if "CI/" in src or "Competitive" in src:
                ci_cites += 1
    if ci_cites > 0:
        signals.append(_signal("evidence", "success", f"CI Evidence: {ci_cites} Citations", "Competitive intelligence backed by evidence citations."))

    confidence = min(1.0, 0.3 + len(covered) * 0.15 + pipeline_mentions * 0.05)

    return _agent_result(
        agent_id="competitive_intelligence",
        role="Competitive Intelligence",
        icon="🎯",
        signals=signals,
        summary=f"{len(covered)} competitors · {pipeline_mentions} pipeline refs · {ci_cites} citations",
        confidence=confidence,
        metadata={"competitors_covered": list(covered.keys()), "pipeline_mentions": pipeline_mentions, "ci_citations": ci_cites},
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  ⚖️  Legal & Promotional Compliance Agent (Pharma Intel)            ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def compliance_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluates promotional compliance, flags potential regulatory risks."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Unsupported Superiority Claims ──
    superiority_terms = ["superior", "best-in-class", "outperform", "better than", "most effective", "gold standard"]
    sup_count = sum(1 for t in superiority_terms if t in s3_lower)
    if sup_count >= 2:
        signals.append(_signal(
            "risk", "warning",
            f"Potential Superiority Claims ({sup_count} Found)",
            "Unsupported superiority language may trigger OPDP review. Ensure claims are backed by head-to-head data.",
        ))

    # ── Fair Balance Check ──
    safety_terms = ["adverse", "side effect", "contraindic", "warning", "black box", "risk", "precaution"]
    benefit_terms = ["efficacy", "benefit", "improvement", "reduction", "response rate", "remission"]
    safety_count = sum(1 for t in safety_terms if t in s3_lower)
    benefit_count = sum(1 for t in benefit_terms if t in s3_lower)
    if benefit_count > 0 and safety_count == 0:
        signals.append(_signal(
            "risk", "critical",
            "Fair Balance Violation — No Safety Information",
            "Benefits mentioned without corresponding safety/risk information. OPDP requires fair balance.",
        ))
    elif benefit_count > safety_count * 3:
        signals.append(_signal(
            "risk", "warning",
            "Potential Fair Balance Imbalance",
            f"Benefits ({benefit_count}) significantly outweigh safety mentions ({safety_count}).",
        ))
    else:
        signals.append(_signal(
            "insight", "success",
            "Fair Balance: Adequate",
            f"Benefits ({benefit_count}) and safety ({safety_count}) appear balanced.",
        ))

    # ── Off-Label Detection ──
    if any(term in s3_lower for term in ["off-label", "off label", "unapproved indication", "investigational use"]):
        signals.append(_signal(
            "risk", "warning",
            "Off-Label Content Detected",
            "Response references off-label use. Ensure appropriate disclaimers are present.",
        ))

    confidence = max(0.3, 1.0 - sup_count * 0.15 - (0.3 if benefit_count > safety_count * 3 else 0))

    return _agent_result(
        agent_id="compliance",
        role="Legal & Promotional Compliance",
        icon="⚖️",
        signals=signals,
        summary=f"Superiority: {sup_count} · Safety: {safety_count} · Benefits: {benefit_count}",
        confidence=confidence,
        metadata={"superiority_claims": sup_count, "safety_mentions": safety_count, "benefit_mentions": benefit_count},
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📡  PubWatch Agent — Scientific Intelligence Monitor               ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def pubwatch_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Monitors publication recency, flags preprints, highlights data currency."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")

    # ── Publication Recency Analysis ──
    current_year = str(datetime.now().year)
    prev_year = str(datetime.now().year - 1)
    recent_refs = s3.count(current_year) + s3.count(prev_year)
    older_years = sum(s3.count(str(y)) for y in range(2015, datetime.now().year - 1))

    if recent_refs >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Current Evidence ({recent_refs} Recent References)",
            f"Response cites {recent_refs} references from {prev_year}-{current_year}.",
        ))
    elif recent_refs == 0 and older_years > 0:
        signals.append(_signal(
            "gap", "warning",
            "Potentially Outdated Evidence",
            f"No references from {prev_year}-{current_year}. {older_years} older references found. Data may be stale.",
        ))

    # ── Preprint Detection ──
    preprint_markers = ["preprint", "biorxiv", "medrxiv", "arxiv", "not peer-reviewed", "non-peer-reviewed"]
    preprint_count = sum(1 for m in preprint_markers if m in s3.lower())
    if preprint_count > 0:
        signals.append(_signal(
            "risk", "info",
            f"Preprint References Detected ({preprint_count})",
            "Some evidence is from preprint sources. Results may change after peer review.",
        ))

    # ── PubWatch Evidence Citations ──
    pw_cites = 0
    if evidence_bundle:
        for c in evidence_bundle.get("citations", []):
            src = c.get("source", "")
            if "PubWatch" in src or "[NEW]" in c.get("title", "") or "[PREPRINT]" in c.get("title", ""):
                pw_cites += 1
    if pw_cites > 0:
        signals.append(_signal("evidence", "success", f"PubWatch: {pw_cites} Fresh Citations", "Recent publication monitoring found new evidence."))

    confidence = min(1.0, 0.3 + recent_refs * 0.1 + (0.2 if pw_cites > 0 else 0))

    return _agent_result(
        agent_id="pubwatch",
        role="Scientific Intelligence Monitor",
        icon="📡",
        signals=signals,
        summary=f"{recent_refs} recent refs · {preprint_count} preprints · {pw_cites} PubWatch citations",
        confidence=confidence,
        metadata={"recent_refs": recent_refs, "preprint_count": preprint_count, "pubwatch_citations": pw_cites},
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📈  Claim Impact & Rx Uplift Agent (Pharma Intel)                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def claim_impact_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyses clinical claims and their potential commercial / prescribing impact."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Endpoint Translation Check ──
    endpoint_terms = ["nnt", "number needed to treat", "absolute risk reduction", "arr",
                      "hazard ratio", "hr ", "odds ratio", "or ", "relative risk",
                      "progression-free survival", "pfs", "overall survival", "os ",
                      "response rate", "orr", "complete response", "cr "]
    endpoint_count = sum(1 for t in endpoint_terms if t in s3_lower)
    if endpoint_count >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Strong Endpoint Data ({endpoint_count} Metrics)",
            "Response includes quantitative clinical endpoints suitable for claim substantiation.",
        ))
    elif endpoint_count == 0:
        signals.append(_signal(
            "gap", "info",
            "No Quantitative Endpoints Found",
            "Response lacks NNT, HR, or other quantitative endpoint data for claim impact assessment.",
        ))

    # ── Commercial Impact Language ──
    commercial_terms = ["formulary", "switching", "prescrib", "market share", "uptake",
                        "adoption", "physician", "payer", "reimburs"]
    comm_count = sum(1 for t in commercial_terms if t in s3_lower)
    if comm_count >= 2:
        signals.append(_signal(
            "insight", "success",
            f"Commercial Impact Context ({comm_count} Indicators)",
            "Response translates clinical data into commercial implications.",
        ))

    # ── Claim-to-Impact Mapping ──
    if endpoint_count >= 2 and comm_count >= 1:
        signals.append(_signal(
            "insight", "success",
            "Claim-Impact Bridge Established",
            "Response connects clinical endpoints to commercial impact — suitable for Rx uplift analysis.",
        ))

    confidence = min(1.0, 0.2 + endpoint_count * 0.08 + comm_count * 0.1)

    return _agent_result(
        agent_id="claim_impact",
        role="Claim Impact & Rx Uplift",
        icon="📈",
        signals=signals,
        summary=f"Endpoints: {endpoint_count} · Commercial: {comm_count}",
        confidence=confidence,
        metadata={"endpoint_metrics": endpoint_count, "commercial_indicators": comm_count},
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  💰  Market Access & Pricing Agent (Pharma Intel)                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def market_access_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyses HTA positioning, pricing evidence, and market access barriers."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── HTA Body Coverage ──
    hta_bodies = {
        "NICE": ["nice", "national institute for health"],
        "ICER": ["icer", "institute for clinical and economic review"],
        "G-BA/AMNOG": ["g-ba", "amnog", "gemeinsamer bundesausschuss"],
        "PBAC": ["pbac", "pharmaceutical benefits advisory"],
        "HAS": ["has ", "haute autorité de santé"],
        "CADTH": ["cadth", "canadian drug"],
    }
    covered_hta = []
    for body, terms in hta_bodies.items():
        if any(t in s3_lower for t in terms):
            covered_hta.append(body)

    if len(covered_hta) >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Comprehensive HTA Coverage ({len(covered_hta)} Bodies)",
            f"Analysis covers: {', '.join(covered_hta)}",
        ))
    elif len(covered_hta) == 0:
        signals.append(_signal(
            "gap", "info",
            "No HTA Body References",
            "Response lacks reference to HTA bodies (NICE, ICER, G-BA, etc.).",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            f"Partial HTA Coverage ({len(covered_hta)})",
            f"Covers: {', '.join(covered_hta)}. Consider adding other major markets.",
        ))

    # ── Pricing / Cost-Effectiveness Metrics ──
    pricing_terms = ["qaly", "cost per qaly", "cost-effective", "willingness to pay",
                     "budget impact", "icer value", "price per", "wholesale acquisition"]
    pricing_count = sum(1 for t in pricing_terms if t in s3_lower)
    if pricing_count >= 2:
        signals.append(_signal(
            "insight", "success",
            f"Pricing Evidence Present ({pricing_count} Metrics)",
            "Response includes health economics data suitable for market access strategy.",
        ))

    # ── Generic/Biosimilar Threat ──
    gx_terms = ["generic", "biosimilar", "patent expir", "loss of exclusivity", "loe",
                 "paragraph iv", "anda", "patent cliff", "price erosion"]
    gx_count = sum(1 for t in gx_terms if t in s3_lower)
    if gx_count >= 2:
        signals.append(_signal(
            "risk", "warning",
            f"Generic/Biosimilar Threat Identified ({gx_count} Signals)",
            "Response mentions generic or biosimilar competition threats.",
        ))

    confidence = min(1.0, 0.3 + len(covered_hta) * 0.1 + pricing_count * 0.08)

    return _agent_result(
        agent_id="market_access",
        role="Market Access & Pricing",
        icon="💰",
        signals=signals,
        summary=f"HTA: {len(covered_hta)} bodies · Pricing: {pricing_count} · GX: {gx_count}",
        confidence=confidence,
        metadata={"hta_bodies_covered": covered_hta, "pricing_metrics": pricing_count, "gx_signals": gx_count},
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🧬  Product Expert Agent — ATTR Portfolio (Pharma Intel)            ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def product_expert_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deep molecule expertise for ATTR-CM/ATTR-PN portfolio."""
    signals = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Molecule Coverage ──
    molecules = {
        "Acoramidis": ["acoramidis"],
        "Tafamidis": ["tafamidis", "vyndaqel", "vyndamax"],
        "Vutrisiran": ["vutrisiran", "amvuttra"],
        "Eplontersen": ["eplontersen", "wainua"],
    }
    covered_mol = {}
    for mol, terms in molecules.items():
        if any(t in s3_lower for t in terms):
            covered_mol[mol] = True

    if len(covered_mol) >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Comprehensive ATTR Coverage ({len(covered_mol)}/4 Molecules)",
            f"Covers: {', '.join(covered_mol.keys())}",
        ))
    elif len(covered_mol) == 0:
        signals.append(_signal(
            "gap", "warning",
            "No ATTR Molecule Coverage",
            "Response lacks mention of key ATTR-CM/PN molecules.",
        ))

    # ── Mechanism Differentiation (Stabiliser vs Silencer) ──
    has_stabiliser = any(t in s3_lower for t in ["stabiliz", "stabilis", "ttr stabiliz", "kinetic stabili"])
    has_silencer = any(t in s3_lower for t in ["sirna", "silenc", "antisense", "rnai", "gene silenc"])
    if has_stabiliser and has_silencer:
        signals.append(_signal(
            "insight", "success",
            "Mechanism Differentiation: Stabiliser vs Silencer",
            "Response distinguishes between TTR stabilisation and TTR silencing approaches.",
        ))
    elif (has_stabiliser or has_silencer) and not (has_stabiliser and has_silencer):
        signals.append(_signal(
            "gap", "info",
            "Partial Mechanism Coverage",
            f"Only {'stabiliser' if has_stabiliser else 'silencer'} mechanism covered. Consider comparing both approaches.",
        ))

    # ── Key Clinical Trials ──
    key_trials = {
        "ATTR-ACT": "tafamidis pivotal",
        "ATTRibute-CM": "acoramidis pivotal",
        "HELIOS-A": "vutrisiran ATTR-PN",
        "HELIOS-B": "vutrisiran ATTR-CM",
        "CARDIO-TTRansform": "eplontersen ATTR-CM",
        "NEURO-TTRansform": "eplontersen ATTR-PN",
    }
    mentioned_trials = [t for t in key_trials if t.lower() in s3_lower]
    if mentioned_trials:
        signals.append(_signal(
            "evidence", "success",
            f"Key Trial References ({len(mentioned_trials)})",
            f"Mentions: {', '.join(mentioned_trials)}",
        ))

    # ── Product Expert Evidence ──
    pe_cites = 0
    if evidence_bundle:
        for c in evidence_bundle.get("citations", []):
            if "ProductExpert" in c.get("source", ""):
                pe_cites += 1
    if pe_cites > 0:
        signals.append(_signal("evidence", "success", f"Product Expert: {pe_cites} Citations", "Deep molecule evidence from multiple sources."))

    confidence = min(1.0, 0.2 + len(covered_mol) * 0.12 + len(mentioned_trials) * 0.08 + (0.1 if has_stabiliser and has_silencer else 0))

    return _agent_result(
        agent_id="product_expert",
        role="Product Expert",
        icon="🧬",
        signals=signals,
        summary=f"{len(covered_mol)}/4 molecules · {len(mentioned_trials)} trials · Stab: {'✓' if has_stabiliser else '✗'} Sil: {'✓' if has_silencer else '✗'}",
        confidence=confidence,
        metadata={
            "molecules_covered": list(covered_mol.keys()),
            "mechanism_stabiliser": has_stabiliser,
            "mechanism_silencer": has_silencer,
            "key_trials_mentioned": mentioned_trials,
            "pe_citations": pe_cites,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🎨  Creative Campaign & PR Agent (Pharma Pipeline)                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def creative_campaign_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    🎨 Creative Campaign & PR Agent — Prepares updated communication
    resources and messages.

    Evaluates the council output for campaign-readiness: press-release
    language, headline quality, multi-channel adaptation potential,
    PR-worthiness of claims, and social media snippet suitability.

    Skills leveraged: PubMed (publication hooks), Endpoints News
    (industry angle), Semantic Scholar (citation authority).
    """
    signals: List[Dict[str, Any]] = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Headline / Key Message Readiness ────────────────────────────
    headline_patterns = [
        r"^#{1,3}\s+.{20,}",                      # Markdown headings
        r"\*\*[^*]{15,80}\*\*",                    # Bold phrases ≥15 chars
        r"Key\s+(Message|Finding|Takeaway|Point)",  # Key message markers
    ]
    headline_count = sum(
        len(re.findall(p, s3, re.MULTILINE | re.IGNORECASE))
        for p in headline_patterns
    )
    if headline_count >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Campaign-Ready Headlines ({headline_count} Found)",
            "Response contains structured headlines suitable for press releases and sales aids.",
        ))
    elif headline_count == 0:
        signals.append(_signal(
            "insight", "warning",
            "No Campaign Headlines Detected",
            "Response lacks bold key messages. Communication materials need clear, quotable headlines.",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            f"Partial Headlines ({headline_count})",
            "Some key messages present — consider adding 2–3 more for multi-channel use.",
        ))

    # ── Press Release Language Indicators ───────────────────────────
    pr_terms = [
        "announce", "launch", "milestone", "breakthrough", "first-ever",
        "transformative", "significant", "landmark", "pivotal", "data show",
        "demonstrated", "data presented at", "congress", "now available",
        "approved", "expanded indication",
    ]
    pr_count = sum(1 for t in pr_terms if t in s3_lower)
    if pr_count >= 4:
        signals.append(_signal(
            "insight", "success",
            f"Strong PR Language ({pr_count} Indicators)",
            "Response uses press-release-appropriate language and action verbs.",
        ))
    elif pr_count == 0:
        signals.append(_signal(
            "insight", "info",
            "No PR Language Detected",
            "Response is scientific in tone. Consider adding action-oriented PR framing.",
        ))

    # ── Multi-Channel Adaptation Potential ──────────────────────────
    channels = {
        "Social Media": any(w in s3_lower for w in [
            "tweet", "post", "hashtag", "social", "linkedin", "x.com",
        ]) or len(s3) > 200,  # Long enough to extract snippets
        "Sales Aid": any(w in s3_lower for w in [
            "one-pager", "sell sheet", "sales aid", "leave-behind",
            "key visual", "detail aid",
        ]),
        "Congress / Event": any(w in s3_lower for w in [
            "congress", "conference", "symposium", "poster", "presentation",
            "asco", "esmo", "aha", "aasld", "esc ",
        ]),
        "Medical Letter": any(w in s3_lower for w in [
            "dear doctor", "medical letter", "hcp communication",
            "field medical", "msl ",
        ]),
    }
    active_channels = [c for c, hit in channels.items() if hit]
    if active_channels:
        signals.append(_signal(
            "insight", "success" if len(active_channels) >= 2 else "info",
            f"Channel Fit: {', '.join(active_channels)}",
            f"{len(active_channels)} communication channel(s) applicable based on content analysis.",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            "No Specific Channel Fit Detected",
            "Content could be adapted for social media, sales aids, congress decks, or medical letters.",
        ))

    # ── Quotable Snippet Extraction ─────────────────────────────────
    # Look for short, powerful sentences that could be social media snippets
    sentences = re.findall(r'[^.!?]*[.!?]', s3)
    quotable = [s.strip() for s in sentences if 30 <= len(s.strip()) <= 200 and any(
        w in s.lower() for w in ["significant", "demonstrated", "showed", "reduced",
                                   "improved", "first", "novel", "breakthrough"]
    )]
    if quotable:
        signals.append(_signal(
            "insight", "success",
            f"{len(quotable)} Quotable Snippet(s) Found",
            f"Best snippet: \"{quotable[0][:120]}{'…' if len(quotable[0]) > 120 else ''}\"",
        ))

    # ── Evidence for Campaign Claims ────────────────────────────────
    campaign_cites = 0
    if evidence_bundle:
        for c in evidence_bundle.get("citations", []):
            src = c.get("source", "").lower()
            if any(s in src for s in ["pubmed", "semanticscholar", "endpoints"]):
                campaign_cites += 1
    if campaign_cites >= 3:
        signals.append(_signal(
            "evidence", "success",
            f"Evidence-Backed Campaign: {campaign_cites} Citations",
            "Campaign claims are supported by literature evidence — suitable for MLR review.",
        ))

    confidence = min(1.0, 0.25 + headline_count * 0.08 + pr_count * 0.05 +
                     len(active_channels) * 0.1 + len(quotable) * 0.05)

    return _agent_result(
        agent_id="creative_campaign",
        role="Creative Campaign & PR",
        icon="🎨",
        signals=signals,
        summary=f"Headlines: {headline_count} · PR: {pr_count} · Channels: {len(active_channels)} · Snippets: {len(quotable)}",
        confidence=confidence,
        metadata={
            "headline_count": headline_count,
            "pr_language_count": pr_count,
            "active_channels": active_channels,
            "quotable_snippets": len(quotable),
            "campaign_citations": campaign_cites,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  🎓  Medical Education & Training Agent (Pharma Pipeline)           ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def medical_education_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    grounding_scores: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    🎓 Medical Education & Training Agent — Enables confident same-day
    scientific dialogue.

    Evaluates the council output for medical education suitability:
    learning-objective alignment, scientific accuracy depth, HCP
    training readiness, MSL dialogue support, and Q&A preparedness.

    Skills leveraged: PubMed (evidence depth), ClinicalTrials.gov
    (latest data), OpenFDA (safety labelling), EMA (SmPC alignment).
    """
    signals: List[Dict[str, Any]] = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── Learning Objectives Detection ───────────────────────────────
    learning_markers = [
        "learning objective", "after reading", "key learning",
        "educational goal", "upon completion", "understand",
        "describe", "explain", "differentiate", "compare",
    ]
    learning_count = sum(1 for m in learning_markers if m in s3_lower)
    if learning_count >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Strong Educational Structure ({learning_count} Markers)",
            "Response includes explicit learning objectives or educational framing.",
        ))
    elif learning_count >= 1:
        signals.append(_signal(
            "insight", "info",
            f"Partial Educational Structure ({learning_count} Markers)",
            "Some educational language present. Consider adding explicit learning objectives.",
        ))
    else:
        signals.append(_signal(
            "insight", "info",
            "No Explicit Learning Objectives",
            "For training materials, add 2–3 clear learning objectives at the start.",
        ))

    # ── Scientific Depth Assessment ─────────────────────────────────
    depth_indicators = [
        "mechanism of action", "pharmacokinetic", "pharmacodynamic",
        "half-life", "bioavailability", "metabolism", "clearance",
        "phase ", "clinical trial", "endpoint", "p-value", "hazard ratio",
        "confidence interval", "nnt", "binding affinity", "ic50", "ec50",
        "selectivity", "molecular weight", "structure-activity",
    ]
    depth_count = sum(1 for d in depth_indicators if d in s3_lower)
    if depth_count >= 8:
        signals.append(_signal(
            "insight", "success",
            f"High Scientific Depth ({depth_count} Technical Terms)",
            "Content suitable for specialist HCP education and MSL dialogue.",
        ))
    elif depth_count >= 4:
        signals.append(_signal(
            "insight", "info",
            f"Moderate Scientific Depth ({depth_count} Terms)",
            "Suitable for general HCP education. Specialist training may need more depth.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            f"Low Scientific Depth ({depth_count} Terms)",
            "Content may not support confident scientific dialogue with specialists.",
        ))

    # ── HCP Training Material Readiness ─────────────────────────────
    training_elements = {
        "Q&A Ready": any(w in s3_lower for w in [
            "question", "answer", "faq", "commonly asked", "objection",
            "how to respond", "talking point",
        ]),
        "Case Studies": any(w in s3_lower for w in [
            "case study", "patient case", "clinical scenario", "real-world",
            "case report", "illustrative",
        ]),
        "Visual Aids": any(w in s3_lower for w in [
            "figure", "table", "chart", "diagram", "graph", "illustration",
            "infographic",
        ]) or ("| " in s3 and " | " in s3),  # Markdown tables
        "Safety Briefing": any(w in s3_lower for w in [
            "black box", "contraindication", "adverse event", "warning",
            "drug interaction", "precaution", "safety profile",
        ]),
        "Dosing Guide": any(w in s3_lower for w in [
            "dosing", "dose", "titration", "administration", "route",
            "frequency", "once daily", "twice daily", "mg",
        ]),
    }
    ready_elements = [e for e, hit in training_elements.items() if hit]
    if len(ready_elements) >= 3:
        signals.append(_signal(
            "insight", "success",
            f"Training-Ready: {', '.join(ready_elements)}",
            f"{len(ready_elements)}/5 training elements present — suitable for HCP slide deck.",
        ))
    elif len(ready_elements) >= 1:
        missing = [e for e, hit in training_elements.items() if not hit]
        signals.append(_signal(
            "insight", "info",
            f"Partial Training Readiness ({len(ready_elements)}/5)",
            f"Missing: {', '.join(missing[:3])}.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            "Not Training-Ready",
            "Response lacks Q&A, case studies, visual aids, safety briefing, or dosing info.",
        ))

    # ── MSL Dialogue Support ────────────────────────────────────────
    msl_terms = [
        "msl", "medical science liaison", "field medical",
        "scientific exchange", "reactive response", "proactive",
        "congress", "advisory board", "kol", "key opinion leader",
    ]
    msl_hits = sum(1 for t in msl_terms if t in s3_lower)
    if msl_hits >= 2:
        signals.append(_signal(
            "insight", "success",
            f"MSL Dialogue Support ({msl_hits} Indicators)",
            "Content supports MSL scientific exchanges with KOLs.",
        ))

    # ── Grounding Adequacy for Education ────────────────────────────
    overall = grounding_scores.get("overall_score", 0)
    if overall >= 70:
        signals.append(_signal(
            "quality", "success",
            f"Education-Grade Grounding: {overall:.0f}%",
            "Grounding score meets pharmaceutical education accuracy requirements.",
        ))
    elif overall >= 50:
        signals.append(_signal(
            "quality", "warning",
            f"Borderline Grounding for Education: {overall:.0f}%",
            "Grounding may be insufficient for formal training materials. Manual review needed.",
        ))
    else:
        signals.append(_signal(
            "quality", "critical",
            f"Insufficient Grounding for Education: {overall:.0f}%",
            "Grounding too low for educational use. Do NOT use in training materials without verification.",
        ))

    # ── Evidence for Education ──────────────────────────────────────
    edu_cites = 0
    if evidence_bundle:
        for c in evidence_bundle.get("citations", []):
            src = c.get("source", "").lower()
            if any(s in src for s in ["pubmed", "clinicaltrials", "fda", "ema"]):
                edu_cites += 1
    if edu_cites >= 3:
        signals.append(_signal(
            "evidence", "success",
            f"Education Evidence: {edu_cites} Authoritative Citations",
            "Training content is supported by regulatory and peer-reviewed sources.",
        ))

    confidence = min(1.0, 0.2 + depth_count * 0.04 + len(ready_elements) * 0.1 +
                     (overall / 100) * 0.2 + learning_count * 0.05)

    return _agent_result(
        agent_id="medical_education",
        role="Medical Education & Training",
        icon="🎓",
        signals=signals,
        summary=f"Depth: {depth_count} terms · Training: {len(ready_elements)}/5 · Grounding: {overall:.0f}%",
        confidence=confidence,
        metadata={
            "learning_markers": learning_count,
            "scientific_depth": depth_count,
            "training_elements": ready_elements,
            "training_readiness": len(ready_elements) / 5.0,
            "msl_support": msl_hits,
            "grounding_for_education": overall,
            "education_citations": edu_cites,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  📊  Performance & Analytics Agent (Pharma Pipeline)                ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def performance_analytics_agent(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    aggregate_rankings: List[Dict[str, Any]],
    grounding_scores: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
    cost_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    📊 Performance & Analytics Agent — Monitors real-time impact on LLM
    visibility, favorability, and searchability.

    Evaluates council output for LLM search optimisation, content
    discoverability, sentiment positioning, and cross-model consistency
    to ensure maximum visibility in AI-powered search and recommendation
    systems.

    Skills leveraged: OpenAlex (citation impact), Semantic Scholar
    (influence metrics), DuckDuckGo (web discoverability).
    """
    signals: List[Dict[str, Any]] = []
    s3 = (stage3_result or {}).get("response", "")
    s3_lower = s3.lower()

    # ── LLM Search Visibility (Structured Content) ──────────────────
    # LLM search engines favour structured, factual, well-cited content
    visibility_factors = {
        "Structured Headings": bool(re.search(r'^#{1,4}\s', s3, re.MULTILINE)),
        "Numbered Lists": bool(re.search(r'^\d+\.\s', s3, re.MULTILINE)),
        "Bullet Points": bool(re.search(r'^[-*]\s', s3, re.MULTILINE)),
        "Tables": "| " in s3 and " | " in s3,
        "Citations": bool(re.search(
            r'\[(?:FDA|CT|PM|EMA|WHO|UP|CB|KG|RC|RX|STR|HUB|SS|CR|EPMC)-\w+\]', s3
        )),
        "Statistical Data": bool(re.search(r'(?:p\s*[<>=]|HR\s*[=:]|CI\s*[:\[]|\d+%)', s3)),
    }
    active_factors = [f for f, hit in visibility_factors.items() if hit]
    visibility_score = len(active_factors) / len(visibility_factors)

    if visibility_score >= 0.7:
        signals.append(_signal(
            "insight", "success",
            f"High LLM Visibility: {len(active_factors)}/{len(visibility_factors)} Factors",
            f"Active: {', '.join(active_factors)}. Content is well-structured for AI search indexing.",
        ))
    elif visibility_score >= 0.4:
        missing = [f for f, hit in visibility_factors.items() if not hit]
        signals.append(_signal(
            "insight", "info",
            f"Moderate Visibility ({len(active_factors)}/{len(visibility_factors)})",
            f"Missing: {', '.join(missing)}. Adding these improves LLM search discoverability.",
        ))
    else:
        signals.append(_signal(
            "insight", "warning",
            f"Low LLM Visibility ({len(active_factors)}/{len(visibility_factors)})",
            "Unstructured content is less likely to appear in LLM-powered search results.",
        ))

    # ── Favorability Analysis (Sentiment & Tone) ───────────────────
    positive_terms = [
        "effective", "well-tolerated", "significant improvement", "superior",
        "first-in-class", "best-in-class", "breakthrough", "transformative",
        "favorable", "promising", "durable", "robust", "compelling",
    ]
    negative_terms = [
        "failed", "discontinued", "withdrawn", "inferior", "no benefit",
        "safety concern", "black box", "fatal", "rejected", "unacceptable",
    ]
    neutral_terms = [
        "compared to", "versus", "similar to", "non-inferior", "equivalent",
    ]
    pos_count = sum(1 for t in positive_terms if t in s3_lower)
    neg_count = sum(1 for t in negative_terms if t in s3_lower)
    neu_count = sum(1 for t in neutral_terms if t in s3_lower)

    total_sentiment = pos_count + neg_count + neu_count
    if total_sentiment > 0:
        pos_ratio = pos_count / total_sentiment
        if pos_ratio >= 0.7:
            sentiment_label = "Strongly Favorable"
        elif pos_ratio >= 0.5:
            sentiment_label = "Moderately Favorable"
        elif neg_count > pos_count:
            sentiment_label = "Unfavorable"
        else:
            sentiment_label = "Balanced"
    else:
        sentiment_label = "Neutral"
        pos_ratio = 0.5

    signals.append(_signal(
        "insight", "success" if "Favorable" in sentiment_label else "info",
        f"Sentiment: {sentiment_label}",
        f"Positive: {pos_count} · Negative: {neg_count} · Neutral: {neu_count}",
    ))

    # ── Cross-Model Consistency (Agreement Signal) ──────────────────
    if aggregate_rankings and len(aggregate_rankings) >= 2:
        top_rank = aggregate_rankings[0].get("average_rank", 0)
        bot_rank = aggregate_rankings[-1].get("average_rank", 0)
        spread = bot_rank - top_rank

        if spread < 1.0:
            signals.append(_signal(
                "pattern", "success",
                f"High Model Agreement (spread: {spread:.2f})",
                "Cross-model consensus strengthens content reliability for analytics.",
            ))
        elif spread > 2.5:
            signals.append(_signal(
                "pattern", "warning",
                f"Model Disagreement (spread: {spread:.2f})",
                "High disagreement may indicate content polarisation — review for accuracy.",
            ))

    # ── Content Discoverability Keywords ────────────────────────────
    # Check for entity-rich content (drug names, conditions, genes)
    entity_patterns = [
        r'\b[A-Z][a-z]+(?:mab|nib|lib|tide|sen|ran|stat|pril|olol)\b',  # Drug suffixes
        r'NCT\d{8}',                                                       # Trial IDs
        r'\b(?:ATTR|HER2|EGFR|BRCA|PD-L?1|ALK|KRAS|TP53)\b',            # Biomarkers
    ]
    entity_count = sum(len(re.findall(p, s3)) for p in entity_patterns)
    if entity_count >= 5:
        signals.append(_signal(
            "insight", "success",
            f"Entity-Rich Content ({entity_count} Searchable Terms)",
            "High density of drug names, biomarkers, and trial IDs improves search findability.",
        ))
    elif entity_count >= 2:
        signals.append(_signal(
            "insight", "info",
            f"Moderate Entity Density ({entity_count} Terms)",
            "Some searchable entities present. Adding more drug names and biomarkers helps.",
        ))

    # ── Citation Authority Score ────────────────────────────────────
    citations = (evidence_bundle or {}).get("citations", [])
    authoritative_sources = {"PubMed", "ClinicalTrials.gov", "OpenFDA", "EMA",
                             "Semantic Scholar", "OpenAlex"}
    auth_cites = sum(1 for c in citations if c.get("source", "") in authoritative_sources)
    if auth_cites >= 5:
        signals.append(_signal(
            "evidence", "success",
            f"High Citation Authority ({auth_cites} Authoritative Sources)",
            "Content backed by PubMed, FDA, EMA, and academic databases — high trust signal.",
        ))
    elif auth_cites > 0:
        signals.append(_signal(
            "evidence", "info",
            f"Moderate Citation Authority ({auth_cites} Sources)",
            "Some authoritative citations present. More PubMed/FDA sources improve trust.",
        ))

    # ── Pipeline Efficiency ─────────────────────────────────────────
    if cost_summary:
        total_tokens = cost_summary.get("total_tokens", 0)
        models_used = cost_summary.get("models_used", 0)
        total_cost = cost_summary.get("total_cost_usd", 0)
        if total_tokens > 0:
            s3_words = len(s3.split())
            efficiency = s3_words / (total_tokens / 1000)  # Words per k-token
            signals.append(_signal(
                "quality", "info",
                f"Efficiency: {efficiency:.1f} words/k-token · ${total_cost:.4f}",
                f"{models_used} models · {total_tokens:,} tokens → {s3_words} synthesis words.",
            ))

    # ── Overall Analytics Score ─────────────────────────────────────
    overall_grounding = grounding_scores.get("overall_score", 0)
    analytics_score = (
        visibility_score * 30 +
        (pos_ratio if total_sentiment > 0 else 0.5) * 20 +
        min(entity_count / 10, 1.0) * 20 +
        min(auth_cites / 5, 1.0) * 15 +
        (overall_grounding / 100) * 15
    )

    signals.append(_signal(
        "quality", "success" if analytics_score >= 70 else "info" if analytics_score >= 50 else "warning",
        f"Analytics Score: {analytics_score:.0f}/100",
        f"Visibility: {visibility_score:.0%} · Sentiment: {sentiment_label} · "
        f"Entities: {entity_count} · Authority: {auth_cites}",
    ))

    confidence = min(1.0, analytics_score / 100)

    return _agent_result(
        agent_id="performance_analytics",
        role="Performance & Analytics",
        icon="📊",
        signals=signals,
        summary=f"Score: {analytics_score:.0f} · Visibility: {visibility_score:.0%} · {sentiment_label} · {entity_count} entities",
        confidence=confidence,
        metadata={
            "analytics_score": round(analytics_score, 1),
            "visibility_score": round(visibility_score, 3),
            "visibility_factors": active_factors,
            "sentiment": sentiment_label,
            "positive_count": pos_count,
            "negative_count": neg_count,
            "neutral_count": neu_count,
            "entity_count": entity_count,
            "authoritative_citations": auth_cites,
            "grounding_score": overall_grounding,
        },
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Team Coordinator — Run All Agents                                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def run_agent_team(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    aggregate_rankings: List[Dict[str, Any]],
    grounding_scores: Dict[str, Any],
    evidence_bundle: Optional[Dict[str, Any]] = None,
    cost_summary: Optional[Dict[str, Any]] = None,
    web_search_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Run all agent team members in parallel and aggregate their results.

    Automatically detects query mode and includes VP-specialist agents
    when a value-proposition query is identified.

    Returns:
        Dict with "agents" list, "team_confidence", "total_signals",
        "critical_count", "query_mode".
    """
    import asyncio

    query_mode = detect_query_mode(user_query)
    logger.info(f"[AgentTeam] Query mode detected: {query_mode}")

    # ── Core agents (always run) ──
    core_tasks = [
        research_analyst_agent(user_query, stage1_results, stage3_result, evidence_bundle),
        fact_checker_agent(stage2_results, grounding_scores),
        risk_assessor_agent(user_query, stage3_result, grounding_scores, evidence_bundle),
        pattern_scout_agent(user_query, stage1_results, stage2_results, aggregate_rankings),
        insight_synthesizer_agent(user_query, stage1_results, stage3_result, aggregate_rankings, evidence_bundle),
        quality_auditor_agent(stage1_results, stage2_results, stage3_result, cost_summary),
        citation_supervisor_agent(stage3_result, evidence_bundle),
        skills_manager_agent(evidence_bundle, web_search_enabled),
        memory_orchestrator_agent(user_query, stage3_result, grounding_scores, cost_summary),
        image_quality_monitor_agent(user_query, stage1_results, stage3_result, cost_summary),
    ]

    # ── VP-specialist agents (only in value_proposition mode) ──
    vp_tasks = []
    if query_mode == "value_proposition":
        logger.info("[AgentTeam] Activating VP agents: Market Positioning, Clinical Value, Messaging Strategist")
        vp_tasks = [
            market_positioning_agent(user_query, stage1_results, stage3_result, evidence_bundle),
            clinical_value_agent(user_query, stage1_results, stage3_result, evidence_bundle),
            messaging_strategist_agent(user_query, stage1_results, stage3_result),
        ]

    # ── Pharma Intelligence agents (auto-detected by domain keywords) ──
    pi_tasks = []
    if query_mode in ("pharma_intel", "pharma_pipeline", "value_proposition"):
        pi_domains = detect_pharma_intel_query(user_query)
        active_pi = [d for d, v in pi_domains.items() if v]
        if active_pi:
            logger.info(f"[AgentTeam] Activating Pharma Intel agents: {active_pi}")
        if pi_domains["ci"]:
            pi_tasks.append(competitive_intelligence_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["compliance"]:
            pi_tasks.append(compliance_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["pubwatch"]:
            pi_tasks.append(pubwatch_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["claim_impact"]:
            pi_tasks.append(claim_impact_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["market_access"]:
            pi_tasks.append(market_access_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["product_expert"]:
            pi_tasks.append(product_expert_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["campaign"]:
            pi_tasks.append(creative_campaign_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if pi_domains["education"]:
            pi_tasks.append(medical_education_agent(user_query, stage1_results, stage3_result, grounding_scores, evidence_bundle))
        if pi_domains["performance"]:
            pi_tasks.append(performance_analytics_agent(user_query, stage1_results, stage2_results, stage3_result, aggregate_rankings, grounding_scores, evidence_bundle, cost_summary))

    # ── Full Pharma Pipeline mode: activate ALL 7 pipeline agents ──
    pipeline_tasks = []
    if query_mode == "pharma_pipeline":
        logger.info("[AgentTeam] Full Pharma Pipeline mode — activating all 7 pipeline agents")
        pi_domains = detect_pharma_intel_query(user_query)
        # Add any pipeline agents not already triggered by domain keywords
        if not pi_domains.get("ci"):
            pipeline_tasks.append(competitive_intelligence_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if not pi_domains.get("product_expert"):
            pipeline_tasks.append(product_expert_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if not pi_domains.get("compliance"):
            pipeline_tasks.append(compliance_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if not pi_domains.get("claim_impact"):
            pipeline_tasks.append(claim_impact_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if not pi_domains.get("campaign"):
            pipeline_tasks.append(creative_campaign_agent(user_query, stage1_results, stage3_result, evidence_bundle))
        if not pi_domains.get("education"):
            pipeline_tasks.append(medical_education_agent(user_query, stage1_results, stage3_result, grounding_scores, evidence_bundle))
        if not pi_domains.get("performance"):
            pipeline_tasks.append(performance_analytics_agent(user_query, stage1_results, stage2_results, stage3_result, aggregate_rankings, grounding_scores, evidence_bundle, cost_summary))

    agents = await asyncio.gather(
        *core_tasks, *vp_tasks, *pi_tasks, *pipeline_tasks,
        return_exceptions=True,
    )

    # Filter out exceptions
    valid_agents = []
    for a in agents:
        if isinstance(a, Exception):
            logger.error(f"[AgentTeam] Agent failed: {a}")
        else:
            valid_agents.append(a)

    # Compute team-level metrics
    all_signals = [s for a in valid_agents for s in a.get("signals", [])]
    team_confidence = (
        sum(a.get("confidence", 0) for a in valid_agents) / max(len(valid_agents), 1)
    )
    critical_count = sum(1 for s in all_signals if s.get("severity") == "critical")
    warning_count = sum(1 for s in all_signals if s.get("severity") == "warning")

    return {
        "agents": valid_agents,
        "team_confidence": round(team_confidence, 3),
        "total_signals": len(all_signals),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "agent_count": len(valid_agents),
        "query_mode": query_mode,
    }
