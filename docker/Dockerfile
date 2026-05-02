# ── Stage 1: build React frontend ────────────────────────────────────────────
FROM node:20-alpine AS fe-build
WORKDIR /app

COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN npm install -g pnpm && cd frontend && pnpm install --frozen-lockfile

COPY frontend ./frontend
RUN cd frontend && pnpm build

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock README.md ./
COPY backend/ backend/

RUN uv sync --no-dev
ENV PATH="/app/.venv/bin:$PATH"

COPY alembic.ini config.yaml.example ./
# Use example as the default config; operators override via volume mount or ENGINES_CONFIG env var
RUN cp config.yaml.example config.yaml

# Copy built SPA — FastAPI serves it via static files + SPA fallback
COPY --from=fe-build /app/frontend/dist ./frontend/dist

EXPOSE 8100

CMD ["uv", "run", "uvicorn", "analytics_agent.main:app", \
     "--host", "0.0.0.0", "--port", "8100"]
