# CLAUDE.md

Read **[AGENTS.md](./AGENTS.md)** first — it is the primary codebase guide for all AI agents.

---

## Claude-specific notes

### Environment

- Python virtualenv is at `.venv/` in the repo root. Always run Python via `uv run <cmd>` or activate with `source .venv/bin/activate`.
- Backend credentials live in `.env`. Source with `set -a && source .env && set +a` before running backend commands in a shell.
- DataHub credentials are in `~/.datahubenv` (written by `datahub init`). The app reads this automatically; no need to copy tokens manually unless overriding with env vars.

### Testing changes

After editing backend Python:
```bash
# Quick syntax check
uv run python -c "import analytics_agent.main"

# Run unit tests
uv run pytest tests/unit/ -v

# Test the full agent pipeline (needs credentials)
cd /path/to/analytics-agent && set -a && source .env && set +a && \
uv run pytest tests/integration/ -v -s
```

After editing frontend TypeScript:
```bash
cd frontend && pnpm tsc --noEmit   # type-check without building
```

### Restarting the backend

When `.env`, `config.yaml`, or Python source changes, the backend needs a restart:
```bash
pkill -f "analytics_agent.main"; sleep 2
set -a && source .env && set +a
nohup uv run uvicorn analytics_agent.main:app --port 8100 > /tmp/analytics_agent.log 2>&1 &
sleep 5 && curl -s http://localhost:8100/api/engines
```

The Vite frontend hot-reloads automatically on TypeScript/TSX changes — no restart needed.

### Commit style

Commits follow conventional format:
```
<type>: <short description>

<optional body>

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

### What not to do

- Do not edit `uv.lock` manually — let `uv sync` manage it
- Do not commit `.env` (it's gitignored) — update `.env.example` instead for new vars
- Do not use `git push --force` on `main`
- Do not add `temperature=0` to `ChatAnthropic` for Opus 4.7 models (API returns 400)
- Do not call `create_react_agent` from `langgraph.prebuilt` (deprecated in v1 — use `create_agent` from `langchain.agents`)
