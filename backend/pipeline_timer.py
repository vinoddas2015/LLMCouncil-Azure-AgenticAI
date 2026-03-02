"""
Pipeline Timing Instrumentation for LLM Council.

Provides a lightweight `PipelineTimer` that records wall-clock durations
for every stage and sub-step.  Integrates into the SSE pipeline via the
`timing` field emitted with `cost_summary`.

Usage in main.py::

    from .pipeline_timer import PipelineTimer
    timer = PipelineTimer()
    timer.start("total")
    timer.start("memory_recall")
    ...
    timer.stop("memory_recall")
    ...
    timing = timer.summary()
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger("llm_council.pipeline_timer")


@dataclass
class _Span:
    """A single timed span."""
    name: str
    start_ts: float = 0.0
    end_ts: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> float:
        if self.end_ts <= 0:
            return round((time.perf_counter() - self.start_ts) * 1000, 1)
        return round((self.end_ts - self.start_ts) * 1000, 1)


class PipelineTimer:
    """
    Hierarchical wall-clock timer for the council pipeline.

    Stages tracked:
        total              — full request lifecycle
        prompt_guard       — evaluate_prompt() call
        memory_recall      — pre_stage1_agent (memory retrieval)
        stage1             — all model queries (parallel)
        stage1/<model>     — individual model time
        title_generation   — generate_conversation_title()
        context_classify   — classify_query()
        evidence_retrieval — run_evidence_skills()
        stage2             — all Stage 2 evaluations (parallel)
        stage2/<model>     — individual model time
        grounding_compute  — compute_response_grounding_scores()
        stage3_streaming   — chairman streaming response
        stage3_fallback    — chairman non-streaming fallback
        ca_validation      — context awareness validation pass
        citation_enrich    — enrich_stage3_citations()
        citation_validate  — validate_and_fix_citations()
        doubting_thomas    — doubting thomas review
        agent_team         — run_agent_team()
        learning           — post_stage3_agent()
    """

    def __init__(self):
        self._spans: Dict[str, _Span] = {}
        self._model_latencies: Dict[str, Dict[str, float]] = {}  # stage -> {model: ms}

    def start(self, name: str, **metadata) -> None:
        """Begin timing a named span."""
        self._spans[name] = _Span(
            name=name,
            start_ts=time.perf_counter(),
            metadata=metadata,
        )

    def stop(self, name: str, **extra_metadata) -> float:
        """
        Stop timing a named span.  Returns elapsed milliseconds.
        Returns 0 if the span was never started (non-fatal).
        """
        span = self._spans.get(name)
        if not span:
            logger.debug(f"[PipelineTimer] stop('{name}') — span not started, ignoring")
            return 0.0
        span.end_ts = time.perf_counter()
        if extra_metadata:
            span.metadata.update(extra_metadata)
        return span.elapsed_ms

    def record_model(self, stage: str, model: str, elapsed_ms: float) -> None:
        """Record individual model latency within a stage."""
        if stage not in self._model_latencies:
            self._model_latencies[stage] = {}
        self._model_latencies[stage][model] = round(elapsed_ms, 1)

    def elapsed(self, name: str) -> float:
        """Get current elapsed ms for a span (works for running spans too)."""
        span = self._spans.get(name)
        return span.elapsed_ms if span else 0.0

    def summary(self) -> Dict[str, Any]:
        """
        Produce a timing summary suitable for SSE emission.

        Returns::

            {
                "total_ms": 45230.1,
                "stages": {
                    "prompt_guard":       {"ms": 12.3},
                    "memory_recall":      {"ms": 340.5},
                    "stage1":             {"ms": 8320.0, "models": {"gpt-5.2": 7800, ...}},
                    "stage2":             {"ms": 12400.0, "models": {"gpt-5.2": 11200, ...}},
                    "stage3_streaming":   {"ms": 18500.0},
                    "agent_team":         {"ms": 3200.0},
                    ...
                },
                "distribution_pct": {
                    "stage1": 18.4,
                    "stage2": 27.4,
                    "stage3_streaming": 40.9,
                    ...
                },
                "bottleneck": "stage3_streaming",
                "slowest_models": {
                    "stage1": {"model": "grok-3", "ms": 9200},
                    "stage2": {"model": "grok-3", "ms": 11800},
                },
                "provider_latencies": {
                    "bayer_mygenassist": {"avg_ms": 8500, "models": [...]},
                    "google_direct":     {"avg_ms": 4200, "models": [...]},
                },
            }
        """
        total_ms = self.elapsed("total")

        stages: Dict[str, Any] = {}
        for name, span in self._spans.items():
            if name == "total":
                continue
            entry: Dict[str, Any] = {"ms": span.elapsed_ms}
            if span.metadata:
                entry["metadata"] = span.metadata
            # Attach per-model breakdowns
            if name in self._model_latencies:
                entry["models"] = self._model_latencies[name]
            stages[name] = entry

        # Add model latencies even if the stage span wasn't created
        for stage, models in self._model_latencies.items():
            if stage not in stages:
                stages[stage] = {"models": models}

        # Compute distribution percentages (only for major stages)
        major_stages = [
            "prompt_guard", "memory_recall", "stage1", "stage2",
            "evidence_retrieval", "stage3_streaming", "stage3_fallback",
            "grounding_compute", "ca_validation", "doubting_thomas",
            "citation_enrich", "citation_validate", "agent_team", "learning",
            "title_generation", "context_classify",
        ]
        distribution: Dict[str, float] = {}
        for s in major_stages:
            if s in stages:
                pct = (stages[s]["ms"] / total_ms * 100) if total_ms > 0 else 0
                distribution[s] = round(pct, 1)

        # Find bottleneck
        bottleneck = max(distribution, key=distribution.get) if distribution else None

        # Find slowest model per stage
        slowest_models: Dict[str, Dict[str, Any]] = {}
        for stage, models in self._model_latencies.items():
            if models:
                slowest = max(models, key=models.get)
                slowest_models[stage] = {"model": slowest, "ms": models[slowest]}

        # Provider-level aggregation
        provider_latencies = self._compute_provider_latencies()

        return {
            "total_ms": round(total_ms, 1),
            "stages": stages,
            "distribution_pct": distribution,
            "bottleneck": bottleneck,
            "slowest_models": slowest_models,
            "provider_latencies": provider_latencies,
        }

    def _compute_provider_latencies(self) -> Dict[str, Dict[str, Any]]:
        """Aggregate model latencies by provider (Bayer vs Google)."""
        providers: Dict[str, List[Dict[str, Any]]] = {
            "bayer_mygenassist": [],
            "google_direct": [],
        }

        for stage, models in self._model_latencies.items():
            for model, ms in models.items():
                entry = {"model": model, "stage": stage, "ms": ms}
                if model.startswith("google/"):
                    providers["google_direct"].append(entry)
                else:
                    providers["bayer_mygenassist"].append(entry)

        result = {}
        for provider, entries in providers.items():
            if entries:
                avg = sum(e["ms"] for e in entries) / len(entries)
                result[provider] = {
                    "avg_ms": round(avg, 1),
                    "count": len(entries),
                    "models": entries,
                }
        return result
