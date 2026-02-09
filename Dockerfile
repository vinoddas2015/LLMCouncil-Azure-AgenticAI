# ============================================================
# LLM Council MGA — Multi-stage Dockerfile (Cloud-Agnostic)
# ============================================================
# Stage 1: Build the React frontend
# Stage 2: Production image with Python backend + static assets
# ============================================================

# ---- Stage 1: Frontend build ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Production image ----
FROM python:3.12-slim AS production
LABEL maintainer="LLM Council Team"
LABEL description="LLM Council MGA — Multi-model council orchestration with memory management"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r council && useradd -r -g council -m council

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Copy backend code
COPY backend/ ./backend/
COPY main.py ./

# Copy built frontend assets
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directories (memory store, conversations)
RUN mkdir -p data/conversations data/memory/semantic data/memory/episodic data/memory/procedural \
    && chown -R council:council /app/data

# Switch to non-root
USER council

# Environment defaults (override at runtime)
ENV PORT=8001
ENV HOST=0.0.0.0
ENV MEMORY_BACKEND=local
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=info

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

EXPOSE ${PORT}

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
