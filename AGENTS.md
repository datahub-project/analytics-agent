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
just start            # build frontend if stale, start backend at :8100
just port=8102 start  # same on a custom port
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
uv run uvicorn analytics_agent.main:app --reload --port 8101
# → http://localhost:8101
# The setup wizard handles LLM key + connections on first run.
# Optional: cp .env.example .env to pre-configure credentials.
```

### Two-process mode (frontend hot reload)

```bash
# Terminal 1 — backend (dev)
uv run uvicorn analytics_agent.main:app --reload --port 8101

# Terminal 2 — Vite dev server with HMR
cd frontend && pnpm dev
# → http://localhost:5173 (proxies /api/* to :8101)
```

**DataHub credentials**: run `datahub init --sso --host https://your-instance.acryl.io/gms` once. The app reads `~/.datahubenv` automatically; or set `DATAHUB_GMS_URL` + `DATAHUB_GMS_TOKEN` in `config.yaml` / `.env`.

**Database**: SQLite at `./data/dev.db` by default. For Postgres set `DATABASE_URL=postgresql+asyncpg://...`.

**Bootstrap (migrations + seed)**: The FastAPI lifespan no longer runs migrations or seeds — it does read-only initialization (loading engines from the DB, propagating env vars, validating the encryption key). All DB-mutating bootstrap work lives in `analytics_agent.bootstrap` and is invoked via the CLI: `analytics-agent bootstrap` runs Alembic migrate → seed-integrations → seed-context-platforms → seed-defaults, idempotently. Run it before the first `uvicorn` start and after any release that adds migrations. The Helm chart runs it automatically as a `pre-install`/`pre-upgrade` hook.

---

## Key file map

| Path | What it does |
|------|-------------|
| `backend/src/analytics_agent/main.py` | FastAPI app factory + lifespan (read-only init: loads engines, validates encryption key, mounts SPA — no migrations/seeds) |
| `backend/src/analytics_agent/agent/graph.py` | LangGraph `StateGraph`: ReAct agent → conditional chart node |
| `backend/src/analytics_agent/agent/streaming.py` | `astream_events` → SSE event dicts; handles `on_tool_error` |
| `backend/src/analytics_agent/agent/history.py` | Reconstructs LangChain message history from DB rows; pads orphaned tool calls |
| `backend/src/analytics_agent/agent/chart_tool.py` | `create_chart` LangChain tool; stores spec in `_pending_charts` side-channel |
| `backend/src/analytics_agent/agent/chart_generator.py` | `chart_node`: runs after SQL results; calls chart LLM → updates `pending_chart` state |
| `backend/src/analytics_agent/api/chat.py` | `POST /api/conversations/{id}/messages` → `StreamingResponse` (SSE) |
| `backend/src/analytics_agent/api/settings.py` | Connection CRUD + test + tool toggles + prompt + display settings |
| `backend/src/analytics_agent/api/oauth.py` | SSO browser flow, PAT storage, OAuth popup flow, credential encryption |
| `backend/src/analytics_agent/context/datahub.py` | Builds DataHub LangChain tools via `datahub_agent_context.build_langchain_tools()` |
| `backend/src/analytics_agent/engines/factory.py` | Engine registry + `ConnectorSpec` map; native connectors (Snowflake, BigQuery) resolved to MCP subprocesses |
| `backend/src/analytics_agent/engines/mcp/engine.py` | `MCPQueryEngine` — discovers tools from a subprocess via `get_tools_async()`, caches client to keep subprocess alive |
| `backend/src/analytics_agent/engines/sqlalchemy/engine.py` | In-process engine for MySQL, PostgreSQL, SQLite via SQLAlchemy |
| `backend/src/analytics_agent/api/connectors.py` | Connector lifecycle: `GET /api/connectors/{type}/status`, `POST /api/connectors/{type}/install`, `POST /api/connectors/{type}/test` |
| `connectors/snowflake/` | Standalone MCP server package — runs as a subprocess launched by the core via `uvx`; owns all Snowflake deps |
| `connectors/bigquery/` | Standalone MCP server package — same pattern for BigQuery/GCP deps |
| `backend/src/analytics_agent/db/models.py` | SQLAlchemy models: Conversation, Message, Integration, IntegrationCredential, Setting |
| `backend/src/analytics_agent/db/repository.py` | Repos: ConversationRepo, MessageRepo, SettingsRepo, IntegrationRepo, CredentialRepo |
| `backend/src/analytics_agent/prompts/system_prompt.md` | Agent system prompt (edit here — loaded at runtime) |
| `frontend/src/components/Chat/ChatView.tsx` | Chat shell; handles welcome-screen → new conversation flow |
| `frontend/src/components/Chat/WelcomeView.tsx` | Landing screen with LLM greeting, suggestion chips, engine selector |
| `frontend/src/components/Settings/SnowflakeAuthSection.tsx` | Segmented auth selector: Password / Private Key / SSO / PAT / OAuth |
| `frontend/src/store/conversations.ts` | Zustand: conversations, messages, engines, streaming state |
| `frontend/src/store/display.ts` | Zustand: app name, logo, cached LLM greeting |

---

## Engine architecture — MCP subprocess isolation

Heavy native connectors (Snowflake, BigQuery) run as **isolated MCP server subprocesses** launched by the core via `uvx`. The core package has no Snowflake or BigQuery Python deps.

```
analytics-agent (core)
  └── MCPQueryEngine ──stdio──▶ analytics-agent-connector-snowflake (own venv)
                     ──stdio──▶ analytics-agent-connector-bigquery  (own venv)
                     ──SSE───▶  any remote MCP server
```

**`ConnectorSpec`** in `factory.py` describes each native connector:

```python
"snowflake": ConnectorSpec(
    package="analytics-agent-connector-snowflake",
    env_map={"account": "SNOWFLAKE_ACCOUNT", "private_key": "SNOWFLAKE_PRIVATE_KEY", ...},
    secret_env_vars={"password": "SNOWFLAKE_PASSWORD", "private_key": "SNOWFLAKE_PRIVATE_KEY", ...},
    required_keys=["account", "user"],
    credential_keys=["password", "private_key", "pat_token"],
)
```

`config.yaml` syntax is **unchanged** — `type: snowflake` works as before. The factory resolves it to an `MCPQueryEngine` that launches the connector subprocess via `uvx`, passing connection config as env vars. Users never see MCP or uvx.

**Connector packages** live in `connectors/<name>/` — each is a standalone Python package with its own `pyproject.toml`, deps, and an MCP server entry-point:

```bash
connectors/
  snowflake/
    pyproject.toml   # name: analytics-agent-connector-snowflake
    analytics_agent_connector_snowflake/server.py  # FastMCP server, 4 tools
  bigquery/
    pyproject.toml   # name: analytics-agent-connector-bigquery
    analytics_agent_connector_bigquery/server.py
```

**Docker pre-baking** — the Dockerfile installs connector packages at build time via `uv tool install` so they're available offline:

```dockerfile
ARG CONNECTORS="snowflake bigquery"
COPY connectors/ connectors/
RUN for c in $CONNECTORS; do uv tool install "connectors/$c"; done
```

**UI install flow** — for new installs the Settings "Add data source" form checks `GET /api/connectors/{type}/status`. If the package isn't found, an "Install connector" step runs `uv tool install` before showing the config form.

## Integrations + credential architecture

Connections are stored in two DB tables:

- **`integrations`** — connection topology (`account`, `warehouse`, `database`, `user`, credentials). `source="yaml"` for `config.yaml` connections, `source="ui"` for UI-created ones.
- `integration_credentials` — encrypted per-connection auth (SSO sessions; legacy from before credential fields moved to `integrations.config`).

Credentials for MCP connectors are stored as plain fields in `integrations.config` (e.g. `{"account": "...", "private_key": "-----BEGIN..."}`). They are forwarded to the subprocess as env vars via `ConnectorSpec.build_mcp_config()`.

`ConnectorSpec.is_configured(conn_cfg)` is the single source of truth for whether a connection has enough credentials to be shown as "Connected". Adding a new connector type means declaring `required_keys` and `credential_keys` on its spec — `settings.py` never needs to be touched for status logic.

### Connection write wire format — `{config, secrets}`

`PUT /api/settings/connections/{name}` and `POST /api/settings/connections`
accept a single wire shape:

```jsonc
{
  "config":  { "account": "...", "warehouse": "...", "database": "...", "user": "..." },
  "secrets": { "password": "..." }
}
```

- `config` values are stored in `integrations.config` (DB).
- `secrets` keys are validated via `factory.get_secret_env_vars(type)` and written to `.env` / `os.environ`. Unknown secret keys are rejected with HTTP 400.

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

## Adding a new query engine (connector package pattern)

All new native connectors follow the MCP subprocess model. The core package gains no new deps.

### 1. Create the connector package

```
connectors/<name>/
  pyproject.toml
  README.md
  analytics_agent_connector_<name>/
    __init__.py
    server.py          # FastMCP server exposing 4 tools
```

`pyproject.toml` minimal shape:
```toml
[project]
name = "analytics-agent-connector-<name>"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0.0",
    "orjson>=3.10.0",
    "<your-db-driver>",
    # cryptography pinned <43 to avoid SIGILL on some ARM hosts:
    "cryptography>=42.0.0,<43.0.0",
]
[project.scripts]
analytics-agent-connector-<name> = "analytics_agent_connector_<name>.server:main"
```

`server.py` template:
```python
import os
from mcp.server.fastmcp import FastMCP
import orjson

mcp = FastMCP("<name>-connector")
SQL_ROW_LIMIT = int(os.environ.get("SQL_ROW_LIMIT", "500"))

@mcp.tool()
def execute_sql(sql: str) -> str:
    """Execute SQL. Returns JSON with columns and rows."""
    ...

@mcp.tool()
def list_tables(schema: str = "") -> str: ...

@mcp.tool()
def get_schema(table: str) -> str: ...

@mcp.tool()
def preview_table(table: str, limit: int = 10) -> str: ...

def main() -> None:
    mcp.run()
```

Rules:
- All tools must return `orjson.dumps(result).decode()` — never raise
- Read all config from env vars (`<NAME>_HOST`, `<NAME>_USER`, etc.)
- Connection objects should be module-level globals (one process per config)

### 2. Register in `engines/factory.py`

Add a `ConnectorSpec` to `_CONNECTOR_MAP`:

```python
"<name>": ConnectorSpec(
    package="analytics-agent-connector-<name>",
    env_map={
        "host":     "<NAME>_HOST",
        "user":     "<NAME>_USER",
        "password": "<NAME>_PASSWORD",
        # ... map every config.yaml key → subprocess env var
    },
    secret_env_vars={
        "password": "<NAME>_PASSWORD",
    },
    required_keys=["host", "user"],
    credential_keys=["password"],   # at least one must be present for "connected" status
),
```

That's all for the backend — `settings.py` status logic, `chat.py` routing, and the test endpoint all work automatically.

### 3. Add to `api/settings.py` → `_KNOWN_TOOLS`

```python
"<name>": [
    {"name": "list_tables",   "label": "List tables"},
    {"name": "get_schema",    "label": "Table schema"},
    {"name": "preview_table", "label": "Preview data"},
    {"name": "execute_sql",   "label": "Execute SQL"},
],
```

### 4. Add frontend plugin

Create `frontend/src/components/Settings/connections/plugins/<name>.tsx`:

```typescript
import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin } from "../types";

export const <name>Plugin: ConnectionPlugin = {
  id: "<name>",
  serviceId: "<name>",
  label: "My DB",
  category: "engine",
  transport: "native",   // triggers install check + form
  description: "Connect to My DB",
  Form: ({ onDone, onCancel }) => (
    <SimpleFormShell
      fields={[
        { key: "host",     label: "Host",     required: true, placeholder: "localhost" },
        { key: "user",     label: "User",     placeholder: "admin" },
        { key: "password", label: "Password", type: "password" as const },
      ]}
      onCancel={onCancel}
      onDone={onDone}
    />
  ),
};
```

Register it in `frontend/src/components/Settings/connections/index.ts`.

### 5. Add to Dockerfile

```dockerfile
ARG CONNECTORS="snowflake bigquery <name>"
```

The Dockerfile loop installs all listed connectors at build time.

---

## Changing the system prompt

Edit `prompts/system_prompt.md`. The prompt is loaded at runtime — no restart needed for changes made via the Settings UI (stored in DB). The `{engine_name}` placeholder is substituted at graph build time.

---

## Docker

```bash
# Build (multistage: Node builds frontend, Python 3.12 serves everything)
docker build -f docker/Dockerfile -t analytics-agent .

# Run
docker run -p 8100:8100 --env-file .env analytics-agent
```

GitHub Actions (`.github/workflows/docker.yml`) builds and pushes to GHCR on every push to `main` and version tags.

---

## Common pitfalls

**Do not** use `create_react_agent` from `langgraph.prebuilt` — deprecated in LangGraph v1. Use `create_agent` from `langchain.agents` with `system_prompt=` (string).

**Do not** pass `temperature=0` to `ChatAnthropic` with `claude-opus-4-7` — sampling parameters are removed on this model.

**Do not** use `EventSource` in the frontend — the chat endpoint is a POST. Use `fetch()` + `ReadableStream` (`frontend/src/api/stream.ts`).

**Do not** put connector-specific Python deps in the core `pyproject.toml` — new connectors belong in `connectors/<name>/` as separate MCP server packages.

**Do not** store chart Vega-Lite specs as the tool return value — use the `_pending_charts` side-channel.

**Do not** start the backend without loading `.env` — `main.py` calls `load_dotenv()` automatically so this is handled, but env vars must be in `.env`.

**The DB engine is lazy**: `db/base.py` creates the SQLAlchemy async engine on first use. This prevents the sync Alembic migration from deadlocking with the async engine at startup.

**`chat.py` uses its own session**: `_event_stream` opens a fresh `AsyncSession` independent of the `Depends(get_session)` session — FastAPI closes `Depends` sessions before `StreamingResponse` iterates the generator.

**Connector type coercion**: each connector's `_run_query` must coerce DB-specific types (`Decimal`, `datetime`, `bytes`, `UUID`) to JSON-native Python types before returning. `orjson` rejects `Decimal` — convert to `int`/`float` depending on whether it has a fractional part.
