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
   # Backend tests
   python -m pytest tests/ -v

   # Frontend accessibility tests (WCAG 3.0)
   cd frontend
   npm test
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
4. Ensure frontend accessibility tests pass: `cd frontend && npm test`
5. Ensure the frontend builds: `cd frontend && npm run build`
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
│       ├── components/     # UI components (incl. ThemeToggle)
│       ├── ThemeContext.jsx # Day/Night theme provider
│       ├── __tests__/      # 89 WCAG 3.0 accessibility tests
│       └── api.js          # Backend API client
├── tests/                  # Test suite
├── deploy/                 # Cloud deployment guides
└── ARCHITECTURE.md         # Full system architecture docs
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
- **CSS**: Use CSS custom properties (`--bg-primary`, `--accent-primary`, etc.) — all colours must work in BOTH Day and Light themes; verify APCA Lc ≥ 45 for non-text and Lc ≥ 75 for text
- **Accessibility**: Follow WCAG 3.0 — ARIA roles, keyboard operability, accessible names, focus indicators
- **Testing**: Every new backend feature needs corresponding tests; new UI components need accessibility tests in `frontend/src/__tests__/`

## Questions / Suggestions?

Reach out to the team at [llmcouncil@bayer.com](mailto:llmcouncil@bayer.com), on Microsoft Teams, or open a GitHub Issue.
