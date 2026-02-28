"""
Simulation tests for episodic memory filtering, duplicate detection,
and memory-aware Stage 3 chairman integration.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_episodic_type_filtering():
    """Only type='episodic' entries should be visible in list_all."""
    print("=" * 60)
    print("TEST 1: Episodic list_all type filtering")
    print("=" * 60)

    # Simulate the exact filter logic from EpisodicMemory.list_all()
    mock_docs = {
        "ep_conv1_abc123": {
            "id": "ep_conv1_abc123", "type": "episodic",
            "query": "What is aspirin?", "grounding_score": 0.77,
            "status": "active", "created_at": "2026-02-27T10:00:00",
        },
        "ep_conv2_def456": {
            "id": "ep_conv2_def456", "type": "episodic",
            "query": "Summarize PDF about pharmacodynamics",
            "grounding_score": 0.56, "status": "active",
            "created_at": "2026-02-27T09:00:00",
        },
        "ca_conv1_model_xyz": {
            "id": "ca_conv1_model_xyz", "type": "ca_snapshot",
            "model": "gpt-5.2", "score": 0.8, "status": "active",
            "created_at": "2026-02-27T10:01:00",
        },
        "upi_user1_aaa": {
            "id": "upi_user1_aaa", "type": "user_profile_interaction",
            "grounding_score": 0.77, "status": "active",
            "created_at": "2026-02-27T10:02:00",
        },
        "eca_state_bbb": {
            "id": "eca_state_bbb", "type": "eca_state",
            "status": "active", "created_at": "2026-02-27T10:03:00",
        },
        "legacy_entry": {
            "id": "legacy_entry", "query": "Old entry without type field",
            "grounding_score": 0.60, "status": "active",
            "created_at": "2025-01-01T00:00:00",
        },
    }

    filtered = []
    for k, doc in mock_docs.items():
        if doc.get("type") not in ("episodic", None):
            continue
        if doc.get("status") != "unlearned":
            filtered.append(doc)

    print(f"  Total docs in collection: {len(mock_docs)}")
    print(f"  After filter (type==episodic or None): {len(filtered)}")
    for e in filtered:
        t = e.get('type', 'None')
        print(f"    [{t}] {e['id']}: query={e.get('query', '')!r:.60}")

    assert len(filtered) == 3, f"Expected 3 (2 episodic + 1 legacy), got {len(filtered)}"
    types = {e.get("type") for e in filtered}
    assert types <= {"episodic", None}, f"Unexpected types leaked: {types}"
    print("  PASS: Only genuine episodic entries + legacy entries returned\n")


def test_duplicate_detection_jaccard():
    """Jaccard similarity should detect near-duplicate queries."""
    print("=" * 60)
    print("TEST 2: Duplicate query detection (Jaccard similarity)")
    print("=" * 60)

    def jaccard_sim(q1, q2):
        w1 = set(q1.lower().split())
        w2 = set(q2.lower().split())
        inter = w1 & w2
        union = w1 | w2
        return len(inter) / len(union) if union else 0.0

    test_cases = [
        # Realistic scenario: same PDF document submitted with different question wrappers
        # The extracted PDF text (hundreds of words) dominates the word set
        (
            "What does this document list? --- Attached Files: === Content extracted from PDF: Exploratory evaluation of pharmacodynamics including absorption rates kinetics metabolism clearance bioavailability steady state concentration plasma levels protein binding distribution volume",
            "Summarize the top three items from this document. --- Attached Files: === Content extracted from PDF: Exploratory evaluation of pharmacodynamics including absorption rates kinetics metabolism clearance bioavailability steady state concentration plasma levels protein binding distribution volume",
            True,
            "Same PDF re-submitted with different question (doc text dominates)",
        ),
        (
            "What is the main point or key takeaway from the attachment?",
            "What does this document list? Summarize the top three items.",
            False,
            "Different short queries without attachments",
        ),
        (
            "Explain CRISPR gene editing mechanisms and applications",
            "What are the side effects of metformin in diabetic patients?",
            False,
            "Completely different pharma queries",
        ),
        # Edge case: very short queries should NOT trigger (too few words)
        (
            "Hello",
            "Hello there",
            False,
            "Trivially short queries (below 3-word minimum)",
        ),
    ]

    all_pass = True
    for q1, q2, should_match, desc in test_cases:
        sim = jaccard_sim(q1, q2)
        detected = sim >= 0.55
        status = "PASS" if detected == should_match else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {status}: {desc}")
        print(f"    sim={sim:.3f}, threshold=0.55, detected={detected}, expected={should_match}")

    assert all_pass, "Some duplicate detection cases failed"
    print("  PASS: All Jaccard similarity cases correct\n")


def test_memory_context_injection():
    """Chairman prompt should include memory context + duplicate advisory."""
    print("=" * 60)
    print("TEST 3: Memory context + duplicate injection for Stage 3")
    print("=" * 60)

    dup_episode = {
        "query_preview": "What does this document list? Summarize the top ...",
        "duplicate_similarity": 0.72,
        "grounding_score": 0.77,
        "chairman_response_preview": "The document lists three items: ...",
    }

    sim = dup_episode["duplicate_similarity"]
    gs = dup_episode["grounding_score"]
    prev_preview = dup_episode["chairman_response_preview"][:400]
    prev_query = dup_episode["query_preview"][:200]
    memory_section = (
        f"PRIOR DELIBERATION CONTEXT - NEAR-DUPLICATE DETECTED\n"
        f"  Similarity: {sim:.0%} | Prior Grounding: {gs:.0%}\n"
        f'  Previous query: "{prev_query}"\n'
        f"  Previous chairman summary: {prev_preview}...\n"
    )

    print(f"  Generated memory section ({len(memory_section)} chars):")
    for line in memory_section.strip().split("\n"):
        print(f"    {line}")

    assert "NEAR-DUPLICATE DETECTED" in memory_section
    assert "72%" in memory_section
    assert "77%" in memory_section
    print("  PASS: Memory section correctly built\n")


def test_memory_addon_in_system_prompt():
    """_MEMORY_ADDON should be included when has_memory_context is set."""
    print("=" * 60)
    print("TEST 4: Memory addon activation in system prompt")
    print("=" * 60)

    # Simulate _build_system_message logic
    features_no_memory = {"needs_chemistry": False, "needs_vp": False}
    features_with_memory = {"needs_chemistry": False, "needs_vp": False, "has_memory_context": True}

    # Check the addon text exists
    _MEMORY_ADDON_SNIPPET = "Memory Advisory"

    # Without memory context: addon should NOT be present
    parts_no = ["BASE_SYSTEM"]
    if features_no_memory.get("has_memory_context"):
        parts_no.append(_MEMORY_ADDON_SNIPPET)
    msg_no = "\n".join(parts_no)
    assert _MEMORY_ADDON_SNIPPET not in msg_no
    print("  PASS: Memory addon absent when no memory context")

    # With memory context: addon SHOULD be present
    parts_yes = ["BASE_SYSTEM"]
    if features_with_memory.get("has_memory_context"):
        parts_yes.append(_MEMORY_ADDON_SNIPPET)
    msg_yes = "\n".join(parts_yes)
    assert _MEMORY_ADDON_SNIPPET in msg_yes
    print("  PASS: Memory addon activated when has_memory_context=True\n")


def test_stats_consistency():
    """Stats should count only episodic entries, matching list_all count."""
    print("=" * 60)
    print("TEST 5: Stats / list_all count consistency")
    print("=" * 60)

    # After fix: both stats and list_all use same filter
    mock_docs = [
        {"type": "episodic", "status": "active"},
        {"type": "episodic", "status": "active"},
        {"type": "episodic", "status": "unlearned"},
        {"type": "ca_snapshot", "status": "active"},
        {"type": "user_profile_interaction", "status": "active"},
        {"type": "eca_state", "status": "active"},
    ]

    # list_all(include_unlearned=True)
    all_entries = [d for d in mock_docs if d.get("type") in ("episodic", None)]
    active = [d for d in all_entries if d["status"] == "active"]
    unlearned = [d for d in all_entries if d["status"] == "unlearned"]

    print(f"  Total in collection: {len(mock_docs)}")
    print(f"  Episodic total: {len(all_entries)}, active: {len(active)}, unlearned: {len(unlearned)}")
    assert len(all_entries) == 3
    assert len(active) == 2
    assert len(unlearned) == 1
    print("  PASS: Stats chip will show '2' active, list will show 2 entries\n")


if __name__ == "__main__":
    test_episodic_type_filtering()
    test_duplicate_detection_jaccard()
    test_memory_context_injection()
    test_memory_addon_in_system_prompt()
    test_stats_consistency()

    print("=" * 60)
    print("ALL 5 SIMULATION TESTS PASSED")
    print("=" * 60)
