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
- **Relevancy Gate** (`compute_relevancy_gate()`):
  - Aggregates per-response Relevancy rubric scores across Stage 2 reviewers
  - Any response with avg relevancy < 5.0/10 across ≥2 reviewers is **gated out**
  - Gated labels are annotated with ⛔ in the Stage 3 chairman prompt
  - Constants: `RELEVANCY_GATE_THRESHOLD = 5.0`, `RELEVANCY_GATE_MIN_REVIEWERS = 2`
- **Chairman Anti-Drift Rules** (Guidelines 0a–0c in `_SYSTEM_MSG_BASE`):
  - 0a: MUST NOT incorporate excluded ⛔ responses
  - 0b: Only incorporate insights that DIRECTLY ADDRESS original question
  - 0c: Every piece must pass "Does this directly help answer the user's question?" test

**`storage.py`** — Triple-Mode Conversation Storage (Cosmos DB + Azure Blob + Local Files)
- **Cloud users (primary)** → Azure Cosmos DB (`COSMOS_ENDPOINT` + `COSMOS_KEY` env vars)
  - Database: `llm-council`, Container: `conversations`, Partition key: `/user_id`
  - Auto-creates database and container on first use (`create_if_not_exists`)
- **Cloud users (legacy fallback)** → Azure Blob Storage (when Cosmos is not configured)
  - Storage account: `llmcouncilmga` in `rg-llmcouncil`
  - 4 dedicated containers: `conversations`, `attachments`, `memory`, `skills`
  - Env vars: `AZURE_BLOB_CONVERSATIONS_CONTAINER`, `AZURE_BLOB_ATTACHMENTS_CONTAINER`, `AZURE_BLOB_MEMORY_CONTAINER`, `AZURE_BLOB_SKILLS_CONTAINER`
- **Local dev** (`user_id == "local-user"`) → file-based at `data/conversations/local-user/{conversation_id}.json`
- Backend selection priority: local-user → Cosmos DB → Blob Storage
- `user_id` is extracted from the `user-id` HTTP header (injected by reverse proxy in cloud, hardcoded as `local-user` in dev)
- Every public function takes `user_id` as its first parameter
- Cosmos DB documents include `user_id` field for partition routing; system props (`_rid`, `_etag`, etc.) are stripped on read
- Path traversal protection: rejects `user_id` containing `/`, `\`, or `..`
- Cosmos client is lazy-initialised (one per process)
- Each conversation: `{id, user_id, created_at, messages[]}`
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

**`memory.py`** — Three-Tier Memory + User Profile + ECA
- **UserProfileMemory** (behaviour learning):
  - `classify_query(query)` → auto-classifies by domain (pharma/chemistry/regulatory/market_access/data_science), question_type, complexity
  - `record_interaction(user_id, query, grounding_score, relevancy_violations, ...)` → stores per-session profile data
  - `get_user_profile(user_id)` → aggregated profile: domain_affinity, question_patterns, avg_grounding, relevancy_violation_rate, warning_level
  - `format_user_context(user_id)` → prompt-injectable text block (triggers "⚠️ HIGH VIOLATION RATE" warning when rate > 30%)
  - Stored in episodic collection with `type: "user_profile_interaction"` for per-user partitioning
- **Experiential Co-Adaptation (ECA)** — Memory × Skills pairing (arXiv 2602.03837, 2511.00926, 2602.13949v1):
  - Reward signal: R(t) = α·Quality + β·Efficiency + γ·Coverage (α=0.4, β=0.3, γ=0.3)
    - Quality = avg reranker relevance score of returned citations
    - Efficiency = 1 − (avg_latency / max_latency)
    - Coverage = unique_skills_hit / 28 total skills
  - EMA temporal smoothing: θ(t+1) = λ·θ(t) + (1−λ)·f(R(t)), λ=0.7
  - Three adaptation functions:
    1. `adapt_prompt(user_id, user_profile, reward)` → adjusts evidence_weight, safety_weight, precision_weight for chairman prompt emphasis
    2. `adapt_rubric(user_id, user_profile, grounding_scores)` → adjusts rubric weight distribution (normalised to sum=5.0) based on violation rates and grounding
    3. `adapt_learning(user_id, reward, grounding_score)` → adjusts auto_learn_threshold (0.5–0.9) and confidence_decay (0.005–0.05) using EMA reward
  - `run_full_adaptation()` → orchestrates all 3 functions in sequence
  - Per-user ECA state persisted in episodic collection with `type: "eca_state"`
  - Singletons: `get_user_profile_memory()`, `get_eca()`
**`main.py`**
- FastAPI app with CORS enabled for all origins
- `get_user_id` dependency: extracts `user-id` header from request, validates against path traversal, required on all `/api/conversations/*` endpoints
- POST `/api/conversations/{id}/message` returns metadata in addition to stages
- Metadata includes: label_to_model mapping and aggregate_rankings
- SSE pipeline includes `ca_validation_complete` event (with enhanced grounding_scores) after Stage 3 and `agent_team_complete` event after cost_summary
- **Entra ID SSO**: when `ENTRA_SSO_ENABLED=true`, all endpoints require a valid JWT Bearer token via `backend/auth.py`
- **Health Probe Agent**: periodic background health checks via `backend/health_probe.py`
  - Endpoints: `/api/health/deep`, `/api/health/history`, `/api/health/failures`
  - Background task runs every 5 minutes, logs warnings for degraded/critical status
  - Checks: Cosmos DB, API key expiry, memory store, model sync, resilience subsystem

**`auth.py`** — Entra ID JWT Validation
- Downloads JWKS from `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys`
- Validates RS256 tokens: issuer, audience (`ENTRA_CLIENT_ID`), expiry, `kid` matching
- `validate_token()` returns decoded claims or raises `HTTPException(401)`
- `get_current_user` FastAPI dependency: extracts Bearer token, validates, returns claims
- Enabled/disabled via `ENTRA_SSO_ENABLED` env var (disabled in local dev by default)
- Env vars: `ENTRA_SSO_ENABLED`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`

**`agents.py`** — Agent Team (Post-Pipeline Intelligence)
- 12 specialised async agents (9 core + 3 VP-mode) that analyse council output in parallel:
  - 🔬 Research Analyst — topic coverage, data density, evidence breadth
  - 🛡️ Fact Checker — grounding validation, hallucination detection (TP/FP/FN)
  - ⚠️ Risk Assessor — safety signals, regulatory compliance flags
  - 🔍 Pattern Scout — consensus detection, recurring themes, rubric trends
  - 💡 Insight Synthesizer — cross-model analysis, novel connections, evidence gaps
  - 📊 Quality Auditor — rubric scores, completeness, cost efficiency
  - 🔗 Citation Supervisor — validates REFERENCES section, enriches plain-text refs with PubMed links, detects orphan tags & DOIs
  - 🧰 Skills Manager — monitors 28-skill evidence pipeline health, diversity analysis, performance benchmarking
  - 🧠 Memory Orchestrator — orchestrates 3-tier memory (Semantic/Episodic/Procedural), drift detection, CA trend analysis
  - 📈 Market Positioning — VP-mode: competitive landscape & differentiation
  - 🏥 Clinical Value — VP-mode: clinical evidence strength & safety profile
  - 📣 Messaging Strategist — VP-mode: communication strategy & audience targeting
- `enrich_stage3_citations()` — utility called in SSE pipeline BEFORE `stage3_complete` emission; auto-wraps italic article titles in PubMed search links, linkifies DOIs/PMIDs, and handles bare URLs
- `run_agent_team()` orchestrates all agents via `asyncio.gather` (non-fatal)
- Each agent returns `{agent_id, role, icon, summary, confidence, signals[], metadata, timestamp}`
- Each signal: `{kind, severity, title, detail, evidence?}` — severity: success/info/warning/critical

### Frontend Structure (`frontend/src/`)

**`authConfig.js`** — MSAL Configuration
- Configures `@azure/msal-browser` PublicClientApplication
- Authority: `https://login.microsoftonline.com/{tenantId}`
- Client ID: `a73fe3b0-6f94-4093-ba33-441d25772636` (App Reg: `llmcouncil-agents`)
- SPA Redirect URIs: `http://localhost:5173`, `https://llmcouncil-frontend.azurewebsites.net`, `https://llmcouncil-agents.ai`
- Login scopes: `openid`, `profile`, `email`

**`main.jsx`**
- Wraps `<App />` in `<MsalProvider>` for Entra ID SSO
- MSAL initialisation is async (`msalInstance.initialize()`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- **SSO gating**: when `VITE_ENV=azure`, renders login screen until Entra ID authentication completes
- **RAF-batched SSE updates**: replaces `flushSync` — coalesces 20+ SSE events into ~1-2 React renders per frame
- **Deduplicated `loadConversations`**: guard ref prevents parallel fetches on `title_complete` + `complete` events
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- User messages wrapped in markdown-content class for padding
- **Code-split Stage imports**: Stage1/Stage2/Stage3 loaded via `React.lazy()` with `<Suspense>` boundaries

**`components/SciMarkdown.jsx`** — Scientific Markdown Renderer
- `React.memo` wrapped — prevents re-parsing on parent re-renders
- `REMARK_PLUGINS` and `REHYPE_PLUGINS` arrays hoisted to module scope (stable references)
- `DEFAULT_COMPONENTS` object hoisted; only merges when `extraComponents` is provided
- Mol3DViewer resize handler uses `[status]` dependency array (fixes memory leak)

**`components/Stage1.jsx`**
- Tab view of individual model responses
- `React.memo` wrapped, tab labels memoized with `useMemo`

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count
- Explanatory text clarifies that boldface model names are for readability only
- `React.memo` wrapped, `deAnonymizedText` memoized with `useMemo`

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion
- `React.memo` wrapped, `linkifyCitations` memoized with `useMemo` (avoids 15+ regex passes per render)
- `CITATION_LINK_COMPONENTS` hoisted to module scope

**`components/GroundingScore.jsx`**
- Circular grounding score bubble with per-criteria breakdown
- `React.memo` wrapped

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

### User-ID Data Isolation & Azure Cosmos DB
- **Cloud (primary)**: conversations stored in Azure Cosmos DB, partitioned by `user_id` for per-user isolation
  - Database: `llm-council`, Container: `conversations`, Partition key: `/user_id`
  - Env vars: `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE`, `COSMOS_CONVERSATIONS_CONTAINER`
- **Cloud (legacy)**: Azure Blob Storage fallback when Cosmos is not configured
  - Storage account: `llmcouncilmga`, 4 containers: `conversations`, `attachments`, `memory`, `skills`
  - Env vars: `AZURE_BLOB_CONVERSATIONS_CONTAINER`, `AZURE_BLOB_ATTACHMENTS_CONTAINER`, `AZURE_BLOB_MEMORY_CONTAINER`, `AZURE_BLOB_SKILLS_CONTAINER`
- **Local dev**: file-based storage at `data/conversations/local-user/` (detected by `user_id == "local-user"`)
- The `user-id` HTTP header is injected by the reverse proxy in cloud deployments
- In local development, `frontend/src/api.js` sends `user-id: local-user` automatically
- `get_user_id` FastAPI dependency (in `main.py`) extracts/validates the header on every conversation endpoint
- Path traversal attacks are blocked: `user_id` values containing `/`, `\`, or `..` are rejected with HTTP 400
- Cosmos DB provides built-in encryption at rest and per-partition data isolation
- **Memory management**: also uses Cosmos DB (container: `memory`, partition: `/collection`) when configured
  - `CosmosDBBackend` in `memory_store.py` implements the `MemoryStoreBackend` ABC
  - Falls back to `LocalJSONBackend` (file-based) when Cosmos is not configured

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

### Python Runtime
- **Python 3.13.5** (`C:\Python313\python.exe`), venv at `myenv/`
- Backend dependencies: `PyJWT[crypto]` for Entra ID JWT validation (RS256)
- Run backend: `python -m backend.main` from project root

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

## Performance Optimizations

### SSE Stream Rendering (P0 — Critical Path)
- **RAF-batched state updates**: `flushSync` replaced with `requestAnimationFrame` batching in `App.jsx`
  - `batchedStreamUpdate()` chains updater functions into a single ref
  - Single RAF callback flushes all pending updaters in one `setCurrentConversation` call
  - Collapses 20+ SSE events per frame into ~1-2 React renders
  - Cleanup on unmount via `cancelAnimationFrame`
- **SciMarkdown memoization**: `React.memo` wrapper prevents re-parsing all visible markdown on every state change
  - `REMARK_PLUGINS` / `REHYPE_PLUGINS` arrays hoisted to module scope (stable identity)
  - `DEFAULT_COMPONENTS` hoisted; component merge only when `extraComponents` provided
- **linkifyCitations memoization**: `useMemo` in Stage3 keyed on `[response, citations]` avoids 15+ regex passes per render

### Component Memoization (P1)
- `Stage1`, `Stage2`, `Stage3`, `GroundingScore` all wrapped in `React.memo`
- `deAnonymizedText` in Stage2 memoized via `useMemo` keyed on `[rankings, activeTab, labelToModel]`
- Tab labels memoized in Stage1/Stage2 with `useMemo`
- `loadConversations` deduplicated with guard ref (`loadingConvsRef`)

### Code Splitting (P2)
- **Vite manual chunks** in `vite.config.js`:
  - `3dmol` (561 KB) — heavy 3D molecule viewer, loaded on demand
  - `katex` (267 KB) — LaTeX math rendering
  - `markdown` (322 KB) — react-markdown + remark/rehype plugins
  - `msal` (221 KB) — Azure authentication library
- **React.lazy** for Stage1/Stage2/Stage3 in `ChatInterface.jsx`
  - Each Stage loaded only when first rendered (with `<Suspense>` fallback)
  - Stage1: 0.8 KB, Stage2: 9.5 KB, Stage3: 6.4 KB — negligible lazy overhead

### Hardware / GPU Acceleration (P2)
- **`.messages-container`**: `will-change: scroll-position` + `transform: translateZ(0)` + `contain: layout style`
  - Promotes scroll container to dedicated GPU compositing layer
  - Eliminates paint jank on long conversations during SSE streaming
- **`.message-group`**: `contain: content`
  - Each message composited independently — only newly-arriving messages paint
  - Previous messages served from GPU texture cache
- Mol3DViewer resize handler: `[status]` dependency array fixes event listener leak

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Missing Metadata**: Metadata is ephemeral (not persisted), only available in API responses
5. **Missing `user-id` Header**: All `/api/conversations/*` endpoints require a `user-id` header. In cloud the reverse proxy injects it; locally the frontend sends `local-user`. Direct curl/Postman calls must include `-H "user-id: test-user"` or the request will return HTTP 422

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
- Entra ID SSO (MSAL frontend + JWT backend) ✅ (done)
- Frontend performance optimisation (RAF batching, memo, code splitting, GPU accel) ✅ (done)
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

## Azure CLI Login

**Always use these steps for `az login`:**
1. Set `$env:AZURE_CLI_DISABLE_CONNECTION_VERIFICATION = "1"` (Bayer corporate proxy intercepts TLS with self-signed cert)
2. Run `az login`
3. Select subscription **AZS1799_codingagent4clinical** (`24cbffca-ac7d-4f7f-9da9-88f62339afe9`) — this is the project's subscription, always use it
4. If subscription selection was skipped or wrong, run: `az account set --subscription "24cbffca-ac7d-4f7f-9da9-88f62339afe9"`
5. Ignore the GHH tenant MFA error and Asklepios tenant warning — they are irrelevant

## Azure Deployment Architecture

### Infrastructure
- **Resource Group**: `rg-llmcouncil` (East US)
- **App Service Plan**: `asp-llmcouncil` (Linux, S2 Standard tier, shared by both apps)
- **Backend**: `llmcouncil-backend.azurewebsites.net` — Python/FastAPI, Gunicorn
- **Frontend**: `llmcouncil-frontend.azurewebsites.net` — Node.js 24 LTS, Express 5 SPA server
- **Bayer Policy**: All webapps MUST use `--https-only true` (RequestDisallowedByPolicy otherwise)

### Frontend Deployment (`frontend/`)

**Key Files:**
- `server.js` — Express 5 SPA server (serves `dist/` static files with SPA fallback)
- `.env.azure` — `VITE_ENV=azure` for Vite build
- `src/enviroments/env.js` — AZURE environment config pointing to backend URL

**Build & Deploy Process:**
1. Build: `cd frontend && npx vite build --mode azure` (creates `dist/`)
2. Create staging dir with: `server.js`, `package.json` (express only), `dist/`, `node_modules/`
3. Create ZIP using .NET `ZipFile` API with **forward slashes** (critical — `Compress-Archive` uses backslashes which break on Linux)
4. Deploy: `az webapp deploy --name llmcouncil-frontend --resource-group rg-llmcouncil --src-path <zip> --type zip`

**App Settings:**
- `SCM_DO_BUILD_DURING_DEPLOYMENT=false` (Oryx build disabled — we deploy pre-built)
- `WEBSITE_NODE_DEFAULT_VERSION=~24`
- Startup command: `node server.js`

**Critical Gotchas:**
- **Express 5 Wildcards**: Express 5 uses path-to-regexp v8 — bare `*` wildcards are invalid. Use `/{*path}` instead of `*` for SPA fallback routes.
- **ZIP Path Separators**: PowerShell `Compress-Archive` creates ZIPs with Windows backslash separators (`\`). Linux App Service `rsync` fails with `Invalid argument (22)` on these paths. Must use .NET `ZipFile` API with explicit `Replace('\', '/')`.
- **PowerShell Pipe Character**: When passing values containing `|` (like `NODE|24-lts`) to `az`, use the `az --%` stop-parsing token.
- **Include node_modules**: Since `SCM_DO_BUILD_DURING_DEPLOYMENT=false`, run `npm install --omit=dev` in staging before zipping.

### Frontend API Integration
- `api.js` detects `VITE_ENV=azure` and routes API calls to `https://llmcouncil-backend.azurewebsites.net`
- Sends `user-id: azure-user` header for user identification
- Backend CORS is `allow_origins=["*"]` (permissive for now)

### Backend Deployment (`deploy/deploy_backend.ps1`)

**Key Files:**
- `deploy/deploy_backend.ps1` — ZIP deploy via Kudu API with TrustAllCertsPolicy
- `run_server.py` — Azure App Service entry point (sets PYTHONPATH, starts uvicorn)
- `startup.sh` — Backup startup script (handles output.tar.gz extraction if Oryx doesn't)
- `requirements.txt` — Python dependencies (installed by Oryx build)

**Build & Deploy Process:**
1. Copy backend source + `run_server.py` + `requirements.txt` to staging dir
2. Create ZIP using .NET `ZipFile.Open()` API with **forward-slash paths** (critical!)
3. Deploy: POST to Kudu `/api/zipdeploy?isAsync=true`
4. Oryx build runs: `pip install -r requirements.txt` into `antenv/`, compresses to `output.tar.gz`
5. Set startup command: `python run_server.py`

**App Settings:**
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` (Oryx builds venv from requirements.txt)
- `WEBSITES_PORT=8000`
- Startup command: `python run_server.py`

**Critical Gotchas:**
- **ZIP Path Separators (CRITICAL)**: Both `Compress-Archive` AND `[ZipFile]::CreateFromDirectory()` create entries with Windows backslash separators. On Linux, `backend\main.py` becomes a **single flat filename** (backslash is valid in Linux filenames), not `backend/main.py` in a directory. Must use `[ZipFile]::Open()` with manual entry creation and `.Replace('\', '/')`. This caused recurring `ModuleNotFoundError: No module named 'backend'` crashes.
- **Oryx CompressDestinationDir**: Oryx sets `CompressDestinationDir=true`, packing the build output into `output.tar.gz` in wwwroot. The container's init script extracts it to `/tmp/{hash}/` before running the startup command.
- **PYTHONPATH**: `run_server.py` adds its own directory to `sys.path` and `PYTHONPATH` env var. Oryx also sets PYTHONPATH to include the antenv site-packages directory.
- **Custom startup.sh Pitfall**: Do NOT use `bash startup.sh` as the startup command if `startup.sh` does `cd /home/site/wwwroot` — Oryx extracts files to `/tmp/{hash}/`, not wwwroot. Use `python run_server.py` directly and let Oryx's wrapper handle extraction.

### Entra ID SSO (Azure Deployment)
- **Frontend** (`@azure/msal-browser` + `@azure/msal-react`):
  - `authConfig.js` configures MSAL PublicClientApplication
  - `main.jsx` wraps `<App>` in `<MsalProvider>`
  - `api.js` acquires Bearer tokens via `acquireTokenSilent` (auto-refresh)
  - `App.jsx` gates UI behind `useIsAuthenticated()` when `VITE_ENV=azure`
- **Backend** (`backend/auth.py` + `PyJWT[crypto]`):
  - Downloads JWKS from Entra ID; validates RS256 JWT (iss, aud, exp, kid)
  - `get_current_user` FastAPI dependency injected on all API routes when enabled
  - Toggle: `ENTRA_SSO_ENABLED=true/false` env var
- **App Registration**: `llmcouncil-agents` (Client ID: `a73fe3b0-6f94-4093-ba33-441d25772636`)
  - SPA Redirect URIs: `http://localhost:5173`, `https://llmcouncil-frontend.azurewebsites.net`, `https://llmcouncil-agents.ai`
- **Backend App Settings**: `ENTRA_SSO_ENABLED=true`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`
