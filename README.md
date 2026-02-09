# LLM Council MGA

<p align="center">
  <img src="Logo_Bayer.jpg" alt="Bayer" width="120" />
</p>

<p align="center">
  <strong>Enterprise Multi-Model AI Orchestration Platform</strong><br />
  <em>Bayer Pharmaceutical Division — myGenAssist</em>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#docker">Docker</a> •
  <a href="#api-reference">API</a> •
  <a href="#testing">Testing</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## Overview

**LLM Council MGA** is an enterprise AI orchestration platform that consults a "council" of diverse Large Language Models to produce consensus-driven, high-confidence responses. Instead of relying on a single model, every query passes through a **3-stage deliberation pipeline** — individual responses, anonymous peer review, and chairman synthesis — producing answers that are more accurate, balanced, and verifiable than any single model alone.

The platform includes built-in **self-healing resilience**, **grounding score evaluation**, **token/cost tracking**, and a **three-tier memory management system** with human-in-the-loop learn/unlearn controls.

---

## Features

### Core Council Pipeline
| Stage | What Happens |
|-------|-------------|
| **Stage 1 — First Opinions** | Query sent to all council models independently; responses displayed in tabs |
| **Stage 2 — Peer Review** | Each model anonymously ranks the others on accuracy & insight |
| **Stage 3 — Chairman Synthesis** | The designated chairman compiles a final consensus response |

### Enterprise Capabilities
- **Self-Healing Resilience** — Circuit breakers, automatic retries, health monitoring, global kill switch
- **Grounding Score** — 5-rubric evaluation (factual accuracy, completeness, consistency, specificity, relevance) with circular bubble UI
- **Token & Cost Burndown** — Real-time tracking of token usage, cost per model, and gateway savings
- **Three-Tier Memory** — Semantic (domain knowledge), Episodic (deliberation history), Procedural (workflow patterns) with confidence-gated auto-learning
- **Stage-Gate Orchestrator** — 4 agents (pre-stage1 recall, post-stage2 evaluation, post-stage3 learning, user gate) that manage the memory lifecycle
- **Human-in-the-Loop** — Users can learn/unlearn any memory at any stage; auto-learn threshold at 75% grounding
- **Prompt Enhancement** — Automatic prompt improvement before council submission
- **File Attachments** — PDF, PPTX, XLSX, DOCX support (up to 10MB)
- **Conversation Management** — Full CRUD, export to markdown, multi-turn follow-ups
- **Cloud-Agnostic** — Pluggable storage backend (Local JSON, Redis, DynamoDB, Cosmos DB)

### Models Supported
| Model | Description |
|-------|------------|
| Claude Opus 4.5 | Strongest reasoning & tool-use (default chairman) |
| Gemini 2.5 Pro | Google's best reasoning model, 1M context |
| GPT-5 Mini | Balanced OpenAI model |
| Grok 3 | Strong reasoning, 1M context window |
| Gemini 2.5 Flash | Fast and efficient for quick tasks |

*Models are configurable per-conversation via the Settings panel.*

---

## Architecture

```
┌──────────────┐     SSE Stream      ┌──────────────────────────────────────┐
│              │◄────────────────────►│          FastAPI Backend             │
│   React UI   │     REST API         │                                      │
│  (Vite 7.x)  │────────────────────►│  ┌──────────┐  ┌──────────────────┐ │
│              │                      │  │ Council   │  │ Memory Pipeline  │ │
│  Port 5173   │                      │  │ 3-Stage   │  │ Semantic/Epi/Proc│ │
│              │                      │  │ Pipeline  │  │                  │ │
└──────────────┘                      │  └─────┬────┘  └────────┬─────────┘ │
                                      │        │                │           │
                                      │  ┌─────▼────────────────▼─────────┐ │
                                      │  │          Orchestrator           │ │
                                      │  │  Pre-S1 │ Post-S2 │ Post-S3   │ │
                                      │  └─────────────────┬──────────────┘ │
                                      │                    │                │
                                      │  ┌─────────────────▼──────────────┐ │
                                      │  │   Bayer myGenAssist API        │ │
                                      │  │   chat.int.bayer.com           │ │
                                      │  └────────────────────────────────┘ │
                                      │                Port 8001            │
                                      └──────────────────────────────────────┘
```

For the full architecture document with diagrams, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Quick Start

### Prerequisites
- **Python** 3.10+
- **Node.js** 18+ and npm
- **Bayer myGenAssist API Key** (mga-*)

### 1. Clone & Setup

```bash
git clone https://github.bayer.com/your-org/LLMCouncilMGA.git
cd LLMCouncilMGA
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv myenv

# Activate (Windows)
myenv\Scripts\activate
# Activate (macOS/Linux)
# source myenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set your API key:
```env
OPENROUTER_API_KEY=mga-your-key-here
API_BASE_URL=https://chat.int.bayer.com/api/v2/chat/completions
```

### 5. Run

**Terminal 1 — Backend:**
```bash
myenv\Scripts\activate
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Docker

### Local (JSON storage)
```bash
docker compose up --build
```

### With Redis Memory Backend
```bash
MEMORY_BACKEND=redis docker compose --profile redis up --build
```

See [deploy/DEPLOY.md](deploy/DEPLOY.md) for AWS, Azure, GCP, and Kubernetes deployment guides.

---

## API Reference

### Conversation Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/conversations` | List all conversations |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/{id}` | Get conversation details |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |
| `POST` | `/api/conversations/{id}/message` | Send message (SSE stream) |
| `GET` | `/api/conversations/{id}/export` | Export to markdown |

### Memory Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/memory/stats` | Memory tier statistics |
| `GET` | `/api/memory/{type}` | List memories by tier |
| `GET` | `/api/memory/{type}/{id}` | Get specific memory |
| `POST` | `/api/memory/decision` | Apply learn/unlearn decision |
| `GET` | `/api/memory/search/{type}?q=...` | Search memories |
| `DELETE` | `/api/memory/{type}/{id}` | Delete memory entry |

### System Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/models` | Available models |
| `POST` | `/api/kill` | Kill active session |
| `POST` | `/api/kill/all` | Emergency halt all sessions |

### SSE Event Types
| Event | Stage | Data |
|-------|-------|------|
| `session_start` | — | `{ session_id }` |
| `stage1_start` / `stage1_complete` | S1 | Individual model responses |
| `stage2_start` / `stage2_complete` | S2 | Peer rankings + grounding scores |
| `stage3_start` / `stage3_complete` | S3 | Chairman synthesis |
| `cost_summary` | — | Token usage & cost breakdown |
| `memory_recall` | Pre-S1 | Recalled memories & influence score |
| `memory_gate` | Post-S2 | Grounding vs historical evaluation |
| `memory_learning` | Post-S3 | Learn/unlearn decision + tier IDs |

---

## Testing

```bash
# Activate virtual environment
myenv\Scripts\activate

# Run full test suite (42 tests)
python -m pytest tests/test_memory_pipeline.py -v

# Run with coverage
python -m pytest tests/ -v --tb=short
```

Test coverage includes:
- Storage backend CRUD + search (8 tests)
- Semantic memory: store, merge, unlearn, relearn (4 tests)
- Episodic memory: store, recall, verdict updates (4 tests)
- Procedural memory: store, reinforcement, unlearn (3 tests)
- MemoryManager facade: recall, format, learn, stats (8 tests)
- Orchestrator agents: all 4 agents + edge cases (8 tests)
- End-to-end pipeline simulation (5 tests)
- Backend swap verification (1 test)

---

## Project Structure

```
LLMCouncilMGA/
├── backend/                    # FastAPI backend
│   ├── config.py               # Model config & API settings
│   ├── council.py              # 3-stage council orchestration
│   ├── grounding.py            # 5-rubric grounding evaluation
│   ├── main.py                 # App, routes, SSE streaming
│   ├── memory.py               # 3-tier memory manager
│   ├── memory_store.py         # Cloud-agnostic storage abstraction
│   ├── openrouter.py           # LLM API client (httpx async)
│   ├── orchestrator.py         # Stage-gate orchestrator agents
│   ├── resilience.py           # Self-healing & circuit breaker
│   ├── storage.py              # Conversation persistence
│   └── token_tracking.py       # Token/cost burndown tracking
├── frontend/                   # React 19 + Vite 7
│   └── src/
│       ├── api.js              # Backend API client
│       ├── App.jsx             # Main app shell
│       └── components/
│           ├── ChatInterface.jsx   # Message display & input
│           ├── EnhancePrompt.jsx   # Prompt enhancement UI
│           ├── GroundingScore.jsx   # Circular score bubble
│           ├── KillSwitch.jsx      # Emergency stop button
│           ├── LearnUnlearn.jsx    # Inline memory controls
│           ├── MemoryPanel.jsx     # Memory management panel
│           ├── Settings.jsx        # Model configuration
│           ├── Sidebar.jsx         # Conversation list
│           ├── Stage1.jsx          # Individual responses
│           ├── Stage2.jsx          # Peer ranking matrix
│           ├── Stage3.jsx          # Chairman response
│           └── TokenBurndown.jsx   # Cost/token chart
├── tests/                      # Test suite
│   └── test_memory_pipeline.py # 42 memory pipeline tests
├── deploy/                     # Deployment guides
│   └── DEPLOY.md              # AWS / Azure / GCP / K8s
├── .github/                    # GitHub templates
│   ├── pull_request_template.md
│   └── ISSUE_TEMPLATE/
├── ARCHITECTURE.md             # Full system architecture
├── CONTRIBUTING.md             # Contribution guidelines
├── NOTICE                      # Copyright & attribution
├── Dockerfile                  # Multi-stage container build
├── docker-compose.yml          # Local + Redis profiles
├── pyproject.toml              # Python project metadata
├── requirements.txt            # Python dependencies
├── .env.example                # Environment config template
└── .gitignore                  # Git ignore rules
```

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Backend** | Python, FastAPI, Uvicorn | 3.10+, 0.115+, 0.32+ |
| **Frontend** | React, Vite, react-markdown | 19.x, 7.x, 10.x |
| **HTTP Client** | httpx (async) | 0.27+ |
| **Streaming** | Server-Sent Events (SSE) | — |
| **Storage** | JSON files (pluggable: Redis, DynamoDB, CosmosDB) | — |
| **Container** | Docker, Docker Compose | — |
| **Testing** | pytest, pytest-asyncio | 9.x, 1.x |
| **API Gateway** | Bayer myGenAssist | — |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, branch naming, and PR process.

---

<p align="center">
  <em>Bayer Pharmaceutical Division — Digital Innovation Team</em><br />
  <strong>Science for a better life.</strong>
</p>
