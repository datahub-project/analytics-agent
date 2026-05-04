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
# Add venv and uv tool bin dirs to PATH.
# uv tool install puts binaries in ~/.local/bin (i.e. /root/.local/bin for root).
ENV PATH="/app/.venv/bin:/root/.local/bin:$PATH"

# Pre-install connector packages so they're available offline at runtime.
# Override at build time: docker build --build-arg CONNECTORS="snowflake bigquery"
# Set to empty string to build a connector-free image: --build-arg CONNECTORS=""
ARG CONNECTORS="snowflake bigquery"
COPY connectors/ connectors/
RUN if [ -n "$CONNECTORS" ]; then \
      for c in $CONNECTORS; do \
        if [ -d "connectors/$c" ]; then \
          echo "→ Installing connector from local source: $c" && \
          uv tool install "connectors/$c"; \
        else \
          echo "→ Installing connector from PyPI: analytics-agent-connector-$c" && \
          uv tool install "analytics-agent-connector-$c"; \
        fi; \
      done; \
    fi

COPY alembic.ini config.yaml.example ./
# Use example as the default config; operators override via volume mount or ENGINES_CONFIG env var
RUN cp config.yaml.example config.yaml

# Copy built SPA — FastAPI serves it via static files + SPA fallback
COPY --from=fe-build /app/frontend/dist ./frontend/dist

EXPOSE 8100

CMD ["sh", "-c", "analytics-agent bootstrap && uvicorn analytics_agent.main:app --host 0.0.0.0 --port 8100"]
