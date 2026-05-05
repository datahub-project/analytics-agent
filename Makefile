PORT     := 8100
DEV_PORT := 8101
LOG      := /tmp/analytics_agent.log

# Load .env if present (same behaviour as just's set dotenv-load)
-include .env
export

.DEFAULT_GOAL := help

.PHONY: help install build typecheck serve dev start frontend dev-full stop \
        restart logs test test-integration test-e2e start-remote check lint fix nuke

# ── Help ───────────────────────────────────────────────────────────────────────

help:
	@echo "Usage: make <target>  [PORT=8100]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

# ── Build ──────────────────────────────────────────────────────────────────────

install: ## Install all dependencies (Python + Node)
	uv sync
	cd frontend && pnpm install

# Make's native dependency tracking replaces just's build-if-stale recipe.
# Re-runs pnpm build only when frontend/src files are newer than the bundle.
frontend/dist/index.html: $(shell find frontend/src -type f 2>/dev/null)
	cd frontend && pnpm build

build: ## Force-rebuild the frontend
	cd frontend && pnpm build

typecheck: ## Type-check frontend without building
	cd frontend && pnpm tsc --noEmit

# ── Development ────────────────────────────────────────────────────────────────

serve: ## Start backend in foreground with auto-reload (blocking)
	uv run analytics-agent bootstrap
	uv run uvicorn analytics_agent.main:app --reload --port $(DEV_PORT)

dev: frontend/dist/index.html ## Build frontend if stale, start backend with auto-reload
	uv run analytics-agent bootstrap
	pkill -f "analytics_agent.main" || true
	nohup uv run uvicorn analytics_agent.main:app --reload --port $(DEV_PORT) > $(LOG) 2>&1 &
	sleep 3 && curl -s http://localhost:$(DEV_PORT)/api/engines | head -c 120
	@echo "\n→ http://localhost:$(DEV_PORT)  (logs: make logs)"

start: frontend/dist/index.html ## Build frontend if stale, start backend on PORT
	uv run analytics-agent bootstrap
	pkill -f "analytics_agent.main" || true
	nohup uv run uvicorn analytics_agent.main:app --port $(PORT) > $(LOG) 2>&1 &
	sleep 3 && curl -s http://localhost:$(PORT)/api/engines | head -c 120
	@echo "\n→ http://localhost:$(PORT)"

frontend: ## Start Vite dev server with HMR (use alongside 'serve')
	cd frontend && pnpm dev

dev-full: ## Start backend (reload) + Vite dev server in parallel
	uv run analytics-agent bootstrap
	pkill -f "analytics_agent.main" || true
	nohup uv run uvicorn analytics_agent.main:app --reload --port $(DEV_PORT) > $(LOG) 2>&1 &
	@echo "Backend → http://localhost:$(DEV_PORT)"
	cd frontend && pnpm dev

stop: ## Kill the backend
	pkill -f "analytics_agent.main" || true
	@echo "stopped"

restart: build stop start ## Force-rebuild frontend and restart backend

logs: ## Tail backend logs
	tail -f $(LOG)

# ── Testing ────────────────────────────────────────────────────────────────────

test: ## Run unit tests
	uv run pytest tests/unit/ -v

test-integration: ## Run integration tests (needs credentials in .env)
	uv run pytest tests/integration/ -v -s

test-e2e: ## Run Playwright e2e tests (real backend + mock MCP tools)
	npx --prefix frontend playwright test --config tests/e2e/playwright.config.ts

# ── Quality ────────────────────────────────────────────────────────────────────

check: ## Quick syntax check of the backend
	uv run python -c "import analytics_agent.main"

lint: ## Lint + format check (mirrors CI)
	uv run ruff check backend/src tests
	uv run ruff format --check backend/src tests

fix: ## Auto-fix lint and format issues
	uv run ruff check --fix backend/src tests
	uv run ruff format backend/src tests

# ── Remote / DataHub ──────────────────────────────────────────────────────────

start-remote: start ## Start agent pointed at a remote DataHub instance
	@echo ""
	@echo "  ┌─────────────────────────────────────────────────────┐"
	@echo "  │  Analytics Agent — Remote DataHub status            │"
	@echo "  └─────────────────────────────────────────────────────┘"
	uv run python scripts/datahub_status.py $(PORT)
	@echo ""
	@echo "  → http://localhost:$(PORT)"

# ── Maintenance ────────────────────────────────────────────────────────────────

nuke: stop ## Wipe local DB so the onboarding wizard reappears
	@DB_URL="$${DATABASE_URL:-sqlite+aiosqlite:///./data/dev.db}"; \
	if echo "$$DB_URL" | grep -q "^sqlite"; then \
	  DB_PATH=$$(echo "$$DB_URL" | sed 's|sqlite.*:///||; s|^\./||'); \
	  if [ -f "$$DB_PATH" ]; then \
	    rm "$$DB_PATH" && echo "✓ Deleted $$DB_PATH"; \
	  else \
	    echo "  (no SQLite DB found at $$DB_PATH — already clean)"; \
	  fi; \
	else \
	  echo "Non-SQLite DB detected ($$DB_URL)."; \
	  echo "To reset manually, drop and recreate the schema your DATABASE_URL points to."; \
	fi
	@echo ""
	@echo "Database wiped. Run 'make start' to come back up fresh."
	@echo "Tip: open http://localhost:$(PORT)/#setup to force the wizard on an existing session."
