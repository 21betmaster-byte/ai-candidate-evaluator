FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Playwright browser + system deps (used by portfolio.py SPA fallback)
RUN python -m playwright install --with-deps chromium

COPY backend/ ./

ENV PORT=8000
EXPOSE 8000

# Default = API. Worker service overrides CMD to: python -m app.jobs.worker
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
