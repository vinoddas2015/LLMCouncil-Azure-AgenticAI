FROM python:3.12-slim

ARG OPENROUTER_API_KEY
ARG API_BASE_URL
ARG S3_BUCKET_NAME

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=80 \
    WEB_CONCURRENCY=2 \
    OPENROUTER_API_KEY=${OPENROUTER_API_KEY} \
    OPENROUTER_API_URL=${API_BASE_URL} \
    S3_BUCKET_NAME=${S3_BUCKET_NAME}

WORKDIR /app

# Install Python dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy backend application code
COPY backend/ ./backend/

# Ensure local storage path exists
RUN mkdir -p /app/data/conversations

EXPOSE 80

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY}"]
