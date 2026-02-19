# CLAUDE.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a 3-stage deliberation system where multiple LLMs collaboratively answer user questions. The key innovation is anonymized peer review in Stage 2, preventing models from playing favorites.

**Domain**: Pharmaceutical (Bayer Internal)
**API**: Bayer myGenAssist (https://chat.int.bayer.com/api/v2/)

## Architecture

### Backend Structure (`backend/`)

**`config.py`**
- Contains `COUNCIL_MODELS` (list of Bayer myGenAssist model identifiers)
- Contains `CHAIRMAN_MODEL` (model that synthesizes final answer)
- Uses environment variable `OPENROUTER_API_KEY` from `.env` (Bayer API key)
- API Endpoint: `https://chat.int.bayer.com/api/v2/chat/completions`
- Backend runs on **port 8001** (NOT 8000 - user had another app on 8000)

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- Returns dict with 'content' and optional 'reasoning_details'
- Graceful degradation: returns None on failure, continues with successful responses

**`council.py`** - The Core Logic
- `stage1_collect_responses()`: Parallel queries to all council models
- `stage2_collect_rankings()`:
  - Anonymizes responses as "Response A, B, C, etc."
  - Creates `label_to_model` mapping for de-anonymization
  - Prompts models to evaluate and rank (with strict format requirements)
  - Returns tuple: (rankings_list, label_to_model_dict)
  - Each ranking includes both raw text and `parsed_ranking` list
- `stage3_synthesize_final()`: Chairman synthesizes from all responses + rankings
- `parse_ranking_from_text()`: Extracts "FINAL RANKING:" section, handles both numbered lists and plain format
- `calculate_aggregate_rankings()`: Computes average rank position across all peer evaluations

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[]}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Note: metadata (label_to_model, aggregate_rankings) is NOT persisted to storage, only returned via API

**`grounding.py`** — Bias-Free Grounding Score Engine + RAGAS Alignment
- Hybrid Verbalized Sampling + Synthetic Math scoring
- Pharma-specific safety metrics: Correctness, Precision, Recall, F1 from TP/FP/FN confusion matrix
- **RAGAS metric alignment** (verified against RAGAS v0.2 framework):
  - Precision = RAGAS Faithfulness (supported claims / total claims)
  - Recall = RAGAS Context Recall (attributable sentences / total sentences)
  - F1 = RAGAS Factual Correctness (balanced F1 score)
- **Bias-free design** (5 fixes applied):
  1. Self-reviews excluded from peer metrics — `_canonicalise_model()` strips fallback suffixes, then skips reviewer == response author
  2. TP/FP/FN averaged per peer reviewer (not raw-summed) for equal distribution
  3. No rank-position fallback — missing claims → zero metrics, not fabricated numbers
  4. Synthetic criteria use uniform multipliers (all 1.0, no dimension-specific bias)
  5. Overall council grounding uses equal weighting (simple average, not rank-weighted harmonic)
- **Context Awareness (Catastrophic Forgetting Detection)**:
  - Self-review data collected separately in `self_claims_per_label` (NOT discarded)
  - Self-reviews excluded from peer metrics but repurposed for self-consistency measurement
  - A model that marks its own claims as FP or fails to detect them (FN) during anonymized self-review exhibits catastrophic forgetting
  - Score: `self_TP / (self_TP + self_FP + self_FN)` — severity: Strong ≥80%, Moderate ≥60%, Weak <60%
- **Enhanced CA (Multi-Round + Adversarial Shuffling)**:
  - `stage2_ca_validation_pass()` in council.py runs a lightweight claims-only self-review probe per model
  - Paragraphs in the model's own response are **shuffled** before re-evaluation (adversarial)
  - Runs in **parallel with Stage 3** (no added latency to user-visible pipeline)
  - `enhance_ca_with_validation()` in grounding.py merges Round 1 (original Stage 2) + Round 2 (validation pass) data
  - Enhanced metrics: `round1_score`, `round2_score`, `stability` (1−|R1−R2|), `adversarial_delta`, `combined_score` ((R1+R2)/2)
  - Stability score: high = robust self-awareness, low = position-sensitive forgetting
  - Adversarial delta: large |Δ| = content-order-dependent recognition → brittle
- **Cross-Session CA Tracking**:
  - `store_ca_snapshot()` in memory.py persists per-model CA data after each council run
  - `get_ca_trend(model)` retrieves historical CA snapshots for degradation analysis
  - `get_ca_trends_all_models()` returns trends for all models
  - Stored in episodic collection with `type: "ca_snapshot"` for audit trail
  - SSE event `ca_validation_complete` includes updated grounding_scores for live frontend refresh
- `compute_response_grounding_scores()` returns `peer_reviews` count per response for transparency
- Formulas:
  - Correctness = TP/(TP+2×FN+FP) — pharma-weighted (penalises missed safety info)
  - F1 (RAGAS) = TP/(TP+0.5×(FP+FN)) — balanced Factual Correctness
  - Precision = TP/(TP+FP)
  - Recall = TP/(TP+FN)
  - Context Awareness = self_TP/(self_TP+self_FP+self_FN)
  - CA Stability = 1 − |round1 − round2|
  - CA Combined = (round1 + round2) / 2

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000
- POST `/api/conversations/{id}/message` returns metadata in addition to stages
- Metadata includes: label_to_model mapping and aggregate_rankings
- SSE pipeline includes `ca_validation_complete` event (with enhanced grounding_scores) after Stage 3 and `agent_team_complete` event after cost_summary

**`agents.py`** — Agent Team (Post-Pipeline Intelligence)
- 7 specialised async agents that analyse council output in parallel:
  - 🔬 Research Analyst — topic coverage, data density, evidence breadth
  - 🛡️ Fact Checker — grounding validation, hallucination detection (TP/FP/FN)
  - ⚠️ Risk Assessor — safety signals, regulatory compliance flags
  - 🔍 Pattern Scout — consensus detection, recurring themes, rubric trends
  - 💡 Insight Synthesizer — cross-model analysis, novel connections, evidence gaps
  - 📊 Quality Auditor — rubric scores, completeness, cost efficiency
  - 🔗 Citation Supervisor — validates REFERENCES section, enriches plain-text refs with PubMed links, detects orphan tags & DOIs
- `enrich_stage3_citations()` — utility called in SSE pipeline BEFORE `stage3_complete` emission; auto-wraps italic article titles in PubMed search links, linkifies DOIs/PMIDs, and handles bare URLs
- `run_agent_team()` orchestrates all agents via `asyncio.gather` (non-fatal)
- Each agent returns `{agent_id, role, icon, summary, confidence, signals[], metadata, timestamp}`
- Each signal: `{kind, severity, title, detail, evidence?}` — severity: success/info/warning/critical

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- User messages wrapped in markdown-content class for padding

**`components/Stage1.jsx`**
- Tab view of individual model responses
- ReactMarkdown rendering with markdown-content wrapper

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count
- Explanatory text clarifies that boldface model names are for readability only

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion

**ThemeContext.jsx**
- React context providing `theme` ('dark'|'light'), `toggleTheme()`, `setTheme()`
- Persists to `localStorage` key `llm-council-theme`
- Respects `prefers-color-scheme` OS setting when no stored preference
- Sets `data-theme` attribute on `<html>` element and `color-scheme` CSS property

**ThemeToggle.jsx**
- Accessible Day/Night toggle with `role="switch"`, `aria-checked`, descriptive `aria-label`
- Animated sun/moon track with thumb that slides between positions
- Keyboard-operable (Enter/Space); reduced-motion and forced-colors safe
- Rendered in the Sidebar header-actions area

**PromptAtlas3D.jsx** — Intelligence Dashboard + Decision Tree
- Tabbed panel: "Agent Signals" (default) + "Decision Tree" views
- Agent Team Dashboard: ConfidenceRing (SVG), AgentCard (expandable), SignalBadge components
- Decision Tree: stage-by-stage flow (user → S1 → S2 → evidence → S3)
- Data flow fix: falls back to `metadata.evidence` when loaded from storage
- WCAG 3.0: `role="complementary"` landmark, `role="tablist/tab"`, `role="button"` + Enter/Space on all cards/nodes, `role="list/listitem"` on signals, `aria-expanded`, `aria-controls`, `aria-label`, min 24×24 targets

**Styling (`*.css`)**
- WCAG 3.0 dual-theme system (Night=dark, Day=light) via CSS custom properties
- Dark theme: `--bg-primary: #111827`, `--text-primary: #f2f3f5` (APCA Lc 93.5)
- Light theme: `--bg-primary: #f8fafc`, `--text-primary: #0f172a` (APCA Lc 94.7)
- `[data-theme="light"]` selector overrides all colour tokens in `index.css`
- Global markdown styling in `index.css` with `.markdown-content` class
- 12px padding on all markdown content to prevent cluttered appearance
- Focus ring: 3px solid `--border-focus` via `:focus-visible`
- `prefers-reduced-motion: reduce` disables all animations
- `forced-colors: active` for Windows High Contrast mode

## Key Design Decisions

### Stage 2 Prompt Format
The Stage 2 prompt is very specific to ensure parseable output:
```
1. Evaluate each response individually first
2. Provide "FINAL RANKING:" header
3. Numbered list format: "1. Response C", "2. Response A", etc.
4. No additional text after ranking section
```

This strict format allows reliable parsing while still getting thoughtful evaluations.

### De-anonymization Strategy
- Models receive: "Response A", "Response B", etc.
- Backend creates mapping: `{"Response A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- Users see explanation that original evaluation used anonymous labels
- This prevents bias while maintaining transparency

### Error Handling Philosophy
- Continue with successful responses if some models fail (graceful degradation)
- Never fail the entire request due to single model failure
- Log errors but don't expose to user unless all models fail

### UI/UX Transparency
- All raw outputs are inspectable via tabs
- Parsed rankings shown below raw text for validation
- Users can verify system's interpretation of model outputs
- This builds trust and allows debugging of edge cases

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) not absolute imports. This is critical for Python's module system to work correctly when running as `python -m backend.main`.

### Port Configuration
- Backend: 8001 (changed from 8000 to avoid conflict)
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing. This class is defined globally in `index.css`.

### Model Configuration
Models are hardcoded in `backend/config.py`. Chairman can be same or different from council members. The current default is Gemini as chairman per user preference.

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Missing Metadata**: Metadata is ephemeral (not persisted), only available in API responses

## Accessibility Testing

The frontend includes 89 automated WCAG 3.0 accessibility tests using Vitest + Testing Library:

```bash
cd frontend && npm test       # Run all 89 tests
npm run test:a11y              # Verbose output
npm run test:watch             # Watch mode
```

Reusable test utilities in `src/__tests__/a11y-utils.js`:
- `calcAPCA(textHex, bgHex)` — APCA contrast computation
- `assertAccessibleNames(container)` — verify all interactive elements have names
- `assertImageAlts(container)` — verify all images have alt text
- `assertHeadingOrder(container)` — verify heading hierarchy
- `getLandmarks(container)` — collect ARIA landmark roles

## Future Enhancement Ideas

- Configurable council/chairman via UI instead of config file ✅ (done)
- Streaming responses instead of batch loading ✅ (done)
- Export conversations to markdown/PDF ✅ (done)
- WCAG 3.0 accessibility + Day/Night mode ✅ (done)
- RAGAS-aligned grounding metrics (F1, Precision=Faithfulness, Recall=Context Recall) ✅ (done)
- Context Awareness / Catastrophic Forgetting detection via self-review ✅ (done)
- Model performance analytics over time
- Custom ranking criteria (not just accuracy/insight)
- Support for reasoning models (o1, etc.) with special handling

## Testing Notes

Use `test_openrouter.py` to verify API connectivity and test different model identifiers before adding to council. The script tests both streaming and non-streaming modes.

## Data Flow Summary

```
User Query
    ↓
Stage 1: Parallel queries → [individual responses]
    ↓
Stage 2: Anonymize → Parallel ranking queries → [evaluations + parsed rankings]
    ↓
Aggregate Rankings Calculation → [sorted by avg position]
    ↓
Stage 3: Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

The entire flow is async/parallel where possible to minimize latency.
