# ---- stage 1: build the React dashboard ----
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
# vite.config.js writes the build to ../app/static
RUN mkdir -p /app/static && npm run build

# ---- stage 2: compile Python wheels once ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---- stage 3: runtime (small image, non-root user) ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

RUN useradd --create-home --uid 10001 sentinel
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install /wheels/* && rm -rf /wheels

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY demo ./demo
COPY scripts ./scripts
COPY --from=frontend /app/static ./app/static

# Make sources readable by the non-root user regardless of host file permissions.
RUN chmod -R a+rX /app

USER sentinel
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('PORT','8000'), timeout=2).status == 200 else 1)"

# Apply migrations, then serve. PORT is injected by Render/Fly/Railway (defaults to 8000).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
