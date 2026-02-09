"""
Token and cost tracking for LLM Council sessions.

Tracks per-model and per-stage token consumption, estimates costs,
and computes savings from using the OpenRouter/myGenAssist gateway
versus direct API pricing.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


# ── Pricing: Direct API vs OpenRouter Gateway ────────────────────────────
# Prices in USD per 1M tokens (input / output)
# Direct prices are list prices from each provider as of Feb 2026
# Gateway prices reflect Bayer enterprise agreement through myGenAssist

DIRECT_PRICING = {
    "claude-opus-4.5":   {"input": 15.00, "output": 75.00, "provider": "Anthropic"},
    "gemini-2.5-pro":    {"input":  1.25, "output": 10.00, "provider": "Google"},
    "gpt-5-mini":        {"input":  1.50, "output":  6.00, "provider": "OpenAI"},
    "grok-3":            {"input":  3.00, "output": 15.00, "provider": "xAI"},
    "gemini-2.5-flash":  {"input":  0.15, "output":  0.60, "provider": "Google"},
}

# Enterprise gateway negotiated rates (typically 30-50% discount)
GATEWAY_PRICING = {
    "claude-opus-4.5":   {"input":  9.00, "output": 45.00},
    "gemini-2.5-pro":    {"input":  0.75, "output":  6.00},
    "gpt-5-mini":        {"input":  0.90, "output":  3.60},
    "grok-3":            {"input":  1.80, "output":  9.00},
    "gemini-2.5-flash":  {"input":  0.09, "output":  0.36},
}


def _extract_base_model(model_name: str) -> str:
    """Extract base model ID from potentially decorated names like 'gpt-5-mini (fallback for ...)'."""
    # Take the first token before any parenthetical
    base = model_name.split("(")[0].strip()
    # Also strip any vendor prefix (e.g., openai/)
    if "/" in base:
        base = base.split("/")[-1]
    return base


def _calc_cost(model: str, prompt_tokens: int, completion_tokens: int, pricing: dict) -> float:
    """Calculate cost in USD for a given model and token counts."""
    base_model = _extract_base_model(model)
    rates = pricing.get(base_model)
    if not rates:
        return 0.0
    input_cost = (prompt_tokens / 1_000_000) * rates["input"]
    output_cost = (completion_tokens / 1_000_000) * rates["output"]
    return input_cost + output_cost


@dataclass
class StageTokens:
    """Token usage for a single stage."""
    stage: str
    models: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, usage: Optional[Dict[str, int]]):
        if usage:
            self.models[model] = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

    @property
    def total_prompt(self) -> int:
        return sum(m.get("prompt_tokens", 0) for m in self.models.values())

    @property
    def total_completion(self) -> int:
        return sum(m.get("completion_tokens", 0) for m in self.models.values())

    @property
    def total(self) -> int:
        return self.total_prompt + self.total_completion

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "models": self.models,
            "totals": {
                "prompt_tokens": self.total_prompt,
                "completion_tokens": self.total_completion,
                "total_tokens": self.total,
            },
        }


class SessionCostTracker:
    """
    Tracks token usage and costs across all stages of a council session.
    """

    def __init__(self):
        self.stages: Dict[str, StageTokens] = {}

    def record(self, stage: str, model: str, usage: Optional[Dict[str, int]]):
        """Record token usage for a model in a given stage."""
        if stage not in self.stages:
            self.stages[stage] = StageTokens(stage=stage)
        self.stages[stage].add(model, usage)

    def compute_summary(self) -> Dict[str, Any]:
        """
        Compute full cost summary with per-stage breakdowns,
        per-model breakdowns, and gateway savings.
        """
        # Aggregate totals
        total_prompt = 0
        total_completion = 0
        total_gateway_cost = 0.0
        total_direct_cost = 0.0

        stage_summaries = []
        per_model_totals: Dict[str, Dict[str, Any]] = {}

        for stage_name, stage_data in self.stages.items():
            stage_gateway = 0.0
            stage_direct = 0.0

            for model, tokens in stage_data.models.items():
                pt = tokens.get("prompt_tokens", 0)
                ct = tokens.get("completion_tokens", 0)

                gateway_cost = _calc_cost(model, pt, ct, GATEWAY_PRICING)
                direct_cost = _calc_cost(model, pt, ct, DIRECT_PRICING)

                stage_gateway += gateway_cost
                stage_direct += direct_cost

                # Accumulate per-model
                base = _extract_base_model(model)
                if base not in per_model_totals:
                    per_model_totals[base] = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "gateway_cost": 0.0,
                        "direct_cost": 0.0,
                        "provider": DIRECT_PRICING.get(base, {}).get("provider", "Unknown"),
                    }
                per_model_totals[base]["prompt_tokens"] += pt
                per_model_totals[base]["completion_tokens"] += ct
                per_model_totals[base]["total_tokens"] += pt + ct
                per_model_totals[base]["gateway_cost"] += gateway_cost
                per_model_totals[base]["direct_cost"] += direct_cost

            total_prompt += stage_data.total_prompt
            total_completion += stage_data.total_completion
            total_gateway_cost += stage_gateway
            total_direct_cost += stage_direct

            stage_summaries.append({
                **stage_data.to_dict(),
                "gateway_cost_usd": round(stage_gateway, 6),
                "direct_cost_usd": round(stage_direct, 6),
            })

        savings = total_direct_cost - total_gateway_cost
        savings_pct = (savings / total_direct_cost * 100) if total_direct_cost > 0 else 0

        # Round per-model costs
        for m in per_model_totals.values():
            m["gateway_cost"] = round(m["gateway_cost"], 6)
            m["direct_cost"] = round(m["direct_cost"], 6)

        return {
            "totals": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
                "gateway_cost_usd": round(total_gateway_cost, 6),
                "direct_cost_usd": round(total_direct_cost, 6),
                "savings_usd": round(savings, 6),
                "savings_pct": round(savings_pct, 1),
            },
            "per_stage": stage_summaries,
            "per_model": per_model_totals,
        }
