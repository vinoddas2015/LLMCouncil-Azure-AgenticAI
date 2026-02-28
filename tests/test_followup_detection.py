"""Comprehensive tests for _detect_targeted_followup().

Tests both the PRIMARY (prefix-based regex) and FALLBACK (mention-based)
detection paths against a wide variety of user input patterns.
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Import the function under test
from backend.main import _detect_targeted_followup


# ── Fixtures ──────────────────────────────────────────────────────────

MOCK_STAGE1 = [
    {"model": "openai/gpt-5.2", "response": "GPT response about hemophilia treatment."},
    {"model": "anthropic/claude-sonnet-4.6", "response": "Claude response about hemophilia treatment."},
    {"model": "google/gemini-3-pro-preview", "response": "Gemini response about hemophilia treatment."},
    {"model": "xai/grok-3", "response": "Grok response about hemophilia treatment."},
]

MOCK_STAGE2 = [
    {"model": "openai/gpt-5.2", "evaluation": "Evaluation text from GPT..."},
    {"model": "anthropic/claude-sonnet-4.6", "evaluation": "Evaluation text from Claude..."},
]

MOCK_STAGE3 = {
    "model": "anthropic/claude-opus-4.6",
    "response": "The chairman synthesis about hemophilia treatment centers in NJ...",
}

MOCK_METADATA = {
    "label_to_model": {"Response A": "openai/gpt-5.2", "Response B": "anthropic/claude-sonnet-4.6"},
    "aggregate_rankings": [{"model": "openai/gpt-5.2", "avg_rank": 1.5}],
    "grounding_scores": {"overall_score": 80},
    "evidence": {"citations": []},
}

MOCK_CONVERSATION_HISTORY = [
    {"role": "user", "content": "Tell me about hemophilia treatment centers in NJ."},
    {
        "role": "assistant",
        "stage1": MOCK_STAGE1,
        "stage2": MOCK_STAGE2,
        "stage3": MOCK_STAGE3,
        "metadata": MOCK_METADATA,
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Stage-Targeted Tests
# ═══════════════════════════════════════════════════════════════════════

class TestStageTargetedPrimary:
    """Tests for PRIMARY stage detection (prefix + regex)."""

    def test_chip_format_colon(self):
        """Chip-generated format: 'Regarding Stage 3: ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 3: please list specialized hemophilia treatment centers",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"
        assert "hemophilia" in result["user_question"]

    def test_comma_separator(self):
        """User typed comma: 'Regarding Stage 3, ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 3, please list specialized hemophilia treatment centers in New Jersey",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_dash_separator(self):
        """User typed dash: 'Regarding Stage 3 - ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 3 - can you elaborate on the treatment options?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_em_dash_separator(self):
        """Em-dash: 'Regarding Stage 3 — ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 3 — what about pediatric patients?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_no_separator(self):
        """No separator: 'Regarding Stage 3 can you ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 3 can you provide more specific details?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_semicolon_separator(self):
        """Semicolon: 'Regarding Stage 1; ...'"""
        result = _detect_targeted_followup(
            "Regarding Stage 1; what sources did the models use?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 1"

    def test_stage_1(self):
        """Stage 1 detection."""
        result = _detect_targeted_followup(
            "Regarding Stage 1: expand the individual responses",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 1"
        assert isinstance(result["reference_data"], list)
        assert len(result["reference_data"]) == 4

    def test_stage_2(self):
        """Stage 2 detection."""
        result = _detect_targeted_followup(
            "Regarding Stage 2: explain the peer rankings in detail",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 2"
        assert isinstance(result["reference_data"], list)

    def test_stage_3_reference_data(self):
        """Stage 3 should return the chairman's response text."""
        result = _detect_targeted_followup(
            "Regarding Stage 3: list treatment centers",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 3"
        assert "hemophilia treatment centers" in result["reference_data"]

    def test_case_insensitive(self):
        """Case insensitivity."""
        result = _detect_targeted_followup(
            "regarding stage 3: tell me more",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 3"

    def test_about_prefix(self):
        """Alternative prefix: 'About Stage 3, ...'"""
        result = _detect_targeted_followup(
            "About Stage 3, can you provide more details?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_for_prefix(self):
        """Alternative prefix: 'For Stage 2: ...'"""
        result = _detect_targeted_followup(
            "For Stage 2: which model ranked highest?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 2"

    def test_expand_on_prefix(self):
        """Alternative prefix: 'Expand on Stage 3 ...'"""
        result = _detect_targeted_followup(
            "Expand on Stage 3 and include treatment costs",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 3"

    def test_elaborate_on_prefix(self):
        """Alternative prefix: 'Elaborate on Stage 1; ...'"""
        result = _detect_targeted_followup(
            "Elaborate on Stage 1; what were the key differences?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 1"

    def test_tell_me_more_prefix(self):
        """Alternative prefix: 'Tell me more about Stage 3 ...'"""
        result = _detect_targeted_followup(
            "Tell me more about Stage 3 hemophilia treatment options",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 3"

    def test_concerning_prefix(self):
        """Alternative prefix: 'Concerning Stage 2, ...'"""
        result = _detect_targeted_followup(
            "Concerning Stage 2, why did model B rank lower?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 2"

    def test_re_prefix(self):
        """Alternative prefix: 'Re Stage 3: ...'"""
        result = _detect_targeted_followup(
            "Re Stage 3: are there any pediatric-focused centers?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 3"


class TestStageTargetedFallback:
    """Tests for FALLBACK stage detection (mention in first 80 chars)."""

    def test_stage_at_end(self):
        """Stage mentioned at end: 'expand the answer from Stage 3'"""
        result = _detect_targeted_followup(
            "Can you expand the answer from Stage 3?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"

    def test_stage_in_middle(self):
        """Stage mentioned mid-sentence."""
        result = _detect_targeted_followup(
            "What did Stage 1 models say about treatment centers?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"] == "Stage 1"

    def test_stage_no_space(self):
        """'Stage3' without space."""
        result = _detect_targeted_followup(
            "Expand Stage3 answer with more specifics",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["target_label"].replace(" ", "").startswith("Stage")

    def test_full_question_as_user_question(self):
        """Fallback should use the full content as user_question."""
        content = "Please list more treatment centers from Stage 3"
        result = _detect_targeted_followup(content, MOCK_CONVERSATION_HISTORY)
        assert result is not None
        assert result["user_question"] == content


# ═══════════════════════════════════════════════════════════════════════
# Model-Targeted Tests
# ═══════════════════════════════════════════════════════════════════════

class TestModelTargetedPrimary:
    """Tests for PRIMARY model detection (prefix + 's response)."""

    def test_chip_format_colon(self):
        """Chip-generated: \"Regarding gpt-5.2's response: ...\""""
        result = _detect_targeted_followup(
            "Regarding gpt-5.2's response: can you elaborate on the evidence?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "gpt-5.2" in result["target_label"]

    def test_comma_separator(self):
        """Comma: \"Regarding claude-sonnet-4.6's response, ...\""""
        result = _detect_targeted_followup(
            "Regarding claude-sonnet-4.6's response, how confident is this?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "claude-sonnet-4.6" in result["target_label"]

    def test_smart_apostrophe(self):
        """Smart/curly apostrophe: 's"""
        result = _detect_targeted_followup(
            "Regarding gpt-5.2\u2019s response: what sources?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"

    def test_about_prefix_model(self):
        """'About grok-3's response, ...'"""
        result = _detect_targeted_followup(
            "About grok-3's response, it seems incomplete",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "grok-3" in result["target_label"]

    def test_model_reference_data(self):
        """Model match should return the correct model's Stage 1 response."""
        result = _detect_targeted_followup(
            "Regarding gpt-5.2's response: elaborate",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert "GPT response" in result["reference_data"]
        assert result["full_model_id"] == "openai/gpt-5.2"


class TestModelTargetedFallback:
    """Tests for FALLBACK model detection (short name mention)."""

    def test_model_name_in_sentence(self):
        """'What did gpt-5.2 say about treatment?'"""
        result = _detect_targeted_followup(
            "What did gpt-5.2 say about treatment options?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "gpt-5.2" in result["target_label"]

    def test_claude_mention(self):
        """'claude-sonnet-4.6 mentioned something about...'"""
        result = _detect_targeted_followup(
            "claude-sonnet-4.6 mentioned something about pediatric centers",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "claude-sonnet-4.6" in result["target_label"]

    def test_gemini_mention(self):
        """'Expand on what gemini-3-pro-preview wrote'"""
        result = _detect_targeted_followup(
            "Expand on what gemini-3-pro-preview wrote about compliance",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["type"] == "model"
        assert "gemini-3-pro-preview" in result["target_label"]


# ═══════════════════════════════════════════════════════════════════════
# Negative Tests (should NOT detect a targeted follow-up)
# ═══════════════════════════════════════════════════════════════════════

class TestNegative:
    """Inputs that should NOT trigger targeted follow-up detection."""

    def test_no_conversation_history(self):
        """No history → None."""
        result = _detect_targeted_followup("Regarding Stage 3: elaborate", [])
        assert result is None

    def test_no_assistant_message(self):
        """Only user messages → None."""
        history = [{"role": "user", "content": "Hello"}]
        result = _detect_targeted_followup("Regarding Stage 3: elaborate", history)
        assert result is None

    def test_empty_content(self):
        """Empty content → None."""
        result = _detect_targeted_followup("", MOCK_CONVERSATION_HISTORY)
        assert result is None

    def test_none_content(self):
        """None content → None."""
        result = _detect_targeted_followup(None, MOCK_CONVERSATION_HISTORY)
        assert result is None

    def test_generic_question(self):
        """Generic question with no stage/model reference → None."""
        result = _detect_targeted_followup(
            "What are the latest FDA guidelines for hemophilia treatment?",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is None

    def test_stage_mention_past_80_chars(self):
        """Stage mention beyond first 80 chars should NOT trigger fallback."""
        # Build a long prefix that pushes "Stage 3" past the 80-char window
        padding = "A" * 80
        result = _detect_targeted_followup(
            f"{padding} regarding Stage 3 answer",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is None

    def test_unknown_model_name(self):
        """Model name not in Stage 1 results → None for model detection."""
        result = _detect_targeted_followup(
            "Regarding unknown-model-x's response: elaborate",
            MOCK_CONVERSATION_HISTORY,
        )
        # Should be None (no matching model)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# Metadata & Reference Data Tests
# ═══════════════════════════════════════════════════════════════════════

class TestMetadata:
    """Verify that previous stage data is correctly carried forward."""

    def test_prev_stages_included(self):
        """All prev_stage* fields should be populated from last assistant msg."""
        result = _detect_targeted_followup(
            "Regarding Stage 3: summarize",
            MOCK_CONVERSATION_HISTORY,
        )
        assert result is not None
        assert result["prev_stage1"] == MOCK_STAGE1
        assert result["prev_stage2"] == MOCK_STAGE2
        assert result["prev_stage3"] == MOCK_STAGE3
        assert result["prev_metadata"] == MOCK_METADATA

    def test_stage3_string_response(self):
        """When stage3 is stored as a plain string (legacy), still extract it."""
        history = [
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "stage1": MOCK_STAGE1,
                "stage2": MOCK_STAGE2,
                "stage3": "Plain text chairman response",
                "metadata": {},
            },
        ]
        result = _detect_targeted_followup("Regarding Stage 3: elaborate", history)
        assert result is not None
        assert result["reference_data"] == "Plain text chairman response"


# ═══════════════════════════════════════════════════════════════════════
# The exact user input that failed (regression test)
# ═══════════════════════════════════════════════════════════════════════

class TestRegressionUserInput:
    """Regression test for the exact user input that triggered the bug."""

    def test_exact_user_input_comma_separator(self):
        """The EXACT user input from the bug report (comma after Stage 3)."""
        content = (
            "Regarding Stage 3, please list specialized hemophilia treatment "
            "centers in New Jersey that adhere to current WFH, ASH, and ISTH "
            "guidelines, detailing the comprehensive care services they provide."
        )
        result = _detect_targeted_followup(content, MOCK_CONVERSATION_HISTORY)
        assert result is not None, (
            f"REGRESSION: failed to detect targeted follow-up for input: {content[:80]!r}"
        )
        assert result["type"] == "stage"
        assert result["target_label"] == "Stage 3"
        assert "hemophilia" in result["user_question"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
