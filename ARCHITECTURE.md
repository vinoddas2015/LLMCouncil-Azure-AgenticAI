# LLM Council MGA — System Architecture

> **Version 3.1** | Bayer Pharmaceutical Division — myGenAssist  
> Last updated: February 15, 2026

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Flow — 3-Stage Pipeline](#2-data-flow--3-stage-pipeline)
3. [Evidence Skills Pipeline](#3-evidence-skills-pipeline)
4. [Scientific Markdown Rendering](#4-scientific-markdown-rendering)
5. [Value Proposition Map](#5-value-proposition-map)
6. [Component Details](#6-component-details) *(incl. Accessibility & WCAG 3.0)*
7. [Technology Stack](#7-technology-stack)
8. [Self-Healing & Resilience](#8-self-healing--resilience)
9. [Grounding Score & Verbalized Sampling](#9-grounding-score--verbalized-sampling)
10. [Cost & Token Tracking](#10-cost--token-tracking)
11. [Memory Management Pipeline](#11-memory-management-pipeline)
12. [Security & Privacy](#12-security--privacy)
13. [Infographics Pipeline](#13-infographics-pipeline)
14. [Prompt Suitability Guard](#14-prompt-suitability-guard)
15. [Production Deployment](#15-production-deployment)

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
  │  └──────────┘  └──────────┘  └──┬───────┘  └──────────┘  └──────────────────┘  │
  │                                  │                                               │
  │                           ┌──────▼──────────┐                                    │
  │                           │ InfographicPanel │  Visual summary: metrics,          │
  │                           │ (collapsible)    │  comparison, steps, highlights     │
  │                           └─────────────────┘                                    │
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
  │  │       │  │15 APIs  │  │Retry+    │  │  Agents    │ │                 │    │
  │  │Verbal.│  │7 core + │  │Fallback  │  │            │ │ Gateway vs      │    │
  │  │Samplng│  │8 web    │  │Quorum    │  │            │ │ Direct Pricing  │    │
  │  └───┬───┘  └────┬────┘  └──────────┘  └────────────┘ └─────────────────┘    │
  │      │           │                                                              │
  │  ┌───▼───────────▼──────────────────────────────────────────┐                   │
  │  │  openrouter.py — Async httpx Client → myGenAssist API     │                   │
  │  │  https://chat.int.bayer.com/api/v2/chat/completions       │                   │
  │  │  + PII Redaction (security.py) before external dispatch   │                   │
  │  └──────────────────────────────────────────────────────────┘                   │
  │                                                                                  │
  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐               │
  │  │  Storage (JSON)  │  │  Memory 3-Tier   │  │  Grounding Score │               │
  │  │  Conversations   │  │  Semantic/Epi/   │  │  Hybrid Verbal.  │               │
  │  │  + Encryption    │  │  Procedural      │  │  + Synthetic     │               │
  │  └──────────────────┘  └──────────────────┘  └──────────────────┘               │
  │                                                                                  │
  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐               │
  │  │  Security        │  │  Prompt Guard    │  │  Infographics    │               │
  │  │  Fernet encrypt  │  │  Pre-stage gate  │  │  JSON extraction │               │
  │  │  PII redaction   │  │  6 categories    │  │  + auto-extract  │               │
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
  │  PRE-GATE: Prompt Suitability Guard                    │
  │  • Regex checks: harmful, illegal, PII, injection      │
  │  • On-topic / off-topic keyword banks                   │
  │  • Ambiguous → LLM relevance check (Gemini Flash)       │
  │  • Blocked → SSE: prompt_rejected (conversation sealed) │
  └─────────────────────────┬───────────────────────────────┘
                          │ (ALLOWED)
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
  ║  • [FDA-L1], [CT-2], [PM-3], [AX-1], [PAT-1],           ║
  ║    [WIKI-1], [ORC-1] tags → clickable links              ║
  ║  • Rich output: tables, SMILES blocks, LaTeX math        ║
  ║  • 10-guideline prompt framework                         ║
  ║  • Infographic JSON block for visual summary             ║
  ║                                                           ║
  ║  → SSE: stage3_start → stage3_complete                    ║
  ╚═══════════════════════╤═══════════════════════════════════╝
                          │
  ┌───────────────────────▼───────────────────────────────┐
  │  POST-STAGE 3: Infographic Extraction                   │
  │  • Parse ```infographic JSON block from chairman         │
  │  • Fallback: auto-extract metrics, highlights, steps    │
  │  • Strip raw JSON from markdown response                │
  │  → SSE: infographic_complete                            │
  └───────────────────────┬───────────────────────────────┘
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
     session_start → prompt_rejected (if blocked, terminates)
     → memory_recall
     → stage1_start → stage1_response ×N → stage1_complete
     → stage2_start → stage2_ranking ×N → stage2_complete
     → evidence_complete (parallel with stage2)
     → memory_gate
     → stage3_start → stage3_complete
     → infographic_complete (if data extracted)
     → cost_summary → memory_learning → complete
```

---

## 3. Evidence Skills Pipeline

The skills module (backend/skills.py) retrieves real-time pharmaceutical evidence in **parallel with Stage 2**, injecting citations into the Stage 3 chairman prompt.

### Data Sources

**Core Skills (always active):**

| # | Skill | API | Data Retrieved | Timeout |
|---|-------|-----|----------------|---------|
| 1 | **OpenFDA** | api.fda.gov | Drug labels, adverse events, indications | 12s |
| 2 | **ClinicalTrials.gov** | clinicaltrials.gov/api/v2 | Active trials (Phase I–IV), conditions, interventions | 12s |
| 3 | **PubMed** | eutils.ncbi.nlm.nih.gov | Recent publications, abstracts, authors | 12s |
| 4 | **EMA** | ema.europa.eu | European Medicines Agency product info | 12s |
| 5 | **WHO ATC/DDD** | who.int | Drug classification, ATC codes | 12s |
| 6 | **UniProt** | uniprot.org | Protein / drug-target data (human) | 12s |
| 7 | **ChEMBL** | ebi.ac.uk/chembl | Compound bioactivity & clinical phase | 12s |

**Web Search Skills (active when web_search_enabled=true):**

| # | Skill | API | Data Retrieved | Timeout |
|---|-------|-----|----------------|---------|
| 8 | **Semantic Scholar** | api.semanticscholar.org | AI-curated scientific papers + abstracts | 15s |
| 9 | **CrossRef** | api.crossref.org | Journal article metadata & DOI links | 15s |
| 10 | **Europe PMC** | ebi.ac.uk/europepmc | Full-text open access literature | 15s |
| 11 | **DuckDuckGo Scientific** | duckduckgo.com | Web search filtered for .gov / .edu / journals | 15s |
| 12 | **arXiv** | export.arxiv.org | Scientific preprints (physics, biology, CS) | 15s |
| 13 | **Google Patents** | patents.google.com | Patent claims and invention descriptions | 15s |
| 14 | **Wikipedia** | en.wikipedia.org | Encyclopaedic context and background | 12s |
| 15 | **ORCID** | pub.orcid.org | Researcher profiles and publication records | 15s |

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
| [EMA-1] | European Medicines Agency | Links to EMA page |
| [WHO-1] | WHO ATC/DDD | Links to WHO classification |
| [UP-1] | UniProt | Links to protein entry |
| [CB-1] | ChEMBL | Links to compound page |
| [SS-1] | Semantic Scholar | Links to paper |
| [CR-1] | CrossRef / DOI | Links to journal article |
| [EPMC-1] | Europe PMC | Links to full-text |
| [WEB-1] | DuckDuckGo Scientific | Links to authoritative site |
| [AX-1] | arXiv | Links to preprint |
| [PAT-1] | Google Patents | Links to patent |
| [WIKI-1] | Wikipedia | Links to article |
| [ORC-1] | ORCID | Links to researcher profile |

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

## 4.5 Agent Team — Post-Pipeline Intelligence

After the 3-stage council pipeline completes, a team of **6 specialised agents** analyses the results in parallel and produces structured signals for the **Prompt Atlas Intelligence Dashboard**.

### Agent Roster

| Agent | Icon | Focus Area |
|-------|------|-----------|
| **Research Analyst** | 🔬 | Topic coverage, data density, evidence breadth, key findings |
| **Fact Checker** | 🛡️ | Grounding validation, hallucination detection, claim analysis (TP/FP/FN) |
| **Risk Assessor** | ⚠️ | Safety signals, regulatory flags, compliance gaps (pharmaceutical focus) |
| **Pattern Scout** | 🔍 | Consensus detection, recurring themes, rubric trends, emerging signals |
| **Insight Synthesizer** | 💡 | Cross-model analysis, novel connections, evidence gap detection |
| **Quality Auditor** | 📊 | Rubric scores, response completeness, cost efficiency, actionability |

### Signal Schema

Each agent returns a structured result:

```json
{
  "agent_id": "research_analyst",
  "role": "Research Analyst",
  "icon": "🔬",
  "summary": "Strong topic coverage across 3 domains",
  "confidence": 0.91,
  "signals": [
    {
      "kind": "finding",
      "severity": "success|info|warning|critical",
      "title": "High data density",
      "detail": "All 4 models addressed the core therapeutic question",
      "evidence": "optional supporting reference"
    }
  ],
  "metadata": {},
  "timestamp": "ISO-8601"
}
```

### SSE Integration

The agent team executes after `cost_summary` in the SSE streaming pipeline:

```
session_start → memory_recall → stage1 → evidence → stage2 → memory_gate
  → stage3 → infographic → cost_summary → ✨ agent_team_complete ✨
  → memory_learning → complete
```

The `agent_team_complete` event carries the combined result of all 6 agents, rendered by the Prompt Atlas dashboard.

### Architecture Principles

- **Pure async, stateless** — Each agent is an `async` function; no side effects
- **Parallel execution** — All 6 agents run concurrently via `asyncio.gather`
- **Non-fatal** — Agent failures are caught and logged; the pipeline continues
- **Structured output** — Every signal has severity, kind, title, detail — no free-form text
- **Scalable** — Designed for horizontal scaling (serverless-compatible)

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
| **Citation-Grounded** | Real-time evidence from 15 APIs (FDA, ClinicalTrials, PubMed, arXiv, Patents, Wikipedia, ORCID, and more) |
| **Infographics** | Auto-generated visual summaries: metrics, comparisons, process steps, highlights |
| **Pharma Metrics** | Verbalized Sampling with Correctness/Precision/Recall |
| **Scientific Output** | SMILES structures, LaTeX equations, GFM tables |
| **Self-Healing** | Circuit breakers + fallback chains + quorum enforcement |
| **Memory System** | 3-tier learn/unlearn with human-in-the-loop |
| **Security** | Encryption at rest, PII redaction, prompt guard, TLS support |
| **Enterprise Security** | All traffic through Bayer myGenAssist gateway |

---

## 6. Component Details

### Backend Components

| Component | File | Purpose |
|-----------|------|---------|
| **API Layer** | backend/main.py | FastAPI endpoints, CORS, SSE streaming, session management, prompt guard gate |
| **Council Orchestrator** | backend/council.py | 3-stage pipeline, Verbalized Sampling, RUBRIC+CLAIMS+RANKING, chairman prompt with 10 guidelines (incl. infographic directive) |
| **Evidence Skills** | backend/skills.py | 15 evidence APIs (7 core + 8 web-search), deduplication, citation formatting |
| **LLM Client** | backend/openrouter.py | Async httpx calls to Bayer myGenAssist API, Gemini multi-modal support (text + image), PII redaction before dispatch |
| **Grounding** | backend/grounding.py | 5-rubric hybrid Verbalized + Synthetic grounding score |
| **Resilience** | backend/resilience.py | Kill switch, circuit breaker, exponential backoff retry, fallback chains, quorum |
| **Memory Manager** | backend/memory.py | Semantic, Episodic, Procedural tiers + MemoryManager facade |
| **Memory Storage** | backend/memory_store.py | Cloud-agnostic storage abstraction (JSON, Redis, DynamoDB, CosmosDB) |
| **Orchestrator** | backend/orchestrator.py | 4 async stage-gate agents (pre-S1, post-S2, post-S3, user gate) |
| **Token Tracking** | backend/token_tracking.py | Per-model cost tracking, gateway vs direct pricing, SessionCostTracker |
| **Storage** | backend/storage.py | JSON-based conversation persistence with optional Fernet encryption at rest |
| **Security** | backend/security.py | Fernet encryption at rest (AES-128-CBC), PII redaction (9 pattern types), security status reporting |
| **Prompt Guard** | backend/prompt_guard.py | Pre-stage suitability gate: 6 rejection categories (off-topic, harmful, illegal, PII, injection, trivial) + LLM fallback |
| **Infographics** | backend/infographics.py | Infographic JSON extraction from chairman responses, auto-extraction fallback, validation & cleaning |
| **Agent Team** | backend/agents.py | 6 specialised post-pipeline agents: Research Analyst, Fact Checker, Risk Assessor, Pattern Scout, Insight Synthesizer, Quality Auditor — run in parallel via `asyncio.gather`, emit structured signals for the Prompt Atlas dashboard |
| **Config** | backend/config.py | Model definitions, API settings, base URLs |

### Frontend Components

| Component | File | Purpose |
|-----------|------|---------|
| **App Shell** | App.jsx | Main state, SSE handler (incl. infographic_complete, prompt_rejected events), layout |
| **SciMarkdown** | SciMarkdown.jsx | Shared scientific renderer: 2D/3D SMILES (smiles-drawer + 3Dmol.js), KaTeX math, GFM tables, figures with broken-image molecule fallback |
| **ChatInterface** | ChatInterface.jsx | Message display, input, file attachments, blocked conversation UX |
| **Stage 1** | Stage1.jsx | Individual model responses with SciMarkdown |
| **Stage 2** | Stage2.jsx | Peer ranking matrix, Verbalized Sampling metrics |
| **Stage 3** | Stage3.jsx | Chairman synthesis, citation links (15 tag types), evidence panel |
| **InfographicPanel** | InfographicPanel.jsx | Visual summary: key metrics grid, comparison table, process steps flow, highlight cards (success/warning/info/danger) |
| **GroundingScore** | GroundingScore.jsx | Circular SVG gauge + expandable criteria bars |
| **TokenBurndown** | TokenBurndown.jsx | Cost/token dashboard, gateway savings display |
| **PromptAtlas** | PromptAtlas3D.jsx | Intelligence Dashboard: 6-agent signals + CSS decision tree — tabbed view with Agent Team cards (signals/patterns/risks/insights), WCAG 3.0 ARIA (complementary landmark, tablist, keyboard-operable cards) |
| **MemoryPanel** | MemoryPanel.jsx | 3-tier memory browser, learn/unlearn/delete |
| **LearnUnlearn** | LearnUnlearn.jsx | Inline bar — auto-learned (green) vs pending (amber) |
| **KillSwitch** | KillSwitch.jsx | Emergency stop (session + global halt + release) |
| **EnhancePrompt** | EnhancePrompt.jsx | Prompt improvement UI |
| **Settings** | Settings.jsx | Model configuration per conversation |
| **Sidebar** | Sidebar.jsx | Conversation list, navigation, create/delete |
| **ThemeToggle** | ThemeToggle.jsx | Day/Night mode switch (WCAG 3.0 `role="switch"`, keyboard-operable) |
| **ThemeContext** | ThemeContext.jsx | Theme provider — `localStorage` persistence, `prefers-color-scheme` OS detection |

### Accessibility (WCAG 3.0 Silver)

The frontend implements WCAG 3.0 draft guidelines using the **APCA** (Advanced Perceptual Contrast Algorithm) contrast methodology:

| APCA Lc Threshold | Use Case | Example |
|---|---|---|
| ≥ 90 | Body text | `--text-primary` on `--bg-primary` |
| ≥ 75 | Large text / headlines | `--text-secondary` on `--bg-primary` |
| ≥ 60 | Sub-text, placeholders | `--text-muted` on `--bg-primary` |
| ≥ 45 | Non-text UI, icons, focus rings | `--accent-primary`, `--border-focus` |
| ≥ 30 | Decorative / disabled | Decorative borders |

**Key accessibility features:**
- **Dual Theme** — Full dark (Night) and light (Day) palettes via CSS custom properties on `[data-theme]`
- **ARIA Landmarks** — `<nav>` (sidebar), `<main>` (chat), `<aside>` (atlas), `role="region"` (emergency controls)
- **Dialog Semantics** — `role="dialog"`, `aria-modal="true"`, `aria-labelledby` on Settings
- **Listbox Pattern** — `role="listbox"`/`role="option"` with `aria-selected` on conversation list
- **Menu Pattern** — `role="menu"`/`role="menuitem"` with `aria-haspopup`/`aria-expanded` on context menus
- **Skip Navigation** — Skip-to-content link targeting `#main-content`
- **Keyboard Operability** — All conversation items, toggles, and menus operable via Enter/Space
- **Focus Indicators** — 3px solid `--border-focus` ring via `:focus-visible`
- **Min Target Size** — 24 × 24 CSS px minimum (WCAG 2.5.8)
- **Reduced Motion** — `prefers-reduced-motion: reduce` disables all animations
- **High Contrast** — `forced-colors: active` for Windows High Contrast mode
- **CVD-Safe** — Palette distinguishable under protanopia, deuteranopia, tritanopia

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
| CSS (scoped) | Per-component styling, WCAG 3.0 dual-theme (Day/Night) |
| ThemeContext | React context + localStorage + prefers-color-scheme |
| Vitest + Testing Library | 89 accessibility tests (APCA contrast, ARIA, landmarks) |

### Backend

| Technology | Purpose |
|-----------|---------|
| Python 3.10+ | Runtime |
| FastAPI 0.115+ | Async API framework |
| Uvicorn 0.32+ | ASGI server |
| httpx 0.27+ | Async HTTP client for LLM + evidence APIs |
| Pydantic 2.x | Request/response validation |
| python-dotenv | Environment configuration |
| cryptography 43+ | Fernet encryption at rest (AES-128-CBC) |

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

## 12. Security & Privacy

### Architecture

```
  User Prompt
       │
       ▼
  ┌──────────────────────────┐
  │ Prompt Guard (pre-gate)  │ ← Blocks before any LLM call
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │ PII Redaction (outbound) │ ← Scrubs before external API
  └────────────┬─────────────┘
               │
               ▼
  ┌──────────────────────────┐
  │ Encryption at Rest       │ ← Fernet AES-128-CBC
  │ (conversation JSON)      │
  └──────────────────────────┘
```

### Encryption at Rest

| Feature | Detail |
|---------|--------|
| Algorithm | Fernet (AES-128-CBC + HMAC-SHA256) |
| Library | `cryptography` 43+ |
| Config | `ENCRYPTION_KEY` env var (base64-encoded 32-byte key) |
| Migration | Graceful — unencrypted legacy files transparently read |

### PII Redaction

Runs **before** every outbound LLM API call (in `openrouter.py`):

| Pattern | Replacement |
|---------|-------------|
| Email addresses | [EMAIL-REDACTED] |
| Phone numbers | [PHONE-REDACTED] |
| SSN (US) | [SSN-REDACTED] |
| Medical Record Number | [MRN-REDACTED] |
| Date of Birth | [DOB-REDACTED] |
| Patient/subject names | [PATIENT-ID-REDACTED] |
| Credit card numbers | [CC-REDACTED] |
| IP addresses (v4) | [IP-REDACTED] |
| Passport numbers | [PASSPORT-REDACTED] |

---

## 13. Infographics Pipeline

### Architecture

```
  Stage 3 Chairman Response
       │
       ▼
  ┌───────────────────────────────────┐
  │  1. Parse ```infographic block   │
  │     explicit JSON from chairman  │
  └────────────────┬──────────────────┘
                 │
         found?  ├── YES → validate_and_clean()
                 │
                 └── NO → auto_extract()
                          │
                          ├─ _extract_metrics() → IC50, Phase, AUC, ...
                          ├─ _extract_highlights() → bold text, key sentences
                          └─ _extract_steps() → numbered lists, headings
                                    │
                                    ▼
                          strip_infographic_block()
                          (remove raw JSON from markdown)
                                    │
                                    ▼
                          SSE: infographic_complete
                          SSE: stage3_complete (cleaned)
```

### Infographic JSON Schema

```json
{
  "title": "Short summary title",
  "type": "summary",
  "key_metrics": [
    { "label": "IC50", "value": "5.2 nM", "icon": "💊" }
  ],
  "comparison": {
    "headers": ["Category", "Drug A", "Drug B"],
    "rows": [["Efficacy", "High", "Moderate"]]
  },
  "process_steps": [
    { "step": 1, "title": "Absorption", "description": "Oral bioavailability ~80%" }
  ],
  "highlights": [
    { "text": "FDA approved in 2024", "type": "success" }
  ]
}
```

### Frontend Rendering (InfographicPanel.jsx)

| Section | Visual |
|---------|--------|
| Key Metrics | Grid of icon + value + label cards |
| Comparison | Styled table with hover highlights |
| Process Steps | Horizontal flow with numbered circles and arrow connectors |
| Highlights | Color-coded cards: green (success), amber (warning), blue (info), red (danger) |

### Validation Limits

| Field | Max Items |
|-------|-----------|
| key_metrics | 6 |
| comparison rows | 8 |
| process_steps | 6 |
| highlights | 4 |

---

## 14. Prompt Suitability Guard

### Rejection Categories

| Category | Trigger |
|----------|---------|
| **TRIVIAL** | Empty, too short (<5 chars), gibberish (>65% non-alpha) |
| **HARMFUL_CONTENT** | Violence, hate speech, discrimination, explicit content |
| **ILLEGAL_ACTIVITY** | Illicit drug synthesis, unregulated substance acquisition |
| **PERSONAL_DATA** | SSN, patient names + medical context, MRN, DOB |
| **PROMPT_INJECTION** | Jailbreak patterns, system prompt exfiltration, instruction override |
| **OFF_TOPIC** | Sports, entertainment, cooking, travel, etc. (no pharma keywords) |

### Detection Pipeline

```
  Prompt → Trivial check → Harmful regex → Illegal regex
       → Injection regex → PII regex
       → On-topic keyword bank (200+ terms)
       → Off-topic keyword bank
       → Ambiguous? → LLM relevance check (Gemini 2.5 Flash, 12s timeout)
       → Verdict: ALLOWED or BLOCKED (category + polite message)
```

### Behaviour on Rejection

1. Conversation marked as `blocked: true` (all follow-ups rejected)
2. User message stored for audit trail
3. SSE event `prompt_rejected` with category and message
4. Frontend disables input, shows policy message
5. User must start a **new conversation**

---

## 15. Production Deployment

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
| ENCRYPTION_KEY | No | — | Fernet key for encryption at rest (base64-encoded 32-byte key) |
| PII_REDACTION | No | true | Enable PII scrubbing before external LLM calls |
| SSL_CERTFILE | No | — | TLS certificate file path (enables HTTPS) |
| SSL_KEYFILE | No | — | TLS private key file path |
| MEMORY_BACKEND | No | local | Storage backend |
| REDIS_URL | If Redis | — | Redis connection URL |

### Deployment Options

See [deploy/DEPLOY.md](deploy/DEPLOY.md) for:
- **AWS** — ECS/Fargate + S3 + DynamoDB
- **Azure** — Container Apps + Blob + Cosmos DB
- **GCP** — Cloud Run + GCS + Firestore
- **Kubernetes** — Helm chart + HPA

---

*LLM Council MGA v3.0 — Ideated by Anna Bredlich · Master mind by Vinod Das*
