# LLM Council MGA — System Architecture

> **Version 2.0** | Bayer Pharmaceutical Division — myGenAssist  
> Last updated: February 10, 2026

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Flow — 3-Stage Pipeline](#2-data-flow--3-stage-pipeline)
3. [Evidence Skills Pipeline](#3-evidence-skills-pipeline)
4. [Scientific Markdown Rendering](#4-scientific-markdown-rendering)
5. [Value Proposition Map](#5-value-proposition-map)
6. [Component Details](#6-component-details)
7. [Technology Stack](#7-technology-stack)
8. [Self-Healing & Resilience](#8-self-healing--resilience)
9. [Grounding Score & Verbalized Sampling](#9-grounding-score--verbalized-sampling)
10. [Cost & Token Tracking](#10-cost--token-tracking)
11. [Memory Management Pipeline](#11-memory-management-pipeline)
12. [Production Deployment](#12-production-deployment)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        LLM COUNCIL MGA — SYSTEM ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  FRONTEND — React 19 + Vite 7                                            :5173  │
  │                                                                                  │
  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
  │  │   Chat   │  │ Settings │  │  Memory  │  │  Kill    │  │   Decision Tree  │  │
  │  │Interface │  │  Panel   │  │  Panel   │  │  Switch  │  │   (PromptAtlas)  │  │
  │  └────┬─────┘  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘  │
  │       │                                                                          │
  │  ┌────▼──────────────────────────────────────────────────────────────────┐       │
  │  │  SciMarkdown — SMILES + LaTeX/KaTeX + GFM Tables + Figures + Code   │       │
  │  └──────────────────────────────────────────────────────────────────────┘       │
  │       │                                                                          │
  │  ┌────▼─────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
  │  │ Stage 1  │  │ Stage 2  │  │ Stage 3  │  │Grounding │  │ Token Burndown   │  │
  │  │Individual│  │PeerReview│  │ Chairman │  │  Score   │  │ Cost Dashboard   │  │
  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘  │
  └───────────────────────┬──────────────────────────────────────────────────────────┘
                          │ Vite Proxy /api/* → :8001
  ┌───────────────────────▼──────────────────────────────────────────────────────────┐
  │  BACKEND — FastAPI + Uvicorn                                             :8001  │
  │                                                                                  │
  │  ┌──────────────────────────────────────────────────────────────────────────┐    │
  │  │  main.py — Routes, SSE Streaming, Session Management                     │    │
  │  └───┬──────────┬──────────────┬──────────────┬─────────────┬──────────────┘    │
  │      │          │              │              │             │                    │
  │  ┌───▼───┐  ┌──▼──────┐  ┌───▼──────┐  ┌───▼────────┐ ┌──▼──────────────┐    │
  │  │Council│  │ Skills  │  │Resilience│  │Orchestrator│ │ Token Tracking  │    │
  │  │3-Stage│  │Evidence │  │Kill+CB+  │  │4 Stage-Gate│ │ Cost Calculator │    │
  │  │       │  │OpenFDA  │  │Retry+    │  │  Agents    │ │                 │    │
  │  │Verbal.│  │CT.gov   │  │Fallback  │  │            │ │ Gateway vs      │    │
  │  │Samplng│  │PubMed   │  │Quorum    │  │            │ │ Direct Pricing  │    │
  │  └───┬───┘  └────┬────┘  └──────────┘  └────────────┘ └─────────────────┘    │
  │      │           │                                                              │
  │  ┌───▼───────────▼──────────────────────────────────────────┐                   │
  │  │  openrouter.py — Async httpx Client → myGenAssist API     │                   │
  │  │  https://chat.int.bayer.com/api/v2/chat/completions       │                   │
  │  └──────────────────────────────────────────────────────────┘                   │
  │                                                                                  │
  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐               │
  │  │  Storage (JSON)  │  │  Memory 3-Tier   │  │  Grounding Score │               │
  │  │  Conversations   │  │  Semantic/Epi/   │  │  Hybrid Verbal.  │               │
  │  │  data/convos/    │  │  Procedural      │  │  + Synthetic     │               │
  │  └──────────────────┘  └──────────────────┘  └──────────────────┘               │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow — 3-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         3-STAGE DELIBERATION PIPELINE                                 │
└─────────────────────────────────────────────────────────────────────────────────────┘

  USER QUERY
       │
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │  PRE-STAGE 1: Memory Recall Agent                       │
  │  • Recall semantic + procedural memories                │
  │  • Compute influence score                              │
  │  • Augment query with remembered context                │
  │  → SSE: memory_recall                                   │
  └───────────────────────┬─────────────────────────────────┘
                          │
  ╔═══════════════════════╧═══════════════════════════════════╗
  ║  STAGE 1: Individual Responses                            ║
  ║                                                           ║
  ║  Query → [Claude 4.5] → Response A  ─┐                   ║
  ║  Query → [Gemini 2.5] → Response B  ─┤  Parallel         ║
  ║  Query → [GPT-5 Mini] → Response C  ─┤  (asyncio.gather) ║
  ║  Query → [Grok 3    ] → Response D  ─┘                   ║
  ║                                                           ║
  ║  Verbalized Sampling: Each response includes             ║
  ║  self-assessed Correctness, Precision, Recall            ║
  ║                                                           ║
  ║  → SSE: stage1_start → stage1_response × N → stage1_complete ║
  ╚═══════════════════════╤═══════════════════════════════════╝
                          │
                          │  ┌──── Parallel Task ──────────────────────┐
                          │  │  Evidence Skills Pipeline               │
                          │  │  OpenFDA + ClinicalTrials + PubMed     │
                          │  │  → SSE: evidence_complete               │
                          │  └─────────────────────────────────────────┘
                          │
  ╔═══════════════════════╧═══════════════════════════════════╗
  ║  STAGE 2: Anonymized Peer Review                          ║
  ║                                                           ║
  ║  Responses shuffled & anonymized (Response 1, 2, 3, 4)   ║
  ║  Each model reviews ALL responses blind:                  ║
  ║                                                           ║
  ║  Evaluation uses RUBRIC + CLAIMS + RANKING format:        ║
  ║  • RUBRIC: scored criteria per response                   ║
  ║  • CLAIMS: TP/FP/FN identification per response           ║
  ║  • RANKING: ordered list best-to-worst                    ║
  ║                                                           ║
  ║  Rankings aggregated → Grounding Score computed            ║
  ║  → SSE: stage2_start → stage2_ranking × N → stage2_complete ║
  ╚═══════════════════════╤═══════════════════════════════════╝
                          │
  ┌───────────────────────▼─────────────────────────────────┐
  │  POST-STAGE 2: Memory Gate Agent                        │
  │  • Compare grounding to historical baseline             │
  │  • Anomaly detection (±15% deviation)                   │
  │  → SSE: memory_gate                                     │
  └───────────────────────┬─────────────────────────────────┘
                          │
  ╔═══════════════════════╧═══════════════════════════════════╗
  ║  STAGE 3: Chairman Synthesis                              ║
  ║                                                           ║
  ║  Chairman (Claude Opus 4.5 by default) receives:         ║
  ║  • All Stage 1 responses with rankings                   ║
  ║  • Peer review evaluations                               ║
  ║  • Evidence citations (from parallel skills task)        ║
  ║  • Memory context                                        ║
  ║                                                           ║
  ║  Chairman produces citation-grounded synthesis:           ║
  ║  • [FDA-L1], [CT-2], [PM-3] tags → clickable links      ║
  ║  • Rich output: tables, SMILES blocks, LaTeX math        ║
  ║  • 7+ guideline prompt framework                         ║
  ║                                                           ║
  ║  → SSE: stage3_start → stage3_complete                    ║
  ╚═══════════════════════╤═══════════════════════════════════╝
                          │
  ┌───────────────────────▼─────────────────────────────────┐
  │  POST-STAGE 3: Learning Agent                           │
  │  • Grounding ≥ 0.75 → auto-learn all tiers             │
  │  • 0.50–0.74 → pending (ask user)                      │
  │  • < 0.50 → episodic record only                       │
  │  → SSE: memory_learning → cost_summary → complete       │
  └─────────────────────────────────────────────────────────┘
```

### API Request Flow

```
  POST /api/conversations/{id}/stream
  Body: { content, council_models, chairman_model, attachments }

  → SSE events emitted in order:
     session_start → memory_recall
     → stage1_start → stage1_response ×N → stage1_complete
     → stage2_start → stage2_ranking ×N → stage2_complete
     → evidence_complete (parallel with stage2)
     → memory_gate
     → stage3_start → stage3_complete
     → cost_summary → memory_learning → complete
```

---

## 3. Evidence Skills Pipeline

The skills module (ackend/skills.py) retrieves real-time pharmaceutical evidence in **parallel with Stage 2**, injecting citations into the Stage 3 chairman prompt.

### Data Sources

| Skill | API | Data Retrieved | Timeout |
|-------|-----|----------------|---------|
| **OpenFDA** | pi.fda.gov | Drug labels, adverse events, indications | 12s |
| **ClinicalTrials.gov** | clinicaltrials.gov/api/v2 | Active trials (Phase I–IV), conditions, interventions | 12s |
| **PubMed** | eutils.ncbi.nlm.nih.gov | Recent publications, abstracts, authors | 12s |

### Architecture

```
  User Query (pharma-related)
       │
       ├──► OpenFDA: drug label search ────────┐
       ├──► ClinicalTrials: study search ──────┤ asyncio.gather (parallel)
       └──► PubMed: article search ────────────┘
                                                │
                                    ┌───────────▼───────────┐
                                    │    Deduplication &     │
                                    │    Citation Tagging    │
                                    │                       │
                                    │  [FDA-L1] Label ref   │
                                    │  [FDA-A2] Adverse evt │
                                    │  [CT-1]  Trial ref    │
                                    │  [PM-1]  PubMed ref   │
                                    │                       │
                                    │  Max: 5 per skill     │
                                    │  Max: 12 total        │
                                    └───────────┬───────────┘
                                                │
                                    format_citations_for_prompt()
                                                │
                                    Injected into Stage 3 chairman prompt
                                    as evidence_context parameter
```

### Citation Format

The chairman references evidence using tags that the frontend converts to clickable links:

| Tag Format | Source | Example |
|------------|--------|---------|
| [FDA-L1] | OpenFDA Drug Label | Links to DailyMed |
| [FDA-A2] | OpenFDA Adverse Event | Links to FDA report |
| [CT-1] | ClinicalTrials.gov | Links to NCT page |
| [PM-1] | PubMed | Links to article |

### Frontend Rendering

- **Stage3.jsx**: linkifyCitations() replaces [FDA-L1] tags with markdown links
- **Evidence Panel**: Collapsible sidebar with source badges (FDA/CT/PM) and direct URLs
- **SSE Event**: evidence_complete delivers citations array with benchmark timing

---

## 4. Scientific Markdown Rendering

The SciMarkdown component provides unified rich rendering across all stages.

### Capabilities

| Feature | Syntax | Renderer |
|---------|--------|----------|
| **2D Molecular Structures** | ``smiles / ``smi / ``mol code blocks | smiles-drawer SvgDrawer |
| **3D Molecular Viewer** | Toggle button on any SMILES block | 3Dmol.js (WebGL) + PubChem SDF |
| **Broken Image Fallback** | `![Chemical structure of X](url)` | Auto-detects molecule names → renders SMILES |
| **LaTeX Math** | $...$ inline, $$...$$ block | KaTeX via rehype-katex |
| **GFM Tables** | Standard GFM pipe tables | remark-gfm → styled table |
| **Figures** | <img> tags with alt text | Auto-wrapped in <figure> + caption |
| **Sub/Superscript** | <sub>, <sup> HTML | rehype-raw passthrough |
| **Code Blocks** | Standard fenced code | Highlighted with copy button |
| **Task Lists** | - [x] / - [ ] | remark-gfm checkboxes |
| **Multi-Modal Images** | Gemini image generation | Inline image rendering from model output |

### Component Architecture

```
  <SciMarkdown content={text}>
       │
       ├── remarkGfm          (tables, task lists, autolinks)
       ├── remarkMath          (detect $ and $$ delimiters)
       ├── rehypeRaw           (pass-through HTML tags)
       ├── rehypeKatex         (render math as KaTeX)
       │
       └── Custom Components:
           ├── CodeBlock        → intercepts smiles/smi/mol → SmilesBlock
           │                      SmilesBlock has 2D/3D toggle:
           │                        2D → smiles-drawer SvgDrawer (fast SVG)
           │                        3D → 3Dmol.js WebGL viewer
           │                             └── PubChem REST API (SMILES → SDF)
           ├── FigureImage      → wraps <img> in <figure> + <figcaption>
           │                      onError → broken-image fallback:
           │                        molecule-name detection (20+ common drugs)
           │                        auto-renders as SmilesBlock if match found
           └── SciTable         → wraps <table> in scrollable container
```

### 3D Molecular Viewer Pipeline

```
  User sees SMILES block → clicks "3D" toggle
       │
       ▼
  Lazy-load 3Dmol.js (WebGL, ~575 KB chunk)
       │
       ▼
  Fetch 3D SDF from PubChem REST API:
    https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{smiles}/SDF?record_type=3d
       │
       ├── 3D conformer available → load into 3Dmol viewer
       │     Style: ball-and-stick (Jmol colorscheme)
       │     Features: click-drag rotate, scroll zoom, auto-spin
       │
       └── 3D not available → fallback to 2D SDF → error message if both fail
```

### Broken Molecule Image Fallback

When an LLM outputs `![Chemical structure of caffeine](broken-url)` instead of a SMILES code block, the `FigureImage` component:
1. Detects the broken `<img>` via `onError` handler
2. Extracts molecule name from alt text against a dictionary of 20+ common pharmaceuticals
3. If matched → renders an interactive `SmilesBlock` (with 2D/3D toggle) instead of a broken image
4. If no match → shows a styled placeholder with the alt text

### Usage

SciMarkdown is used in **Stage1.jsx**, **Stage2.jsx**, **Stage3.jsx**, and **ChatInterface.jsx** — replacing the bare ReactMarkdown component throughout.

---

## 5. Value Proposition Map

| Metric | Single LLM | LLM Council | Improvement |
|--------|-----------|-------------|-------------|
| **Accuracy** | ~85% | ~95% | +12% |
| **Hallucination Risk** | Medium-High | Low | -60% |
| **Evidence-Backed Claims** | 0% | ~80% | +∞ |
| **Manual Review Time** | 15 min/query | 0 min | -100% |
| **Model Comparison Time** | 30 min/query | Automatic | -100% |
| **Confidence Level** | Uncertain | Peer-validated + grounded | High |

### Key Differentiators

| Capability | Description |
|-----------|-------------|
| **Consensus-Driven** | 4 models must agree through blind peer review |
| **Citation-Grounded** | Real-time evidence from FDA, ClinicalTrials, PubMed |
| **Pharma Metrics** | Verbalized Sampling with Correctness/Precision/Recall |
| **Scientific Output** | SMILES structures, LaTeX equations, GFM tables |
| **Self-Healing** | Circuit breakers + fallback chains + quorum enforcement |
| **Memory System** | 3-tier learn/unlearn with human-in-the-loop |
| **Enterprise Security** | All traffic through Bayer myGenAssist gateway |

---

## 6. Component Details

### Backend Components

| Component | File | Purpose |
|-----------|------|---------|
| **API Layer** | ackend/main.py | FastAPI endpoints, CORS, SSE streaming, session management |
| **Council Orchestrator** | ackend/council.py | 3-stage pipeline, Verbalized Sampling, RUBRIC+CLAIMS+RANKING, chairman prompt with 7+ guidelines |
| **Evidence Skills** | ackend/skills.py | OpenFDA, ClinicalTrials.gov, PubMed retrieval, deduplication, citation formatting |
| **LLM Client** | ackend/openrouter.py | Async httpx calls to Bayer myGenAssist API, Gemini multi-modal support (text + image), multi-part response assembly |
| **Grounding** | ackend/grounding.py | 5-rubric hybrid Verbalized + Synthetic grounding score |
| **Resilience** | ackend/resilience.py | Kill switch, circuit breaker, exponential backoff retry, fallback chains, quorum |
| **Memory Manager** | ackend/memory.py | Semantic, Episodic, Procedural tiers + MemoryManager facade |
| **Memory Storage** | ackend/memory_store.py | Cloud-agnostic storage abstraction (JSON, Redis, DynamoDB, CosmosDB) |
| **Orchestrator** | ackend/orchestrator.py | 4 async stage-gate agents (pre-S1, post-S2, post-S3, user gate) |
| **Token Tracking** | ackend/token_tracking.py | Per-model cost tracking, gateway vs direct pricing, SessionCostTracker |
| **Storage** | ackend/storage.py | JSON-based conversation persistence with metadata |
| **Config** | ackend/config.py | Model definitions, API settings, base URLs |

### Frontend Components

| Component | File | Purpose |
|-----------|------|---------|
| **App Shell** | App.jsx | Main state, SSE handler, evidence_complete event, layout |
| **SciMarkdown** | SciMarkdown.jsx | Shared scientific renderer: 2D/3D SMILES (smiles-drawer + 3Dmol.js), KaTeX math, GFM tables, figures with broken-image molecule fallback |
| **ChatInterface** | ChatInterface.jsx | Message display, input, file attachments |
| **Stage 1** | Stage1.jsx | Individual model responses with SciMarkdown |
| **Stage 2** | Stage2.jsx | Peer ranking matrix, Verbalized Sampling metrics |
| **Stage 3** | Stage3.jsx | Chairman synthesis, citation links, evidence panel |
| **GroundingScore** | GroundingScore.jsx | Circular SVG gauge + expandable criteria bars |
| **TokenBurndown** | TokenBurndown.jsx | Cost/token dashboard, gateway savings display |
| **PromptAtlas** | PromptAtlas3D.jsx | CSS decision tree flow visualization (no Three.js) |
| **MemoryPanel** | MemoryPanel.jsx | 3-tier memory browser, learn/unlearn/delete |
| **LearnUnlearn** | LearnUnlearn.jsx | Inline bar — auto-learned (green) vs pending (amber) |
| **KillSwitch** | KillSwitch.jsx | Emergency stop (session + global halt + release) |
| **EnhancePrompt** | EnhancePrompt.jsx | Prompt improvement UI |
| **Settings** | Settings.jsx | Model configuration per conversation |
| **Sidebar** | Sidebar.jsx | Conversation list, navigation, create/delete |

---

## 7. Technology Stack

### Frontend

| Technology | Purpose |
|-----------|---------|
| React 19.x | Component library |
| Vite 7.x | Build tool, HMR dev server, proxy |
| react-markdown 10.x | Base markdown rendering |
| remark-gfm | GFM tables, task lists, autolinks |
| remark-math | LaTeX math delimiter detection |
| rehype-raw | HTML passthrough (sub/sup/figure) |
| rehype-katex + katex | Math equation rendering |
| smiles-drawer | 2D molecular structure SVGs |
| 3Dmol.js (3dmol) | Interactive 3D molecular viewer (WebGL) |
| CSS (scoped) | Per-component styling, dark theme |

### Backend

| Technology | Purpose |
|-----------|---------|
| Python 3.10+ | Runtime |
| FastAPI 0.115+ | Async API framework |
| Uvicorn 0.32+ | ASGI server |
| httpx 0.27+ | Async HTTP client for LLM + evidence APIs |
| Pydantic 2.x | Request/response validation |
| python-dotenv | Environment configuration |

### Infrastructure

| Technology | Purpose |
|-----------|---------|
| Bayer myGenAssist | Enterprise LLM gateway (~40% cost savings) |
| JSON file storage | Default persistence (pluggable) |
| Redis / DynamoDB / CosmosDB | Production storage backends |
| Server-Sent Events | Real-time streaming |

### LLM Models (via myGenAssist)

| Model | Provider | Strengths |
|-------|----------|-----------|
| Claude Opus 4.5 | Anthropic | Strongest reasoning, default chairman |
| Gemini 2.5 Pro | Google | 1M context, strong analysis |
| GPT-5 Mini | OpenAI | Balanced speed/quality |
| Grok 3 | xAI | 1M context, strong reasoning |
| Gemini 2.5 Flash | Google | Fast fallback option |

---

## 8. Self-Healing & Resilience

### Resilience Points

```
  USER ──── KILL SWITCH (session or global halt) ─────────────────────┐
                                                                       │
  API Request                                                          │
  ┌─────────────────────────────────────────────────────┐              │
  │  Global Halt Check → BLOCKED if halted → Error 503  │              │
  │  Session Registration → Kill switch monitors this    │              │
  └──────────────────────────┬──────────────────────────┘              │
                             │                                          │
  ╔══════════════════════════╧══════════════════════════╗               │
  ║  STAGE 1: For each model:                           ║               │
  ║    ① Circuit Breaker check — SKIP if OPEN           ║               │
  ║    ② Retry with exponential backoff (1.5s→3s→6s)    ║  ◄── KILL    │
  ║    ③ Record success/failure in circuit breaker       ║               │
  ║    ④ If failed → resolve FALLBACK from chain         ║               │
  ║    ⑤ QUORUM CHECK: need ≥ 2 successful responses    ║               │
  ╚══════════════════════════╤══════════════════════════╝               │
                             │                                          │
  ╔══════════════════════════╧══════════════════════════╗               │
  ║  STAGE 2: Same per-model resilience                 ║               │
  ║    Accept partial rankings if quorum met (≥ 2)      ║  ◄── KILL    │
  ╚══════════════════════════╤══════════════════════════╝               │
                             │                                          │
  ╔══════════════════════════╧══════════════════════════╗               │
  ║  STAGE 3: Chairman with retry+backoff               ║               │
  ║    If failed → fallback chairman chain              ║  ◄── KILL    │
  ║    If ALL fail → EMERGENCY: use top Stage 1 response║               │
  ╚═════════════════════════════════════════════════════╝               │
```

### Circuit Breaker States

```
  CLOSED (normal) ──failure_count ≥ threshold──► OPEN (disabled)
       ▲                                              │
       │ success during half-open              recovery timeout
       │                                              │
       └──────────── HALF_OPEN (tentative) ◄──────────┘
```

### Fallback Chains

| Primary | Fallback 1 | Fallback 2 | Fallback 3 |
|---------|-----------|-----------|-----------|
| Claude Opus 4.5 | Gemini 2.5 Pro | GPT-5 Mini | Grok 3 |
| Gemini 2.5 Pro | Claude Opus 4.5 | GPT-5 Mini | Grok 3 |
| GPT-5 Mini | Gemini 2.5 Flash | Gemini 2.5 Pro | Claude Opus 4.5 |
| Grok 3 | Gemini 2.5 Pro | Claude Opus 4.5 | GPT-5 Mini |

### Kill Switch API

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/kill-switch/session | POST | Kill specific session |
| /api/kill-switch/halt | POST | Emergency global halt |
| /api/kill-switch/release | POST | Release global halt |
| /api/kill-switch/status | GET | Current kill switch state |

---

## 9. Grounding Score & Verbalized Sampling

### Verbalized Sampling Metrics

Used in all 3 stages with pharma-grade binary classification:

| Metric | Formula | Purpose |
|--------|---------|---------|
| **Correctness** | TP / (TP + 2×FN + FP) | Penalizes missed critical facts (2× weight on FN) |
| **Precision** | TP / (TP + FP) | Accuracy of stated claims |
| **Recall** | TP / (TP + FN) | Completeness of coverage |

### 5-Rubric Grounding Criteria

| # | Criterion | Weight | Description |
|---|-----------|--------|-------------|
| 1 | **Relevancy** | 25% | How directly the response addresses the query |
| 2 | **Faithfulness** | 25% | Factual accuracy, absence of hallucination |
| 3 | **Context Recall** | 15% | Completeness of information retrieval |
| 4 | **Output Quality** | 20% | Structural clarity, reasoning depth |
| 5 | **Consensus** | 15% | Agreement among peer reviewers on ranking |

### Hybrid Score Computation

```
  For each response r ranked at position p out of N:
    base_score(r)      = (N - p) / (N - 1)
    consensus_score(r) = 1 - (σ_rank(r) / N)
    grounding_score(r) = Σ (base_score × criterion_weight) + consensus_bonus

  Overall = mean(grounding_score for all responses)
```

### Visual Representation

- **Outer ring**: Animated SVG progress arc (green ≥80%, amber ≥60%, red <60%)
- **Centre**: Percentage + tier label ("High / Moderate / Low Confidence")
- **Detail panel**: Per-criteria horizontal bars + per-model breakdown

---

## 10. Cost & Token Tracking

### Pricing Model

| Model | Direct ($/1M in/out) | Gateway ($/1M in/out) | Savings |
|-------|---------------------|----------------------|---------|
| Claude Opus 4.5 |  /  |  /  | ~40% |
| Gemini 2.5 Pro | .25 /  | .75 /  | ~40% |
| GPT-5 Mini | .50 /  | .90 / .60 | ~40% |
| Grok 3 |  /  | .80 /  | ~40% |
| Gemini 2.5 Flash | .15 / .50 | .09 / .10 | ~40% |

### Data Flow

```
  Stage 1 → record(model, usage) × N models
  Stage 2 → record(model, usage) × N models
  Stage 3 → record(chairman, usage) × 1
                     │
                     ▼
         SessionCostTracker.compute_summary()
                     │
            ┌────────┴────────┐
            ▼                 ▼
   SSE: cost_summary    TokenBurndown component
      { totals,         ┌─────────────────────┐
        per_stage,      │ Total: 12,340 tokens │
        per_model }     │ Gateway:     .0142 │
                        │ Saved:       .0095 │
                        └─────────────────────┘
```

---

## 11. Memory Management Pipeline

### Three-Tier Architecture

| Tier | Purpose | Learn Trigger |
|------|---------|---------------|
| **Semantic** | Domain knowledge, facts, topics | Grounding ≥ 0.5 |
| **Episodic** | Full deliberation records with rankings | Always stored |
| **Procedural** | Workflow patterns, step sequences | "How-to" + Grounding ≥ 0.6 |

### Stage-Gate Agents

| Agent | Trigger | Action |
|-------|---------|--------|
| **PRE_STAGE1** | Before Stage 1 | Recall memories, augment query |
| **POST_STAGE2** | After Stage 2 | Compare grounding to historical mean, anomaly detect |
| **POST_STAGE3** | After Stage 3 | Auto-learn (≥0.75) or mark pending |
| **USER_GATE** | User action | Apply learn/unlearn decision |

### Learn / Unlearn Decision Tree

```
  Grounding Score
       │
  ┌────┼────────────┐
  │    │             │
  ≥0.75  0.50-0.74  <0.50
  │    │             │
  Auto  Pending     Episodic
  Learn (ask user)  Only
```

### Cloud-Agnostic Storage

| Backend | Config Value | Use Case |
|---------|-------------|----------|
| Local JSON | MEMORY_BACKEND=local | Development |
| Redis | MEMORY_BACKEND=redis | Multi-instance |
| DynamoDB | MEMORY_BACKEND=dynamodb | AWS serverless |
| Cosmos DB | MEMORY_BACKEND=cosmosdb | Azure global |

### Memory API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/memory/stats | Tier statistics |
| GET | /api/memory/{type} | List memories |
| POST | /api/memory/decision | Learn/unlearn |
| GET | /api/memory/search/{type}?q=... | Full-text search |
| DELETE | /api/memory/{type}/{id} | Permanent delete |

---

## 12. Production Deployment

### Quick Start

```bash
# Terminal 1 — Backend
cd LLMCouncilMGA
.\myenv\Scripts\Activate.ps1   # Windows
# source myenv/bin/activate    # Linux/macOS
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2 — Frontend
cd LLMCouncilMGA/frontend
npm run dev

# Open http://localhost:5173
```

### Production Build

```bash
# Build frontend
cd frontend && npm run build   # → frontend/dist/

# Run backend with multiple workers
uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 4
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| MGA_API_KEY | Yes | — | Bayer myGenAssist API key |
| MEMORY_BACKEND | No | local | Storage backend |
| REDIS_URL | If Redis | — | Redis connection URL |

### Deployment Options

See [deploy/DEPLOY.md](deploy/DEPLOY.md) for:
- **AWS** — ECS/Fargate + S3 + DynamoDB
- **Azure** — Container Apps + Blob + Cosmos DB
- **GCP** — Cloud Run + GCS + Firestore
- **Kubernetes** — Helm chart + HPA

---

*LLM Council MGA v2.0 — Ideated by Anna Bredlich · Master mind by Vinod Das*
