set dotenv-load := true

port     := "8100"
dev_port := "8101"
log      := "/tmp/analytics_agent.log"

# List available recipes
default:
    @just --list

# Install all dependencies (Python + Node)
install:
    uv sync
    cd frontend && pnpm install

# Build the frontend for production
build:
    cd frontend && pnpm build

# Build only if frontend/src is newer than the dist bundle
build-if-stale:
    #!/usr/bin/env bash
    if [ ! -f frontend/dist/index.html ] || \
       [ -n "$(find frontend/src -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
      echo "frontend is stale — rebuilding…"
      cd frontend && pnpm build
    else
      echo "frontend is up to date"
    fi

# Type-check frontend without building
typecheck:
    cd frontend && pnpm tsc --noEmit

# Start backend (blocks; use 'dev' for background)
serve:
    uv run uvicorn analytics_agent.main:app --reload --port {{dev_port}}

# Build frontend if stale, then start backend in background (with auto-reload on Python changes)
dev: build-if-stale
    pkill -f "analytics_agent.main" || true
    nohup uv run uvicorn analytics_agent.main:app --reload --port {{dev_port}} > {{log}} 2>&1 &
    sleep 3 && curl -s http://localhost:{{dev_port}}/api/engines | head -c 120
    @echo "\n→ http://localhost:{{dev_port}}  (logs: just logs)"

# Start backend, rebuilding frontend if stale
start: build-if-stale
    pkill -f "analytics_agent.main" || true
    nohup uv run uvicorn analytics_agent.main:app --port {{port}} > {{log}} 2>&1 &
    sleep 3 && curl -s http://localhost:{{port}}/api/engines | head -c 120
    @echo "\n→ http://localhost:{{port}}"

# Start Vite dev server with HMR (use alongside 'serve' for hot-reload frontend)
# → http://localhost:5173 (proxies /api/* to backend)
frontend:
    cd frontend && pnpm dev

# Start backend (reload mode) + Vite dev server in parallel
dev-full:
    pkill -f "analytics_agent.main" || true
    nohup uv run uvicorn analytics_agent.main:app --reload --port {{dev_port}} > {{log}} 2>&1 &
    @echo "Backend → http://localhost:{{dev_port}}"
    cd frontend && pnpm dev

# Kill the backend
stop:
    pkill -f "analytics_agent.main" || true
    @echo "stopped"

# Rebuild frontend and restart backend
restart: build stop start

# Tail backend logs
logs:
    tail -f {{log}}

# Run unit tests
test:
    uv run pytest tests/unit/ -v

# Run integration tests (needs credentials in .env)
test-integration:
    uv run pytest tests/integration/ -v -s

# Run Playwright e2e tests (real backend + mock MCP tools)
test-e2e:
    npx --prefix frontend playwright test --config tests/e2e/playwright.config.ts

# Start the agent pointed at a remote DataHub instance.
# Set DATAHUB_GMS_URL + DATAHUB_GMS_TOKEN in .env for OSS/self-hosted DataHub.
# For Acryl cloud, leave those blank — configure DataHub via MCP in the UI after startup.
# Either way, open http://localhost:{{port}} and the wizard handles the rest.
start-remote:
    #!/usr/bin/env bash
    set -euo pipefail
    just start
    echo ""
    echo "  ┌─────────────────────────────────────────────────────┐"
    echo "  │  Analytics Agent — Remote DataHub status            │"
    echo "  └─────────────────────────────────────────────────────┘"
    # Query the running API for actual DataHub connection state
    uv run python scripts/datahub_status.py {{port}}
    echo ""
    echo "  → http://localhost:{{port}}"

# Quick syntax check of the backend
check:
    uv run python -c "import analytics_agent.main"

# Lint + format check (mirrors CI — run before pushing)
lint:
    uv run ruff check backend/src tests
    uv run ruff format --check backend/src tests

# Auto-fix lint and format issues
fix:
    uv run ruff check --fix backend/src tests
    uv run ruff format backend/src tests

# Wipe the local database and browser state so the onboarding wizard reappears.
# Stops the server, deletes the SQLite DB, clears the dismissed flag hint.
# Re-run 'just start' afterwards to come back up fresh.
nuke: stop
    #!/usr/bin/env bash
    set -euo pipefail
    # Resolve the DB path from DATABASE_URL (or fall back to the SQLite default)
    DB_URL="${DATABASE_URL:-sqlite+aiosqlite:///./data/dev.db}"
    if [[ "$DB_URL" == sqlite* ]]; then
        DB_PATH="${DB_URL#sqlite*:///}"
        DB_PATH="${DB_PATH#./}"
        if [[ -f "$DB_PATH" ]]; then
            rm "$DB_PATH"
            echo "✓ Deleted $DB_PATH"
        else
            echo "  (no SQLite DB found at $DB_PATH — already clean)"
        fi
    else
        echo "Non-SQLite DB detected ($DB_URL)."
        echo "To reset manually, drop and recreate the schema your DATABASE_URL points to."
    fi
    echo ""
    echo "Database wiped. Run 'just start' to come back up fresh."
    echo "Tip: open http://localhost:{{port}}/#setup to force the wizard on an existing session."
