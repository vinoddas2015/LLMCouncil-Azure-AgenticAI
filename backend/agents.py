"""
Agent Team for LLM Council — Specialized Role-Based Analysis.

Each agent is a focused expert that analyses the council pipeline
from a distinct perspective.  Agents run post-pipeline and produce
structured insights that feed into the Prompt Atlas dashboard.

Agent Roster
────────────
  🔬  Research Analyst    — Extracts key findings, data density, topic coverage
  🛡️  Fact Checker        — Validates claims against evidence, detects hallucinations
  ⚠️  Risk Assessor       — Evaluates safety signals, regulatory compliance flags
  🔍  Pattern Scout       — Detects recurring themes, emerging signals across sessions
  💡  Insight Synthesizer — Generates novel connections and strategic observations
  📊  Quality Auditor     — Scores response quality, completeness, actionability

All agents are pure async functions — stateless per-request, horizontally
scalable, and suitable for serverless deployment.
"""

from __future__ import annotations

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
    has_refs = bool(re.search(r'\[(?:FDA|CT|PM|WEB|SS|CR|EPMC|AX|PAT|WIKI|ORC)-\w+\]', s3_text))
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

    return "value_proposition" if vp_score >= 2 else "standard"


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
        r'\[(?:FDA|CT|PM|EMA|WHO|UP|CB|SS|CR|EPMC|WEB|AX|PAT|WIKI|ORC)-\w+\]',
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

    agents = await asyncio.gather(
        *core_tasks, *vp_tasks,
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
