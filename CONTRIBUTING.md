# Contributing to LLM Council MGA

Thank you for your interest in contributing to the LLM Council MGA platform.

## Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.bayer.com/your-org/LLMCouncilMGA.git
   cd LLMCouncilMGA
   ```

2. **Set up the Python environment**
   ```bash
   python -m venv myenv
   myenv\Scripts\activate        # Windows
   # source myenv/bin/activate   # macOS/Linux
   pip install -r requirements.txt
   ```

3. **Set up the frontend**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API key
   ```

5. **Run tests**
   ```bash
   python -m pytest tests/ -v
   ```

## Development Workflow

### Branch Naming
- `feature/<description>` — New features
- `bugfix/<description>` — Bug fixes
- `refactor/<description>` — Code restructuring

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
```
feat: add Redis memory backend
fix: handle empty grounding scores in Stage 2
refactor: extract memory recall into shared utility
docs: update ARCHITECTURE.md with memory pipeline
test: add orchestrator agent edge case tests
```

### Pull Request Process
1. Create a feature branch from `main`
2. Make your changes with appropriate tests
3. Ensure all tests pass: `python -m pytest tests/ -v`
4. Ensure the frontend builds: `cd frontend && npm run build`
5. Update `ARCHITECTURE.md` if you change system behavior
6. Open a PR with a clear description of changes

## Project Structure

```
LLMCouncilMGA/
├── backend/                # FastAPI backend
│   ├── config.py           # Model configuration & API settings
│   ├── council.py          # 3-stage council orchestration
│   ├── grounding.py        # Grounding score evaluation
│   ├── main.py             # FastAPI app, routes, SSE streaming
│   ├── memory.py           # 3-tier memory manager
│   ├── memory_store.py     # Cloud-agnostic storage abstraction
│   ├── openrouter.py       # LLM API client
│   ├── orchestrator.py     # Stage-gate orchestrator agents
│   ├── resilience.py       # Self-healing & circuit breaker
│   ├── storage.py          # Conversation persistence
│   └── token_tracking.py   # Token/cost burndown tracking
├── frontend/               # React + Vite frontend
│   └── src/
│       ├── components/     # UI components
│       └── api.js          # Backend API client
├── tests/                  # Test suite
├── deploy/                 # Cloud deployment guides
├── ARCHITECTURE.md         # Full system architecture docs
└── docker-compose.yml      # Container orchestration
```

## Adding a New Memory Backend

1. Create a class that extends `MemoryStoreBackend` in `backend/memory_store.py`
2. Implement all abstract methods: `put`, `get`, `delete`, `list_keys`, `query`, `search`
3. Add a factory case in the backend initialization
4. Update `.env.example` with required config variables
5. Add tests in `tests/test_memory_pipeline.py`

## Code Standards

- **Python**: Type hints on all public functions, docstrings on classes/modules
- **JavaScript/React**: Functional components with hooks, prop destructuring
- **CSS**: Follow existing dark-theme variables (`--bg-primary`, `--accent-primary`, etc.)
- **Testing**: Every new backend feature needs corresponding tests

## Questions?

Reach out to the team on Microsoft Teams or open a GitHub Issue.
