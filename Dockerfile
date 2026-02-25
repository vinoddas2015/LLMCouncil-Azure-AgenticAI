FROM python:3.12-slim

# ── Azure App Service uses WEBSITES_PORT or defaults to 8000 ──
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_CONCURRENCY=4

WORKDIR /app

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy backend application code
COPY backend/ ./backend/

# Ensure local storage path exists (file-based fallback)
RUN mkdir -p /app/data/conversations /app/data/memory /app/data/skills

EXPOSE 8000

# All secrets are injected via App Service Application Settings (env vars)
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY}"]
