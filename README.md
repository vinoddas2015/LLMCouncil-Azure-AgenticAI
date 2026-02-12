# LLM Council MGA

<p align="center">
  <img src="Logo_Bayer.jpg" alt="Bayer" width="120" />
</p>

<p align="center">
  <strong>Enterprise Multi-Model AI Orchestration Platform</strong><br />
  <em>Bayer Pharmaceutical Division — myGenAssist v2.0</em>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#api-reference">API</a> •
  <a href="#production-deployment">Production</a> •
  <a href="#testing">Testing</a>
</p>

---

## Overview

**LLM Council MGA** is an enterprise AI orchestration platform that consults a "council" of diverse Large Language Models to produce consensus-driven, high-confidence responses for pharmaceutical professionals. Every query passes through a **3-stage deliberation pipeline** — individual responses, anonymous peer review with **Verbalized Sampling** metrics, and chairman synthesis with **citation-grounded evidence** — producing answers that are more accurate, balanced, and verifiable than any single model alone.

The platform integrates real-time evidence retrieval from **15 parallel skills** — 7 core APIs (OpenFDA, ClinicalTrials.gov, PubMed, EMA, WHO ATC, UniProt, ChEMBL) plus 8 web-search skills (Semantic Scholar, CrossRef, Europe PMC, DuckDuckGo Science, arXiv, Google Patents, Wikipedia, ORCID) — renders **scientific markdown** (2D/3D SMILES molecular structures, LaTeX math, GFM tables), generates **visual infographic summaries** (metric cards, comparisons, process flows, highlight takeaways), supports **Gemini multi-modal output** (text + images), and includes a **prompt suitability guard**, built-in **self-healing resilience**, **grounding score evaluation**, **token/cost tracking**, and a **three-tier memory management system**.

---

## Features

### Core Council Pipeline

| Stage | What Happens |
|-------|-------------|
| **Stage 1 — First Opinions** | Query sent to all council models independently; responses rendered with SciMarkdown |
| **Stage 2 — Peer Review** | Each model anonymously ranks others using Verbalized Sampling (pharma-grade Correctness, Precision, Recall) |
| **Stage 3 — Chairman Synthesis** | Chairman compiles citation-grounded final response with [FDA-L1], [CT-2], [PM-3], [SS-1], [CR-1], [EPMC-1], [AX-1], [PAT-1], [WIKI-1], [ORC-1] references, plus an auto-generated visual infographic summary |

### Prompt Suitability Guard
- **Pre-Stage Gate** — Every prompt is evaluated before council stages fire, filtering trivial, harmful, illegal, PII, injection, and off-topic queries
- **6 Rejection Categories** — TRIVIAL, HARMFUL_CONTENT, ILLEGAL_ACTIVITY, PERSONAL_DATA, PROMPT_INJECTION, OFF_TOPIC
- **Conversation Lock** — Rejected conversations are permanently blocked; users must start a new conversation
- **Policy-Aligned Messages** — Polite rejection messages referencing Bayer's Responsible AI Policy

### Evidence & Citation System
- **15 Parallel Evidence Skills** — 7 core APIs always fire: OpenFDA (drug labels/adverse events), ClinicalTrials.gov (active trials), PubMed (publications), EMA (European Medicines Agency), WHO ATC (drug classifications), UniProt (protein data), ChEMBL (bioactivity data)
- **8 Web-Search Skills** (when Web Search enabled) — Semantic Scholar (academic papers, citation-weighted), CrossRef (DOI metadata), Europe PMC (open-access literature), DuckDuckGo Science (authoritative domain filter), arXiv (scientific preprints), Google Patents (patent search), Wikipedia (encyclopaedic context), ORCID (researcher profiles)
- **Citation-Grounded Output** — Chairman references evidence as clickable [FDA-L1], [CT-2], [PM-3], [SS-1], [CR-1], [EPMC-1], [WEB-1], [AX-1], [PAT-1], [WIKI-1], [ORC-1] tags linking to source URLs
- **Evidence Panel** — Collapsible sidebar showing all retrieved citations with source badges
- **Benchmark Timing** — Per-skill execution time reported with evidence results

### Infographics
- **Auto-Generated Visual Summaries** — Every chairman response includes an interactive infographic panel
- **Key Metric Cards** — IC<sub>50</sub>, Phase, Approval dates, Patient counts, p-values extracted automatically
- **Comparison Tables** — Side-by-side drug/treatment comparisons rendered as styled data tables
- **Process Flows** — Mechanism of action, clinical pathways, and synthesis pipelines as step diagrams
- **Highlight Cards** — Key takeaways classified as success (green), warning (amber), info (blue), or danger (red)
- **Collapsible Panel** — Click header to toggle; does not clutter the main response

### Scientific Markdown Rendering (SciMarkdown)
- **2D SMILES Structures** — Molecular diagrams rendered via smiles-drawer (use ``smiles code blocks)
- **3D Molecular Viewer** — Interactive WebGL 3D models via 3Dmol.js with ball-and-stick rendering, auto-spin, click-drag rotation, and scroll zoom. 3D coordinates fetched from PubChem REST API. Toggle 2D↔3D on any SMILES block.
- **Broken Molecule Image Fallback** — When LLMs output `![structure of caffeine](broken-url)`, the frontend detects the broken image, matches the molecule name against 20+ common pharmaceuticals, and renders an interactive SMILES structure instead
- **LaTeX Math** — Inline $...$ and block $$...$$ equations via KaTeX
- **GFM Tables** — Striped, scrollable tables with sticky headers
- **Rich HTML** — Subscript/superscript (<sub>/<sup>), figures with captions
- **Code Blocks** — Syntax-highlighted with copy button
- **Multi-Modal Output** — Gemini models can return inline images alongside text

### Verbalized Sampling Metrics
Pharma-grade evaluation in all 3 stages using binary classification metrics:
- **Correctness** = TP / (TP + 2×FN + FP) — penalizes missed critical facts
- **Precision** = TP / (TP + FP) — accuracy of stated claims  
- **Recall** = TP / (TP + FN) — completeness of coverage

### Enterprise Capabilities
- **Self-Healing Resilience** — Circuit breakers, exponential backoff retries, fallback chains, quorum enforcement, global kill switch
- **Grounding Score** — 5-rubric evaluation (Relevancy 25%, Faithfulness 25%, Output Quality 20%, Context Recall 15%, Consensus 15%) with hybrid Verbalized + Synthetic scoring
- **Token & Cost Burndown** — Real-time tracking of token usage, cost per model/stage, gateway vs direct pricing with ~40% savings display
- **Three-Tier Memory** — Semantic (domain knowledge), Episodic (deliberation history), Procedural (workflow patterns) with confidence-gated auto-learning
- **Decision Tree Visualization** — Interactive conversation flow (Root → Stage 1 → Stage 2 → Evidence → Stage 3) with click-to-expand nodes
- **Prompt Enhancement** — Automatic prompt improvement before council submission
- **File Attachments** — PDF, PPTX, XLSX, DOCX support (up to 10MB)
- **Conversation Management** — Full CRUD, export to markdown, multi-turn follow-ups
- **Cloud-Agnostic Storage** — Pluggable backend (Local JSON, Redis, DynamoDB, Cosmos DB)

### Models

| Model | Provider | Role |
|-------|----------|------|
| **Claude Opus 4.5** | Anthropic | Default Chairman — strongest reasoning |
| **Gemini 2.5 Pro** | Google | Council member — 1M context window |
| **GPT-5 Mini** | OpenAI | Council member — balanced performance |
| **Grok 3** | xAI | Council member — 1M context window |
| **Gemini 2.5 Flash** | Google | Fallback — fast and efficient |

*Models are configurable per-conversation via the Settings panel.*

---

## Architecture

```
┌──────────────┐     SSE Stream      ┌──────────────────────────────────────────┐
│              │◄────────────────────►│            FastAPI Backend               │
│   React 19   │     REST API         │                                          │
│  + Vite 7.x  │────────────────────►│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│              │                      │  │ Prompt   │  │ Evidence │  │ Memory │ │
│  SciMarkdown │                      │  │ Guard ──►│  │ Skills   │  │ 3-Tier │ │
│  + KaTeX     │                      │  │ Council  │  │(7+4 Web) │  │ System │ │
│              │                      │  │ 3-Stage  │  │          │  │        │ │
│  Port 5173   │                      │  └─────┬────┘  └────┬─────┘  └───┬────┘ │
└──────────────┘                      │        │            │            │       │
                                      │  ┌─────▼────────────▼────────────▼─────┐ │
                                      │  │         Orchestrator + Resilience    │ │
                                      │  │  Kill Switch │ Circuit Breakers     │ │
                                      │  └──────────────────┬──────────────────┘ │
                                      │                     │                    │
                                      │  ┌──────────────────▼──────────────────┐ │
                                      │  │      Bayer myGenAssist API          │ │
                                      │  │      chat.int.bayer.com             │ │
                                      │  └─────────────────────────────────────┘ │
                                      │                  Port 8001               │
                                      └──────────────────────────────────────────┘
```

**Full architecture document**: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Quick Start

### Prerequisites
- **Python** 3.10+ with pip
- **Node.js** 18+ with npm
- **Bayer myGenAssist API Key** (`mga-*`)

### 1. Clone & Configure

```bash
git clone <repo-url>
cd LLMCouncilMGA
cp .env.example .env
# Edit .env with your API key:
#   MGA_API_KEY=mga-your-key-here
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv myenv

# Activate (Windows PowerShell)
.\myenv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source myenv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### 4. Open Application

Navigate to **http://localhost:5173** — the Vite dev server proxies `/api/*` requests to the backend on port 8001.

---

## API Reference

### Conversations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/conversations` | List all conversations |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/{id}` | Get conversation detail |
| `PUT` | `/api/conversations/{id}` | Update conversation metadata |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |
| `POST` | `/api/conversations/{id}/stream` | Stream council deliberation (SSE) |

### Memory

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/memory/stats` | Tier statistics |
| `GET` | `/api/memory/{type}` | List memories by tier |
| `GET` | `/api/memory/{type}/{id}` | Get specific memory |
| `POST` | `/api/memory/decision` | Learn/unlearn decision |
| `GET` | `/api/memory/search/{type}?q=...` | Search within tier |
| `DELETE` | `/api/memory/{type}/{id}` | Delete memory entry |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Full system health + healing log |
| `GET` | `/api/health/circuits` | Per-model circuit breaker status |
| `POST` | `/api/health/circuits/reset` | Reset circuit breaker(s) |
| `POST` | `/api/kill-switch/session` | Kill specific session |
| `POST` | `/api/kill-switch/halt` | Emergency global halt |
| `POST` | `/api/kill-switch/release` | Release global halt |
| `GET` | `/api/kill-switch/status` | Kill switch state |
| `GET` | `/api/models` | Available model list |
| `POST` | `/api/enhance-prompt` | Enhance prompt before submission |

### SSE Event Types

Events emitted during `POST /api/conversations/{id}/stream`:

| Event | Stage | Payload Description |
|-------|-------|---------------------|
| `prompt_rejected` | Pre | Prompt blocked by guard — category + message |
| `session_start` | Pre | Session ID + metadata |
| `memory_recall` | Pre | Recalled memories + influence score |
| `stage1_start` | S1 | Stage 1 initiated |
| `stage1_response` | S1 | Individual model response |
| `stage1_complete` | S1 | All council members responded |
| `stage2_start` | S2 | Peer review initiated |
| `stage2_ranking` | S2 | Per-model ranking data |
| `stage2_complete` | S2 | Rankings + grounding score |
| `evidence_complete` | S2→S3 | Citations from 7 core + 8 web-search skills with timing |
| `infographic_complete` | Post-S3 | Structured infographic data (metrics, comparison, steps, highlights) |
| `memory_gate` | Post-S2 | Grounding vs historical evaluation |
| `stage3_start` | S3 | Chairman synthesis initiated |
| `stage3_complete` | S3 | Final citation-grounded response |
| `cost_summary` | Post-S3 | Token usage, gateway/direct costs, savings |
| `memory_learning` | Post-S3 | Learn/unlearn decision + tier IDs |
| `complete` | End | Full metadata + timing |

---

## Production Deployment

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MGA_API_KEY` | Yes | Bayer myGenAssist API key (`mga-*`) |
| `MEMORY_BACKEND` | No | Storage backend: `local` (default), `redis`, `dynamodb`, `cosmosdb` |
| `REDIS_URL` | If Redis | Redis connection URL |
| `AWS_REGION` | If DynamoDB | AWS region for DynamoDB |
| `COSMOS_CONNECTION_STRING` | If CosmosDB | Azure Cosmos DB connection string |

### Build for Production

```bash
# Build frontend static assets
cd frontend
npm run build
# Output: frontend/dist/

# Serve backend with production ASGI server
cd ..
uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 4
```

### Docker (Example)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
EXPOSE 8001
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
```

### Deployment Options

See [deploy/DEPLOY.md](deploy/DEPLOY.md) for detailed guides covering:
- **AWS** — ECS/Fargate + S3 + DynamoDB
- **Azure** — Container Apps + Blob Storage + Cosmos DB
- **GCP** — Cloud Run + GCS + Firestore
- **Kubernetes** — Helm chart with horizontal autoscaling

---

## Testing

```bash
# Activate virtual environment
.\myenv\Scripts\Activate.ps1

# Run full test suite (42 tests)
python -m pytest tests/test_memory_pipeline.py -v

# Run with coverage
python -m pytest tests/ -v --tb=short
```

Test coverage includes: storage CRUD, semantic/episodic/procedural memory operations, MemoryManager facade, orchestrator agents, end-to-end pipeline simulation, and backend swap verification.

---

## Project Structure

```
LLMCouncilMGA/
├── backend/                        # FastAPI backend
│   ├── main.py                     # App, routes, SSE streaming
│   ├── council.py                  # 3-stage council (Verbalized Sampling)
│   ├── prompt_guard.py              # Prompt suitability guard (6-category filter)
│   ├── skills.py                   # Evidence retrieval (15 skills: 7 core + 8 web)
│   ├── infographics.py             # Infographic extraction from chairman output
│   ├── grounding.py                # Hybrid grounding score computation
│   ├── openrouter.py               # Async LLM API client (httpx)
│   ├── resilience.py               # Kill switch, circuit breaker, retries
│   ├── memory.py                   # 3-tier memory manager
│   ├── memory_store.py             # Cloud-agnostic storage abstraction
│   ├── orchestrator.py             # Stage-gate orchestrator agents
│   ├── storage.py                  # Conversation persistence (JSON)
│   ├── token_tracking.py           # Token/cost burndown tracking
│   └── config.py                   # Model config & API settings
├── frontend/                       # React 19 + Vite 7
│   └── src/
│       ├── api.js                  # Backend API client
│       ├── App.jsx                 # Main app shell + SSE handler
│       └── components/
│           ├── ChatInterface.jsx   # Message display & input
│           ├── SciMarkdown.jsx     # 2D/3D SMILES, LaTeX/KaTeX, GFM renderer
│           ├── Stage1.jsx          # Individual model responses
│           ├── Stage2.jsx          # Peer ranking matrix
│           ├── Stage3.jsx          # Chairman + citation links
│           ├── InfographicPanel.jsx # Visual infographic summary
│           ├── GroundingScore.jsx  # Circular confidence gauge
│           ├── TokenBurndown.jsx   # Cost/token dashboard
│           ├── PromptAtlas3D.jsx   # Decision tree flow viz
│           ├── MemoryPanel.jsx     # Memory management panel
│           ├── LearnUnlearn.jsx    # Inline memory controls
│           ├── KillSwitch.jsx      # Emergency stop button
│           ├── EnhancePrompt.jsx   # Prompt enhancement UI
│           ├── Settings.jsx        # Model configuration
│           └── Sidebar.jsx         # Conversation list
├── tests/                          # Test suite
│   └── test_memory_pipeline.py     # 42 memory pipeline tests
├── deploy/                         # Deployment guides
│   └── DEPLOY.md                   # AWS / Azure / GCP / K8s
├── ARCHITECTURE.md                 # Full system architecture
├── CONTRIBUTING.md                 # Contribution guidelines
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Python project metadata
├── .env.example                    # Environment config template
└── start.sh                        # Quick-start script
```

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Backend** | Python, FastAPI, Uvicorn | 3.10+, 0.115+, 0.32+ |
| **Frontend** | React, Vite | 19.x, 7.x |
| **Scientific Rendering** | react-markdown, remark-gfm, rehype-raw, remark-math, rehype-katex, smiles-drawer, 3Dmol.js | Latest |
| **HTTP Client** | httpx (async) | 0.27+ |
| **Streaming** | Server-Sent Events (SSE) | — |
| **Evidence APIs** | OpenFDA, ClinicalTrials.gov, PubMed, arXiv, Google Patents, Wikipedia, ORCID | Public REST |
| **Storage** | JSON files (pluggable: Redis, DynamoDB, CosmosDB) | — |
| **Testing** | pytest, pytest-asyncio | 9.x, 1.x |
| **LLM Gateway** | Bayer myGenAssist | Enterprise |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, branch naming, and PR process.

---

<p align="center">
  <em>Ideated by Anna Bredlich · Master mind by Vinod Das</em><br />
  <strong>Science for a better life.</strong>
</p>
