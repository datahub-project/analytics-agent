#!/usr/bin/env bash
# DataHub + Analytics Agent Quickstart
# Idempotent: safe to re-run at any point.
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

ok()  { echo -e "${GREEN}[✓]${NC} $*"; }
go()  { echo -e "${CYAN}[→]${NC} $*"; }
warn(){ echo -e "${YELLOW}[!]${NC} $*"; }
die() { echo -e "${RED}[✗] ERROR:${NC} $*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"


# Source .env if present so variables like ANTHROPIC_API_KEY are available
# without the user needing to export them manually before running the script.
if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

# ──────────────────────────────────────────────────────────────────────────────
# Banner
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   DataHub + Analytics Agent Quickstart          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ──────────────────────────────────────────────────────────────────────────────
# 1. Prerequisites
# ──────────────────────────────────────────────────────────────────────────────
go "Checking prerequisites..."

check_cmd() {
    local cmd="$1"
    local hint="${2:-}"
    if ! command -v "$cmd" &>/dev/null; then
        die "'$cmd' not found.${hint:+ $hint}"
    fi
    ok "$cmd found"
}

check_cmd docker       "Install Docker Desktop: https://www.docker.com/products/docker-desktop"
check_cmd datahub      "Install DataHub CLI: pip install acryl-datahub"
check_cmd uv           "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
check_cmd python3      "Install Python 3.11+: https://python.org"
# pnpm not required — the Docker image builds the frontend internally

# ──────────────────────────────────────────────────────────────────────────────
# 2. LLM API key (optional here — the browser wizard handles it if not set)
# ──────────────────────────────────────────────────────────────────────────────
_LLM_KEY_SOURCE=""
# Explicit LLM_PROVIDER=bedrock takes priority — Bedrock has no single env var,
# so we treat it as opt-in via either LLM_PROVIDER or the presence of ~/.aws.
if [[ "${LLM_PROVIDER:-}" == "bedrock" ]]; then
    if [[ ! -d "$HOME/.aws" ]]; then
        die "LLM_PROVIDER=bedrock set but ~/.aws not found. Run 'aws configure' or 'aws sso login' first, then retry."
    fi
    go "Verifying AWS credentials..."
    if ! aws sts get-caller-identity &>/dev/null; then
        die "AWS credentials not valid or expired. Run 'aws sso login' (or 'aws configure') and retry."
    fi
    _aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
    go "Verifying Bedrock access in region ${_aws_region}..."
    if ! aws bedrock list-foundation-models --region "$_aws_region" --output text &>/dev/null; then
        die "Bedrock not accessible in region ${_aws_region}. Check that:
  • Bedrock is enabled in your account (console.aws.amazon.com/bedrock)
  • Your IAM role has bedrock:ListFoundationModels permission"
    fi
    _LLM_KEY_SOURCE="bedrock"
    ok "Bedrock accessible in ${_aws_region} — will mount ~/.aws into the container (read-only)"
elif [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    _LLM_KEY_SOURCE="anthropic"
    ok "ANTHROPIC_API_KEY found — will be pre-configured in the container"
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    _LLM_KEY_SOURCE="openai"
    ok "OPENAI_API_KEY found — will be pre-configured in the container"
elif [[ -n "${GOOGLE_API_KEY:-}" ]]; then
    _LLM_KEY_SOURCE="google"
    ok "GOOGLE_API_KEY found — will be pre-configured in the container"
else
    warn "No LLM API key found in environment — you'll enter it in the browser after startup"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 3. Start DataHub (if not already running)
# ──────────────────────────────────────────────────────────────────────────────
go "Detecting DataHub..."

# GMS URL — can be overridden via env var before running the script.
DATAHUB_GMS_URL="${DATAHUB_GMS_URL:-http://localhost:8080}"

# ── Probe helpers ─────────────────────────────────────────────────────────────

# Returns 0 if the endpoint at $1 responds like a DataHub GMS /health endpoint.
# We don't care about Docker project names (OSS uses "datahub", cloud uses "acryl",
# others may differ) — we just check if the service quacks like DataHub.
_gms_healthy() {
    local url="${1:-$DATAHUB_GMS_URL}"
    curl -sf --max-time 3 "${url}/health" &>/dev/null
}

# Returns 0 if MySQL on localhost:3306 accepts the given credentials.
_mysql_reachable() {
    local user="${1:-datahub}" pass="${2:-datahub}"
    uv run python -c "
import pymysql, sys
try:
    conn = pymysql.connect(host='localhost', port=3306, user='${user}', password='${pass}', connect_timeout=3)
    conn.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

# Returns 0 if the 'datahub' schema exists in MySQL (confirming it's a DataHub MySQL instance).
_mysql_has_datahub_schema() {
    local user="${1:-datahub}" pass="${2:-datahub}"
    uv run python -c "
import pymysql, sys
try:
    conn = pymysql.connect(host='localhost', port=3306, user='${user}', password='${pass}', connect_timeout=3)
    cur = conn.cursor()
    cur.execute(\"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='datahub'\")
    found = cur.fetchone() is not None
    conn.close()
    sys.exit(0 if found else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

# ── Detection logic ────────────────────────────────────────────────────────────

MYSQL_USER="${MYSQL_USER:-datahub}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-datahub}"
MYSQL_DATABASE="${MYSQL_DATABASE:-analytics_agent_demo}"
# Admin (root) credentials — needed only for CREATE DATABASE + GRANT.
# DataHub OSS and Acryl both default to root/datahub.
MYSQL_ADMIN_USER="${MYSQL_ADMIN_USER:-root}"
MYSQL_ADMIN_PASSWORD="${MYSQL_ADMIN_PASSWORD:-datahub}"

DATAHUB_GMS_TOKEN=""

# ── Provision a local GMS token via datahub init ───────────────────────────────
# Back up ~/.datahubenv, run `datahub init` against the local instance to mint a
# fresh token, extract it, then restore the backup so the user's regular env is
# untouched.  Can be skipped by pre-setting DATAHUB_GMS_TOKEN in the environment.
_provision_local_token() {
    # 1) Honor pre-set env var.
    if [[ -n "${DATAHUB_GMS_TOKEN:-}" ]]; then
        ok "Using DATAHUB_GMS_TOKEN from environment"
        return
    fi

    # 2) Reuse ~/.datahubenv if it already points at the same GMS host.
    if [[ -f "$HOME/.datahubenv" ]]; then
        local existing_host existing_token
        read -r existing_host existing_token < <(uv run python3 -c "
import yaml
with open('$HOME/.datahubenv') as f:
    cfg = yaml.safe_load(f) or {}
gms = cfg.get('gms') or {}
print(gms.get('server',''), gms.get('token',''))
" 2>/dev/null) || true
        if [[ "$existing_host" == "$DATAHUB_GMS_URL" && -n "$existing_token" ]]; then
            # Validate the token is actually accepted by this DataHub instance
            # before trusting it — an expired or stale token would silently
            # break ingestion later in the script.
            if curl -sf \
                -H "Authorization: Bearer $existing_token" \
                -H "Content-Type: application/json" \
                -X POST "$DATAHUB_GMS_URL/api/graphql" \
                -d '{"query":"{ me { corpUser { urn } } }"}' &>/dev/null; then
                DATAHUB_GMS_TOKEN="$existing_token"
                ok "Reusing token from ~/.datahubenv (verified against ${DATAHUB_GMS_URL})"
                return
            fi
            # Token rejected — fall through to mint a fresh one.
        fi
    fi

    # 3) Fall back to minting a fresh token via 'datahub init'.
    go "Provisioning local DataHub token via 'datahub init'..."

    # Use a temp HOME so datahub init writes to a throwaway dir,
    # leaving the real ~/.datahubenv completely untouched.
    local tmp_home
    tmp_home=$(mktemp -d)

    HOME="$tmp_home" datahub init \
        --username datahub \
        --password datahub \
        --force \
        --host "$DATAHUB_GMS_URL" 2>/dev/null || true

    local token
    token=$(uv run python3 -c "
import yaml, sys
with open('${tmp_home}/.datahubenv') as f:
    cfg = yaml.safe_load(f)
print((cfg.get('gms') or {}).get('token', ''), end='')
" 2>/dev/null) || true

    rm -rf "$tmp_home"

    if [[ -z "$token" ]]; then
        warn "Could not provision local GMS token — metadata ingestion may fail if auth is required."
    else
        DATAHUB_GMS_TOKEN="$token"
        ok "Local GMS token provisioned (your ~/.datahubenv is untouched)"
    fi
}

if _gms_healthy; then
    echo ""
    ok "DataHub GMS is already running at ${DATAHUB_GMS_URL}"

    # Confirm MySQL also looks like a DataHub MySQL (has the 'datahub' schema).
    if _mysql_has_datahub_schema "$MYSQL_USER" "$MYSQL_PASSWORD"; then
        ok "MySQL at localhost:3306 has the 'datahub' schema — using existing instance"
    elif _mysql_reachable "$MYSQL_USER" "$MYSQL_PASSWORD"; then
        warn "MySQL is reachable but the 'datahub' schema was not found."
        warn "Proceeding anyway — data will be loaded into analytics_agent_demo."
    else
        warn "MySQL not reachable at localhost:3306 with user=${MYSQL_USER}."
        warn "If your instance uses different credentials, set MYSQL_USER / MYSQL_PASSWORD before running this script."
    fi

    _provision_local_token

    # ── If OPENAI_API_KEY is set, ensure GMS has semantic search enabled ───────
    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        # Find the GMS container (handles both "datahub-gms" and "datahub-gms-debug" etc.)
        GMS_CONTAINER=$(docker ps --format "{{.Names}}" | grep -E "datahub-gms" | grep -v upgrade | head -1)
        if [[ -n "$GMS_CONTAINER" ]]; then
            SEMANTIC_ALREADY=$(docker exec "$GMS_CONTAINER" sh -c 'echo ${ELASTICSEARCH_SEMANTIC_SEARCH_ENABLED:-false}' 2>/dev/null)
            if [[ "$SEMANTIC_ALREADY" != "true" ]]; then
                warn "DataHub is running but semantic search is not enabled."
                warn "To enable: restart DataHub with OPENAI_API_KEY set (run this script again after 'datahub docker quickstart --stop')."
            else
                ok "Semantic search is already enabled on the running DataHub instance"
            fi
        fi
    fi

    echo ""
    warn "Skipping 'datahub docker quickstart' — using the existing DataHub instance above."
    echo ""
else
    go "No DataHub GMS found at ${DATAHUB_GMS_URL} — starting DataHub OSS quickstart..."

    # ── Optional: enable semantic search if OPENAI_API_KEY is available ───────
    # Semantic search requires GMS to receive extra env vars that the default
    # quickstart compose does not include. We inject them via a compose override
    # that is passed alongside the base quickstart file using -f (multiple=True).
    SEMANTIC_COMPOSE_ARGS=""
    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        go "OPENAI_API_KEY detected — enabling semantic search for DataHub..."
        SEMANTIC_OVERRIDE_FILE="$(mktemp /tmp/datahub-semantic-XXXXXX.yml)"
        cat > "$SEMANTIC_OVERRIDE_FILE" <<EOF
services:
  datahub-gms-quickstart:
    environment:
      - ELASTICSEARCH_SEMANTIC_SEARCH_ENABLED=true
      - SEARCH_SERVICE_SEMANTIC_SEARCH_ENABLED=true
      - ELASTICSEARCH_SEMANTIC_SEARCH_ENTITIES=document
      - ELASTICSEARCH_SEMANTIC_VECTOR_DIMENSION=3072
      - ELASTICSEARCH_SEMANTIC_KNN_ENGINE=faiss
      - ELASTICSEARCH_SEMANTIC_SPACE_TYPE=cosinesimil
      - EMBEDDING_PROVIDER_TYPE=openai
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_EMBEDDING_MODEL=${OPENAI_EMBEDDING_MODEL:-text-embedding-3-large}
EOF
        DH_DEFAULT_COMPOSE="$HOME/.datahub/quickstart/docker-compose.yml"
        if [[ -f "$DH_DEFAULT_COMPOSE" ]]; then
            SEMANTIC_COMPOSE_ARGS="-f ${DH_DEFAULT_COMPOSE} -f ${SEMANTIC_OVERRIDE_FILE}"
        fi
        ok "Semantic search overlay created"
    fi

    if [[ -n "$SEMANTIC_COMPOSE_ARGS" ]]; then
        # shellcheck disable=SC2086
        datahub docker quickstart $SEMANTIC_COMPOSE_ARGS
    else
        datahub docker quickstart
    fi

    # ── Poll for GMS health ──
    go "Waiting for DataHub GMS to become healthy (up to 5 minutes)..."
    WAIT_SECS=300
    POLL_INTERVAL=5
    elapsed=0
    printf "    "
    while ! _gms_healthy; do
        if [[ $elapsed -ge $WAIT_SECS ]]; then
            echo ""
            die "DataHub GMS did not become healthy within ${WAIT_SECS}s. Check: docker ps"
        fi
        printf "."
        sleep "$POLL_INTERVAL"
        elapsed=$((elapsed + POLL_INTERVAL))
    done
    echo ""
    ok "DataHub GMS is healthy"
    _provision_local_token
fi

# ──────────────────────────────────────────────────────────────────────────────
# 4. Load sample data (idempotent)
# ──────────────────────────────────────────────────────────────────────────────
go "Checking if Olist sample data is already loaded..."

# Returns 0 only if ALL 7 expected tables exist AND at least one key table
# (orders) has rows — so empty or partial loads always re-trigger.
_sample_data_loaded() {
    uv run python -c "
import pymysql, sys
REQUIRED = {'olist_customers','olist_orders','olist_order_items','olist_order_payments','olist_order_reviews','olist_products','olist_sellers','product_category_name_translation'}
try:
    conn = pymysql.connect(
        host='localhost', port=3306,
        user='${MYSQL_USER}', password='${MYSQL_PASSWORD}',
        connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute(
        \"SELECT table_name FROM information_schema.tables WHERE table_schema='${MYSQL_DATABASE:-analytics_agent_demo}'\"
    )
    found = {row[0] for row in cur.fetchall()}
    if not REQUIRED.issubset(found):
        missing = REQUIRED - found
        print(f'Missing tables: {missing}', file=sys.stderr)
        conn.close(); sys.exit(1)
    cur.execute(\"SELECT COUNT(*) FROM \`${MYSQL_DATABASE:-analytics_agent_demo}\`.\`olist_orders\`\")
    row_count = cur.fetchone()[0]
    conn.close()
    if row_count == 0:
        print('orders table is empty', file=sys.stderr)
        sys.exit(1)
    print(f'Found {row_count:,} rows in orders — data already loaded')
    sys.exit(0)
except Exception as e:
    print(f'Check failed: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1
}

# NOTE: assignment inside `if` suppresses set -e for the subshell exit code,
# which is what we want — a non-zero exit means "not loaded yet", not a fatal error.
if _check_result=$(_sample_data_loaded); then
    ok "Olist sample data already loaded — ${_check_result}"
else
    [[ -n "${_check_result:-}" ]] && warn "${_check_result}"
    go "Loading Olist sample data into MySQL..."
    cd "$REPO_ROOT"
    uv run python scripts/load_sample_data.py \
        --user "$MYSQL_USER" \
        --password "$MYSQL_PASSWORD" \
        --database "${MYSQL_DATABASE:-analytics_agent_demo}" \
        --admin-user "$MYSQL_ADMIN_USER" \
        --admin-password "$MYSQL_ADMIN_PASSWORD"
    ok "Sample data loaded"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 5. Ingest metadata into DataHub
# ──────────────────────────────────────────────────────────────────────────────
go "Ingesting table metadata into DataHub..."
cd "$REPO_ROOT"
_ingest_args=(
    --gms-url "$DATAHUB_GMS_URL"
    --token "${DATAHUB_GMS_TOKEN:-}"
    --database "${MYSQL_DATABASE}"
    --mysql-user "$MYSQL_USER"
    --mysql-password "$MYSQL_PASSWORD"
)
uv run python scripts/ingest_metadata.py "${_ingest_args[@]}"
ok "Metadata ingested"

# ──────────────────────────────────────────────────────────────────────────────
# 6. Write .env.quickstart (Docker container env — does NOT touch your .env)
# ──────────────────────────────────────────────────────────────────────────────
# Inside Docker on macOS, host.docker.internal resolves to the host machine,
# so the container can reach the DataHub GMS and MySQL running on the host.
go "Writing .env.quickstart for Docker container..."
cd "$REPO_ROOT"

# Ensure the 'talkster' schema exists in MySQL (uses admin credentials)
go "Ensuring 'talkster' schema exists in MySQL..."
uv run python3 - <<PYEOF
import pymysql, sys
try:
    conn = pymysql.connect(host='localhost', port=3306,
                           user='${MYSQL_ADMIN_USER}', password='${MYSQL_ADMIN_PASSWORD}',
                           connect_timeout=5)
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS \`talkster\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute("GRANT ALL PRIVILEGES ON \`talkster\`.* TO '${MYSQL_USER}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    conn.close()
    print("talkster schema ready")
except Exception as e:
    print(f"Warning: could not create talkster schema: {e}", file=sys.stderr)
PYEOF
ok "'talkster' schema ready"

cat > .env.quickstart <<EOF
# Auto-generated by quickstart.sh — do not edit by hand.
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_GMS_TOKEN=${DATAHUB_GMS_TOKEN:-}
MYSQL_HOST=host.docker.internal
MYSQL_PORT=3306
MYSQL_USER=${MYSQL_USER}
MYSQL_PASSWORD=${MYSQL_PASSWORD}
MYSQL_DATABASE=${MYSQL_DATABASE}
DATABASE_URL=mysql+aiomysql://${MYSQL_USER}:${MYSQL_PASSWORD}@host.docker.internal:3306/talkster
# datahub_agent_context detects cloud vs OSS via frontend_base_url; the local
# acryl stack sets this, causing it to enable cloud-only ES fields that fail.
# Force OSS mode so GraphQL queries use the correct field set.
DISABLE_NEWER_GMS_FIELD_DETECTION=true
EOF

# Append LLM key if one was found in the environment — otherwise the wizard handles it
if [[ "$_LLM_KEY_SOURCE" == "anthropic" ]]; then
    printf '\nLLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=%s\n' "${ANTHROPIC_API_KEY}" >> .env.quickstart
elif [[ "$_LLM_KEY_SOURCE" == "openai" ]]; then
    printf '\nLLM_PROVIDER=openai\nOPENAI_API_KEY=%s\n' "${OPENAI_API_KEY}" >> .env.quickstart
elif [[ "$_LLM_KEY_SOURCE" == "google" ]]; then
    printf '\nLLM_PROVIDER=google\nGOOGLE_API_KEY=%s\n' "${GOOGLE_API_KEY}" >> .env.quickstart
elif [[ "$_LLM_KEY_SOURCE" == "bedrock" ]]; then
    {
        printf '\nLLM_PROVIDER=bedrock\n'
        printf 'AWS_REGION=%s\n' "${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
        [[ -n "${AWS_PROFILE:-}" ]] && printf 'AWS_PROFILE=%s\n' "$AWS_PROFILE"
    } >> .env.quickstart
fi

ok ".env.quickstart written (uses host.docker.internal — your .env is untouched)"

# ──────────────────────────────────────────────────────────────────────────────
# 7. Copy config.demo.yaml → config.yaml (baked into the Docker image)
# ──────────────────────────────────────────────────────────────────────────────
go "Copying config.demo.yaml → config.yaml..."
cp "${REPO_ROOT}/config.demo.yaml" "${REPO_ROOT}/config.yaml"
ok "config.yaml updated"

# ──────────────────────────────────────────────────────────────────────────────
# 8. Build Docker image (builds frontend + backend in one shot)
# ──────────────────────────────────────────────────────────────────────────────
go "Building talkster Docker image (this bakes in the frontend — may take ~2 min)..."
cd "$REPO_ROOT"
docker build -f docker/Dockerfile -t analytics-agent-quickstart . 1>&2
ok "Docker image built: analytics-agent-quickstart"

# ──────────────────────────────────────────────────────────────────────────────
# 9. Run talkster in Docker
# ──────────────────────────────────────────────────────────────────────────────
go "Starting talkster container..."
cd "$REPO_ROOT"

# Stop and remove any previous quickstart container
docker rm -f analytics-agent-quickstart 2>/dev/null && warn "Removed previous analytics-agent-quickstart container" || true

# Mount ~/.aws read-only when using Bedrock so boto3 can pick up profiles / SSO cache.
_AWS_MOUNT=()
if [[ "$_LLM_KEY_SOURCE" == "bedrock" ]]; then
    _AWS_MOUNT=(-v "$HOME/.aws:/root/.aws:ro")
fi

docker run -d \
    --name analytics-agent-quickstart \
    --env-file .env.quickstart \
    -v "${REPO_ROOT}/config.yaml:/app/config.yaml:ro" \
    ${_AWS_MOUNT:+"${_AWS_MOUNT[@]}"} \
    -p 8100:8100 \
    analytics-agent-quickstart

# Wait for talkster to respond
go "Waiting for talkster to start..."
WAIT_SECS=60
elapsed=0
printf "    "
until curl -sf --max-time 2 http://localhost:8100/ &>/dev/null; do
    if [[ $elapsed -ge $WAIT_SECS ]]; then
        echo ""
        die "Analytics Agent did not start within ${WAIT_SECS}s. Logs: docker logs analytics-agent-quickstart"
    fi
    printf "."
    sleep 2
    elapsed=$((elapsed + 2))
done
echo ""

# ──────────────────────────────────────────────────────────────────────────────
# Optional: configure DataHub via MCP server (opt-in, set DATAHUB_USE_MCP=true)
# Default is the native REST API pathway which requires no subprocess.
# ──────────────────────────────────────────────────────────────────────────────
if [[ "${DATAHUB_USE_MCP:-false}" == "true" ]]; then
    go "Configuring DataHub via MCP server (DATAHUB_USE_MCP=true)..."
    _MCP_PAYLOAD=$(cat <<EOF
{
  "name": "datahub",
  "type": "datahub-mcp",
  "label": "DataHub",
  "category": "context_platform",
  "config": {},
  "mcp_config": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-datahub@latest"],
    "env": {
      "DATAHUB_GMS_URL": "http://host.docker.internal:8080",
      "DATAHUB_GMS_TOKEN": "${DATAHUB_GMS_TOKEN:-}",
      "DISABLE_NEWER_GMS_FIELD_DETECTION": "true",
      "TOOLS_IS_MUTATION_ENABLED": "true"
    }
  }
}
EOF
)
    _MCP_RESULT=$(curl -sf -X POST http://localhost:8100/api/settings/connections \
        -H "Content-Type: application/json" \
        -d "$_MCP_PAYLOAD" 2>/dev/null || echo "failed")
    if echo "$_MCP_RESULT" | grep -q '"success":true'; then
        ok "DataHub MCP connection registered — tools will be discovered at next startup"
    else
        warn "MCP registration failed (${_MCP_RESULT}) — falling back to native DataHub"
    fi
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Analytics Agent is ready!                  ║${NC}"
echo -e "${BOLD}║  → http://localhost:8100             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
if [[ -z "$_LLM_KEY_SOURCE" ]]; then
    echo -e "${CYAN}  First time?${NC} Open http://localhost:8100 — a setup wizard"
    echo -e "  will walk you through picking a model and entering your API key."
    echo ""
fi
echo -e "  ${BOLD}DataHub UI:${NC}  http://localhost:9002  (datahub / datahub)"
echo ""
echo -e "  ${BOLD}Try asking:${NC}"
echo "    • Top 10 categories by revenue?"
echo "    • Monthly order volumes (chart)"
echo "    • States with best review scores?"
echo "    • Average delivery time by category"
echo "    • Sellers with most late deliveries"
echo ""
echo "  Stop:  docker stop analytics-agent-quickstart"
echo "  Logs:  docker logs -f analytics-agent-quickstart"
echo ""
