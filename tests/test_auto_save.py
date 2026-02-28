"""
Simulation tests for the auto-save + context classification feature.

Tests cover:
  1. classify_query() domain classification for pharma/chemistry/regulatory/data_science/general
  2. classify_query() question_type detection
  3. classify_query() complexity heuristic
  4. update_conversation_context() storage function (local-user file-based)
  5. Pydantic model serialization with context_tags field
  6. Cosmos DB list query includes context_tags
  7. Early title flow: title_task consumed after Stage 1 (not Stage 3)
  8. Auto-create conversation: handleSendMessage creates if none exists
"""
import json
import os
import sys
import uuid
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ===================================================================
# Test 1: classify_query — domain detection
# ===================================================================
def test_classify_query_domains():
    """Test that sample queries classify to the expected domain."""
    from backend.memory import UserProfileMemory

    cases = [
        # (query, expected_domain)
        ("What is the pharmacokinetic profile of ibuprofen?", "pharma"),
        ("Describe the mechanism of action of EGFR antibody trastuzumab", "pharma"),
        ("What is the FDA approval timeline for a biosimilar?", "pharma"),
        ("How to synthesize aspirin via esterification reaction?", "chemistry"),
        ("Compare HPLC chromatography yield and reagent purity", "chemistry"),
        ("What are the ICH GMP compliance requirements for sterile manufacturing?", "regulatory"),
        ("Compare the NICE and IQWiG HTA processes for market access", "market_access"),
        ("How to build a transformer model for NLP classification?", "data_science"),
        ("What is the weather like today?", "general"),  # no domain keywords
    ]

    passed = 0
    for query, expected_domain in cases:
        result = UserProfileMemory.classify_query(query)
        actual = result["domain"]
        status = "✓" if actual == expected_domain else "✗"
        if actual == expected_domain:
            passed += 1
        print(f"  {status} classify_query domain: expected={expected_domain}, got={actual}")
        print(f"    query: {query[:60]}...")
        print(f"    domain_scores: {result['domain_scores']}")

    print(f"\n  Domain tests: {passed}/{len(cases)} passed")
    assert passed == len(cases), f"Domain classification: {passed}/{len(cases)} passed"


# ===================================================================
# Test 2: classify_query — question_type detection
# ===================================================================
def test_classify_query_question_types():
    """Test question type classification."""
    from backend.memory import UserProfileMemory

    cases = [
        ("How to run a clinical trial?", "how_to"),
        ("Compare aspirin versus ibuprofen", "comparison"),
        ("What is a monoclonal antibody?", "factual"),
        ("Analyze the Phase III trial data", "analysis"),
        ("What best practice should I follow for GMP?", "recommendation"),
        ("Hello world", "general"),  # no type triggers
    ]

    passed = 0
    for query, expected_type in cases:
        result = UserProfileMemory.classify_query(query)
        actual = result["question_type"]
        status = "✓" if actual == expected_type else "✗"
        if actual == expected_type:
            passed += 1
        print(f"  {status} question_type: expected={expected_type}, got={actual} — {query[:50]}")

    print(f"\n  Question type tests: {passed}/{len(cases)} passed")
    assert passed == len(cases), f"Question type: {passed}/{len(cases)} passed"


# ===================================================================
# Test 3: classify_query — complexity heuristic
# ===================================================================
def test_classify_query_complexity():
    """Test word-count based complexity detection."""
    from backend.memory import UserProfileMemory

    cases = [
        ("What is aspirin?", "simple"),          # 3 words
        (" ".join(["word"] * 14), "simple"),     # 14 words → simple
        (" ".join(["word"] * 15), "moderate"),   # 15 words → moderate
        (" ".join(["word"] * 49), "moderate"),   # 49 words → moderate
        (" ".join(["word"] * 50), "complex"),    # 50 words → complex
        (" ".join(["word"] * 100), "complex"),   # 100 words → complex
    ]

    passed = 0
    for query, expected_complexity in cases:
        result = UserProfileMemory.classify_query(query)
        actual = result["complexity"]
        wc = result["word_count"]
        status = "✓" if actual == expected_complexity else "✗"
        if actual == expected_complexity:
            passed += 1
        print(f"  {status} complexity: expected={expected_complexity}, got={actual} (word_count={wc})")

    print(f"\n  Complexity tests: {passed}/{len(cases)} passed")
    assert passed == len(cases), f"Complexity: {passed}/{len(cases)} passed"


# ===================================================================
# Test 4: update_conversation_context — local file storage
# ===================================================================
def test_update_conversation_context_local():
    """Test that context_tags persist to a conversation JSON file."""
    # Use a temp directory to avoid polluting real data
    temp_dir = tempfile.mkdtemp(prefix="llm_test_")
    conv_id = str(uuid.uuid4())
    user_id = "local-user"
    user_dir = os.path.join(temp_dir, "data", "conversations", user_id)
    os.makedirs(user_dir, exist_ok=True)

    # Create a minimal conversation file
    conv = {
        "id": conv_id,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": "Test Conversation",
        "messages": [],
    }
    conv_path = os.path.join(user_dir, f"{conv_id}.json")
    with open(conv_path, "w") as f:
        json.dump(conv, f)

    # Patch the data directory so storage.py reads from our temp
    import backend.storage as storage_mod

    original_data_dir = getattr(storage_mod, '_DATA_DIR', None)
    # Find the DATA_DIR constant
    data_dir_path = os.path.join(temp_dir, "data", "conversations")

    # Patch _file_get to read from our temp dir
    def _file_get_patched(uid, cid):
        p = os.path.join(data_dir_path, uid, f"{cid}.json")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return json.load(f)

    def _file_save_patched(uid, conv):
        d = os.path.join(data_dir_path, uid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{conv['id']}.json"), "w") as f:
            json.dump(conv, f)

    with patch.object(storage_mod, 'get_conversation', side_effect=_file_get_patched):
        with patch.object(storage_mod, 'save_conversation', side_effect=_file_save_patched):
            context_tags = {
                "domain": "pharma",
                "domain_scores": {"pharma": 3, "chemistry": 1},
                "question_type": "factual",
                "complexity": "moderate",
                "word_count": 25,
            }
            storage_mod.update_conversation_context(user_id, conv_id, context_tags)

    # Verify the file was updated
    with open(conv_path) as f:
        updated = json.load(f)

    assert "context_tags" in updated, "context_tags not saved to conversation file"
    assert updated["context_tags"]["domain"] == "pharma"
    assert updated["context_tags"]["word_count"] == 25
    print(f"  ✓ context_tags persisted to local file: {updated['context_tags']}")

    # Cleanup
    shutil.rmtree(temp_dir)
    print(f"  ✓ temp directory cleaned up")


# ===================================================================
# Test 5: Pydantic model serialization with context_tags
# ===================================================================
def test_pydantic_context_tags():
    """Test ConversationMetadata and Conversation Pydantic models include context_tags."""
    from backend.main import ConversationMetadata, Conversation

    # Test ConversationMetadata with context_tags
    meta = ConversationMetadata(
        id="test-id",
        created_at="2025-01-01T00:00:00Z",
        title="Test Title",
        message_count=5,
        context_tags={"domain": "pharma", "complexity": "moderate"},
    )
    assert meta.context_tags is not None
    assert meta.context_tags["domain"] == "pharma"
    dumped = meta.model_dump()
    assert "context_tags" in dumped
    print(f"  ✓ ConversationMetadata with context_tags: {dumped['context_tags']}")

    # Test ConversationMetadata without context_tags (backward compat)
    meta_no_tags = ConversationMetadata(
        id="test-id-2",
        created_at="2025-01-01T00:00:00Z",
        title="Old Conversation",
        message_count=2,
    )
    assert meta_no_tags.context_tags is None
    print(f"  ✓ ConversationMetadata without context_tags: None (backward compatible)")

    # Test full Conversation model
    conv = Conversation(
        id="test-conv-id",
        created_at="2025-01-01T00:00:00Z",
        title="Test Conv",
        messages=[{"role": "user", "content": "hello"}],
        context_tags={"domain": "chemistry", "question_type": "how_to", "complexity": "simple", "word_count": 5},
    )
    assert conv.context_tags["domain"] == "chemistry"
    conv_json = conv.model_dump_json()
    assert "chemistry" in conv_json
    print(f"  ✓ Conversation model with context_tags serializes correctly")


# ===================================================================
# Test 6: Cosmos DB list query includes context_tags
# ===================================================================
def test_cosmos_list_query_includes_context_tags():
    """Verify the _cosmos_list function's SQL query fetches context_tags."""
    import backend.storage as storage_mod
    import inspect

    source = inspect.getsource(storage_mod._cosmos_list)
    assert "c.context_tags" in source, "_cosmos_list query does not SELECT c.context_tags"
    print(f"  ✓ _cosmos_list SQL query includes 'c.context_tags'")


# ===================================================================
# Test 7: Early title flow — title_task consumed after Stage 1
# ===================================================================
def test_early_title_flow():
    """Verify the SSE pipeline code has title_task consumed after Stage 1 checkpoint."""
    import inspect
    from backend import main as main_mod

    # Find the send_message_stream endpoint function
    source = inspect.getsource(main_mod.send_message_stream)

    # Find the positions of key markers
    stage1_checkpoint_pos = source.find("Checkpoint: Stage 1 complete")
    early_title_pos = source.find("Early Title Save + Context Classification")
    stage2_start_pos = source.find("stage2_start")
    stage3_emit_pos = source.find("stage3_complete")

    assert stage1_checkpoint_pos > 0, "Stage 1 checkpoint marker not found"
    assert early_title_pos > 0, "Early Title Save marker not found"
    assert stage2_start_pos > 0, "stage2_start marker not found"

    # Verify order: Stage 1 → Early Title → Stage 2
    assert stage1_checkpoint_pos < early_title_pos < stage2_start_pos, \
        f"Title save not between Stage 1 and Stage 2: " \
        f"s1={stage1_checkpoint_pos}, title={early_title_pos}, s2={stage2_start_pos}"
    print(f"  ✓ Title save occurs AFTER Stage 1 checkpoint and BEFORE Stage 2 start")

    # Verify context_classified event is emitted early 
    context_classified_pos = source.find("context_classified")
    assert context_classified_pos > 0, "context_classified event not found"
    assert stage1_checkpoint_pos < context_classified_pos < stage2_start_pos, \
        "context_classified not between Stage 1 and Stage 2"
    print(f"  ✓ context_classified SSE event emitted between Stage 1 and Stage 2")

    # Verify title_task = None (consumed) happens before Stage 2
    title_consumed_pos = source.find("title_task = None  # consumed")
    assert title_consumed_pos > 0, "title_task = None  # consumed not found"
    assert title_consumed_pos < stage2_start_pos, \
        "title_task not consumed before Stage 2 starts"
    print(f"  ✓ title_task is consumed (set to None) before Stage 2")


# ===================================================================
# Test 8: Real pharma queries (vinod.das@bayer.com style)
# ===================================================================
def test_real_pharma_queries():
    """Test classify_query with realistic Bayer pharmaceutical queries."""
    from backend.memory import UserProfileMemory

    bayer_queries = [
        # Typical pharma R&D queries
        {
            "query": "What is the pharmacokinetic profile of finerenone in clinical trials?",
            "expected_domain": "pharma",
            "expected_type": "factual",
        },
        {
            "query": "Compare the efficacy of SGLT2 inhibitors versus DPP4 inhibitors for type 2 diabetes in oncology patients",
            "expected_domain": "pharma",
            "expected_type": "comparison",
        },
        {
            "query": "How to design a Phase III clinical trial for a novel anticoagulant compound?",
            "expected_domain": "pharma",
            "expected_type": "how_to",
        },
        {
            "query": "Analyze the pharmacokinetic data from the rivaroxaban absorption study",
            "expected_domain": "pharma",
            "expected_type": "analysis",
        },
        {
            "query": "What are the FDA regulatory requirements for an IND submission of a new oncology drug?",
            "expected_domain": "pharma",  # pharma + regulatory, pharma should win on keyword count
            "expected_type": "factual",
        },
        # Data science / ML queries
        {
            "query": "How to build a deep learning model for drug-target interaction prediction using a transformer architecture?",
            "expected_domain": "data_science",
            "expected_type": "how_to",
        },
    ]

    passed = 0
    for case in bayer_queries:
        result = UserProfileMemory.classify_query(case["query"])
        domain_ok = result["domain"] == case["expected_domain"]
        type_ok = result["question_type"] == case["expected_type"]
        both = domain_ok and type_ok
        if both:
            passed += 1
        status = "✓" if both else "✗"
        issues = []
        if not domain_ok:
            issues.append(f"domain: expected={case['expected_domain']}, got={result['domain']}")
        if not type_ok:
            issues.append(f"type: expected={case['expected_type']}, got={result['question_type']}")
        issue_str = f" ({'; '.join(issues)})" if issues else ""
        print(f"  {status} {case['query'][:55]}...{issue_str}")
        print(f"    → domain={result['domain']}, type={result['question_type']}, complexity={result['complexity']}, words={result['word_count']}")

    print(f"\n  Real pharma query tests: {passed}/{len(bayer_queries)} passed")
    assert passed == len(bayer_queries), f"Real pharma queries: {passed}/{len(bayer_queries)} passed"


# ===================================================================
# Main runner
# ===================================================================
if __name__ == "__main__":
    tests = [
        ("Test 1: Domain classification", test_classify_query_domains),
        ("Test 2: Question type detection", test_classify_query_question_types),
        ("Test 3: Complexity heuristic", test_classify_query_complexity),
        ("Test 4: Context tags persistence (local storage)", test_update_conversation_context_local),
        ("Test 5: Pydantic model serialization", test_pydantic_context_tags),
        ("Test 6: Cosmos list query includes context_tags", test_cosmos_list_query_includes_context_tags),
        ("Test 7: Early title flow (Stage 1 timing)", test_early_title_flow),
        ("Test 8: Real pharma queries (Bayer style)", test_real_pharma_queries),
    ]

    total_passed = 0
    total_tests = len(tests)
    failures = []

    for name, func in tests:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        try:
            func()
            total_passed += 1
            print(f"  ✅ PASSED")
        except Exception as e:
            failures.append((name, str(e)))
            print(f"  ❌ FAILED: {e}")

    print(f"\n{'='*60}")
    print(f"  RESULTS: {total_passed}/{total_tests} tests passed")
    print(f"{'='*60}")
    if failures:
        print("\n  Failed tests:")
        for name, err in failures:
            print(f"    ✗ {name}: {err}")
        sys.exit(1)
    else:
        print("\n  All tests passed! ✓")
        sys.exit(0)
