# AGENTS.md — Analytics Agent Codebase Guide

This file is written for AI coding agents (Claude Code, Cursor, Copilot, etc.) working on the Analytics Agent codebase. Read it before making changes.

---

## Project in one sentence

Analytics Agent is a LangGraph-based chat agent that uses **DataHub** tools for metadata context and pluggable **SQL engines** (Snowflake first) to answer natural-language data questions, with Vega-Lite charts rendered inline in a React + Vite UI served by the same FastAPI process.

---

## Running the stack

A `justfile` at the repo root covers all common tasks. Install `just` once (`brew install just`), then:

```bash
just install          # uv sync + pnpm install
just start            # build frontend if stale, start backend at :8000
just port=8001 start  # same on a custom port
just stop             # kill the backend
just nuke             # wipe the DB (start from scratch / re-trigger wizard)
just start-remote     # start + print DataHub connection status
just logs             # tail /tmp/analytics_agent.log
just test             # unit tests
just build            # force frontend rebuild
```

`just start` automatically detects whether `frontend/src` is newer than `frontend/dist` and rebuilds only when needed.

### Without just (manual)

```bash
uv sync
cd frontend && pnpm install && pnpm build && cd ..
uv run uvicorn analytics_agent.main:app --reload --port 8000
# → http://localhost:8000
# The setup wizard handles LLM key + connections on first run.
# Optional: cp .env.example .env to pre-configure credentials.
```

### Two-process mode (frontend hot reload)

```bash
# Terminal 1 — backend
uv run uvicorn analytics_agent.main:app --reload --port 8000

# Terminal 2 — Vite dev server with HMR
cd frontend && pnpm dev
# → http://localhost:5173 (proxies /api/* to :8000)
```

**DataHub credentials**: run `datahub init --sso --host https://your-instance.acryl.io/gms` once. The app reads `~/.datahubenv` automatically; or set `DATAHUB_GMS_URL` + `DATAHUB_GMS_TOKEN` in `config.yaml` / `.env`.

**Database**: SQLite at `./data/dev.db` by default. Alembic runs automatically on startup. For Postgres set `DATABASE_URL=postgresql+asyncpg://...`.

---

## Key file map

| Path | What it does |
|------|-------------|
| `backend/src/analytics_agent/main.py` | FastAPI app factory + lifespan (runs Alembic, seeds integrations, mounts SPA) |
| `backend/src/analytics_agent/agent/graph.py` | LangGraph `StateGraph`: ReAct agent → conditional chart node |
| `backend/src/analytics_agent/agent/streaming.py` | `astream_events` → SSE event dicts; handles `on_tool_error` |
| `backend/src/analytics_agent/agent/history.py` | Reconstructs LangChain message history from DB rows; pads orphaned tool calls |
| `backend/src/analytics_agent/agent/chart_tool.py` | `create_chart` LangChain tool; stores spec in `_pending_charts` side-channel |
| `backend/src/analytics_agent/agent/chart_generator.py` | `chart_node`: runs after SQL results; calls chart LLM → updates `pending_chart` state |
| `backend/src/analytics_agent/api/chat.py` | `POST /api/conversations/{id}/messages` → `StreamingResponse` (SSE) |
| `backend/src/analytics_agent/api/settings.py` | Connection CRUD + test + tool toggles + prompt + display settings |
| `backend/src/analytics_agent/api/oauth.py` | SSO browser flow, PAT storage, OAuth popup flow, credential encryption |
| `backend/src/analytics_agent/context/datahub.py` | Builds DataHub LangChain tools via `datahub_agent_context.build_langchain_tools()` |
| `backend/src/analytics_agent/engines/resolver.py` | **Single credential resolution point** — loads Integration + credential from DB |
| `backend/src/analytics_agent/engines/snowflake/engine.py` | Snowflake `QueryEngine`: execute_sql, list_tables, get_schema, preview_table; SSO/key-pair/PAT auth |
| `backend/src/analytics_agent/engines/factory.py` | Engine registry; `register_engine` / `unregister_engine` for dynamic connections |
| `backend/src/analytics_agent/db/models.py` | SQLAlchemy models: Conversation, Message, Integration, IntegrationCredential, Setting |
| `backend/src/analytics_agent/db/repository.py` | Repos: ConversationRepo, MessageRepo, SettingsRepo, IntegrationRepo, CredentialRepo |
| `backend/src/analytics_agent/prompts/system_prompt.md` | Agent system prompt (edit here — loaded at runtime) |
| `frontend/src/components/Chat/ChatView.tsx` | Chat shell; handles welcome-screen → new conversation flow |
| `frontend/src/components/Chat/WelcomeView.tsx` | Landing screen with LLM greeting, suggestion chips, engine selector |
| `frontend/src/components/Settings/SnowflakeAuthSection.tsx` | Segmented auth selector: Password / Private Key / SSO / PAT / OAuth |
| `frontend/src/store/conversations.ts` | Zustand: conversations, messages, engines, streaming state |
| `frontend/src/store/display.ts` | Zustand: app name, logo, cached LLM greeting |

---

## Integrations + credential architecture

Connections are stored in two DB tables:

- **`integrations`** — connection topology (account, warehouse, database, user). `source="yaml"` for `config.yaml` connections, `source="ui"` for UI-created ones.
- **`integration_credentials`** — encrypted auth per connection: `auth_type` ∈ `{sso_externalbrowser, private_key, pat, oauth, password}`.

**Credential resolution** happens in `engines/resolver.py::resolve_engine(engine_name, session)`:
1. Looks up `integration_credentials` for the engine
2. Decrypts the credential and returns a configured engine clone
3. Falls back to env vars for `source="yaml"` connections (backwards compat)

**Never thread individual credential fields** (`oauth_token`, `sso_user`, etc.) through `graph.py` or agent code. Pass the engine object returned by `resolve_engine`.

```python
# chat.py — the only place credentials are resolved
engine = await resolve_engine(engine_name, session)
graph = build_graph(engine=engine, engine_name=engine_name, ...)
```

### Connection write wire format — `{config, secrets}`

`PUT /api/settings/connections/{name}` and `POST /api/settings/connections`
accept a single wire shape:

```jsonc
{
  "config":  { "account": "...", "warehouse": "...", "database": "...", "user": "..." },
  "secrets": { "password": "..." }
}
```

- `config` values are merged directly into `integrations.config` (DB) for engines,
  or into the context-platform's config JSON for DataHub.
- `secrets` keys are validated against each engine's own
  `QueryEngine.secret_env_vars` allow-list (e.g.
  `SnowflakeQueryEngine.secret_env_vars = {"password": "SNOWFLAKE_PASSWORD", ...}`)
  and translated to env-var names before being written to `.env` and
  `os.environ`. Unknown secret keys are rejected with **HTTP 400**. The API
  layer stays ignorant of any particular engine's credential fields.
- `_upsert_env_vars` always double-quotes every value so PEM blocks and passwords
  with special characters (`#`, `$`, `\`, spaces) round-trip correctly.

**How the frontend splits values** — each `ConnectionField` returned by
`GET /connections` has an optional `secret_key` attribute. If present, the field's
value is routed to `body.secrets[secret_key]`; otherwise it goes to
`body.config[key]`. See `splitConnectionValues` in `frontend/src/api/settings.ts`.

**Staged follow-up steps (tracked):**

- **1 - route `body.secrets` to `integration_credentials`** (encrypted, per-connection).
  Adds a `password` auth_type and a `password` branch in `resolver.py`, plus
  `with_password` on `SnowflakeQueryEngine`. After 1 lands, `.env` stops accumulating
  per-connection secrets and two Snowflake connections with different passwords can
  coexist without collision.
- **2 - `GET /api/settings/connections/schemas/{type}`** + frontend renders forms
  generically from the schema. Promotes `QueryEngine.secret_env_vars` into a full
  typed schema (fields, labels, placeholders, required flags) shared with the
  frontend; handler becomes validate -> dispatch.

---

## SSE event flow

```
POST /api/conversations/{id}/messages
  └─ chat.py: _event_stream()
       ├─ resolve_engine(engine_name, session) → configured engine
       ├─ load conversation history → build_history() → LangChain messages
       ├─ build_graph(engine=engine, ...) → LangGraph compiled graph
       └─ stream_graph_events(graph, ...)
            ├─ on_chat_model_stream  → TEXT event
            ├─ on_tool_start        → TOOL_CALL event (skipped for create_chart)
            ├─ on_tool_end          → SQL / TOOL_RESULT / CHART
            ├─ on_tool_error        → TOOL_RESULT (is_error=True)
            ├─ on_chain_end         → captures final_state for chart_node charts
            └─ end of stream        → CHART (fallback) + COMPLETE
```

Frontend consumes SSE via `stream.ts` (fetch + ReadableStream, **not** EventSource — needs POST).

---

## LangGraph agent design

```
START → agent (create_react_agent) → conditional → chart → END
                                          ↓ (no SQL rows)
                                         END
```

- Use `create_agent` from `langchain.agents` (**not** `create_react_agent` from `langgraph.prebuilt`)
- System prompt loaded from `prompts/system_prompt.md` at runtime (editable without restart)
- Tools: DataHub tools (search_documents, search, get_entities, …) + engine tools + `create_chart`
- `chart_node` fires when `get_last_sql_result(state)` finds an `execute_sql` ToolMessage with rows

---

## Chart generation — two paths

| Path | Trigger | How spec reaches frontend |
|------|---------|--------------------------|
| `create_chart` tool | Agent calls tool | `_pending_charts[chart_id]` → `on_tool_end` → CHART event |
| `chart_node` | SQL returned rows | `state.pending_chart` → `on_chain_end` → CHART event |
| Text fallback | Model writes spec as ```json``` | `_extract_chart_from_text` regex → CHART event |

`chart_emitted` flag prevents duplicates across all three paths.

---

## Dynamic connections (UI-created)

Users can add connections via **Settings → Add Connection** without editing `config.yaml`:

1. `POST /api/settings/connections` → creates `Integration` in DB + calls `register_engine()`
2. `DELETE /api/settings/connections/{name}` → removes from DB + calls `unregister_engine()`
3. On server restart, `_seed_integrations()` in `main.py` reloads all integrations from DB

The Snowflake engine supports `with_sso_user()`, `with_private_key()`, `with_pat_token()`, `with_oauth_token()` clone methods — these are called by `resolver.py`, never from agent code.

---

## Multi-turn conversation history

`build_history()` in `agent/history.py` converts DB rows to LangChain messages:

- **User TEXT** → `HumanMessage`
- **TOOL_CALL + TOOL_RESULT pairs** → `AIMessage(tool_calls=[...])` + `ToolMessage`
- Tool calls always use `tc["id"]` for `tool_call_id` (not the result's stored ID) — avoids Anthropic "unexpected tool_use_id" rejections from orphaned DB records
- Turns with no useful content → **skipped** (avoids consecutive HumanMessages)

---

## Serving the frontend

`main.py` mounts the built React SPA after registering all API routes:

```python
_dist = Path(os.getenv("FRONTEND_DIST", "")) or Path(__file__).parents[3] / "frontend" / "dist"

if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(_dist / "index.html", media_type="text/html")
```

- If `dist/` is absent (dev mode), the server runs API-only and Vite handles the frontend
- `FRONTEND_DIST` env var overrides the default path (useful in Docker)
- The catch-all **must be the last route** — FastAPI matches in registration order

---

## Adding a new query engine

1. Create `engines/<name>/engine.py` implementing `QueryEngine`:
   - Expose four tools: `execute_sql`, `list_tables`, `get_schema`, `preview_table`
   - All tools must catch exceptions and return `{"error": str(e)}` — never raise
2. Register in `engines/factory.py` → `_engine_cls()` dict
3. Add connection config to `config.yaml` OR let users add via the Settings UI
4. Add tool list to `api/settings.py` → `_KNOWN_TOOLS`

---

## Changing the system prompt

Edit `prompts/system_prompt.md`. The prompt is loaded at runtime — no restart needed for changes made via the Settings UI (stored in DB). The `{engine_name}` placeholder is substituted at graph build time.

---

## Docker

```bash
# Build (multistage: Node builds frontend, Python 3.12 serves everything)
docker build -f docker/Dockerfile -t analytics-agent .

# Run
docker run -p 8000:8000 --env-file .env analytics-agent
```

GitHub Actions (`.github/workflows/docker.yml`) builds and pushes to GHCR on every push to `main` and version tags.

---

## Common pitfalls

**Do not** use `create_react_agent` from `langgraph.prebuilt` — deprecated in LangGraph v1. Use `create_agent` from `langchain.agents` with `system_prompt=` (string).

**Do not** pass `temperature=0` to `ChatAnthropic` with `claude-opus-4-7` — sampling parameters are removed on this model.

**Do not** use `EventSource` in the frontend — the chat endpoint is a POST. Use `fetch()` + `ReadableStream` (`frontend/src/api/stream.ts`).

**Do not** thread credential fields through `graph.py` — use `resolver.py` to get a pre-configured engine and pass the engine object.

**Do not** store chart Vega-Lite specs as the tool return value — use the `_pending_charts` side-channel.

**Do not** start the backend without loading `.env` — `main.py` calls `load_dotenv()` automatically so this is handled, but env vars must be in `.env`.

**The DB engine is lazy**: `db/base.py` creates the SQLAlchemy async engine on first use. This prevents the sync Alembic migration from deadlocking with the async engine at startup.

**`chat.py` uses its own session**: `_event_stream` opens a fresh `AsyncSession` independent of the `Depends(get_session)` session — FastAPI closes `Depends` sessions before `StreamingResponse` iterates the generator.

**Snowflake Decimal/date types**: `_run_query` in `snowflake/engine.py` coerces `Decimal` → `int`/`float` and `datetime` → ISO string before serialisation. Do not remove this — `orjson` rejects `Decimal`.
