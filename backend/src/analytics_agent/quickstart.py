"""Quickstart wizard and server lifecycle management for analytics-agent."""

from __future__ import annotations

import getpass
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import click

from analytics_agent.config import get_config_dir

# ── Engine prompts ─────────────────────────────────────────────────────────────

# Each entry: list of (prompt_label, env_var_name, is_secret)
_ENGINE_FIELDS: dict[str, list[tuple[str, str, bool]]] = {
    "snowflake": [
        ("Account (e.g. xy12345.us-east-1)", "SNOWFLAKE_ACCOUNT", False),
        ("Warehouse", "SNOWFLAKE_WAREHOUSE", False),
        ("Database", "SNOWFLAKE_DATABASE", False),
        ("Schema", "SNOWFLAKE_SCHEMA", False),
        ("User", "SNOWFLAKE_USER", False),
        ("Password", "SNOWFLAKE_PASSWORD", True),
    ],
    "bigquery": [
        ("GCP Project ID", "BIGQUERY_PROJECT", False),
        ("Dataset", "BIGQUERY_DATASET", False),
        ("Path to service-account JSON key", "BIGQUERY_CREDENTIALS_FILE", False),
    ],
    "postgresql": [
        ("Host", "POSTGRES_HOST", False),
        ("Port", "POSTGRES_PORT", False),
        ("Database", "POSTGRES_DATABASE", False),
        ("User", "POSTGRES_USER", False),
        ("Password", "POSTGRES_PASSWORD", True),
    ],
    "mysql": [
        ("Host", "MYSQL_HOST", False),
        ("Port", "MYSQL_PORT", False),
        ("Database", "MYSQL_DATABASE", False),
        ("User", "MYSQL_USER", False),
        ("Password", "MYSQL_PASSWORD", True),
    ],
}

# config.yaml connection block template per engine type.
# Values reference ${ENV_VAR} substitution supported by analytics-agent.
_ENGINE_CONFIG_TEMPLATE: dict[str, dict[str, Any]] = {
    "snowflake": {
        "account": "${SNOWFLAKE_ACCOUNT}",
        "warehouse": "${SNOWFLAKE_WAREHOUSE}",
        "database": "${SNOWFLAKE_DATABASE}",
        "schema": "${SNOWFLAKE_SCHEMA}",
        "user": "${SNOWFLAKE_USER}",
        "password": "${SNOWFLAKE_PASSWORD}",
    },
    "bigquery": {
        "project": "${BIGQUERY_PROJECT}",
        "dataset": "${BIGQUERY_DATASET}",
        "credentials_file": "${BIGQUERY_CREDENTIALS_FILE}",
    },
    "postgresql": {
        "host": "${POSTGRES_HOST}",
        "port": "${POSTGRES_PORT}",
        "database": "${POSTGRES_DATABASE}",
        "user": "${POSTGRES_USER}",
        "password": "${POSTGRES_PASSWORD}",
    },
    "mysql": {
        "host": "${MYSQL_HOST}",
        "port": "${MYSQL_PORT}",
        "database": "${MYSQL_DATABASE}",
        "user": "${MYSQL_USER}",
        "password": "${MYSQL_PASSWORD}",
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────────


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    if secret:
        value = getpass.getpass(f"  {label}: ")
    else:
        if default:
            value = click.prompt(f"  {label}", default=default)
        else:
            value = click.prompt(f"  {label}")
    return value.strip()


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Merge updates into an existing .env file (or create it)."""
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(updates)
    lines = [f"{k}={v}" for k, v in existing.items()]
    path.write_text("\n".join(lines) + "\n")


def _write_config_yaml(path: Path, engine_type: str, engine_name: str) -> None:
    """Write (or merge) a config.yaml with one engine entry using ${VAR} refs."""
    import yaml

    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text()) or {}
        except Exception:
            pass

    engines: list[dict[str, Any]] = existing.get("engines", [])
    # Remove any existing entry with the same name to avoid duplicates
    engines = [e for e in engines if e.get("name") != engine_name]
    engines.append(
        {
            "type": engine_type,
            "name": engine_name,
            "connection": _ENGINE_CONFIG_TEMPLATE[engine_type],
        }
    )
    existing["engines"] = engines

    # Dump preserving existing context_platforms if present
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))


# ── PID / server management ────────────────────────────────────────────────────


def _pid_file() -> Path:
    return get_config_dir() / "agent.pid"


def _log_file() -> Path:
    return get_config_dir() / "logs" / "agent.log"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def read_pid() -> int | None:
    """Return the PID from the PID file, or None if absent/stale."""
    pf = _pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().split(":")[0].strip())
    except ValueError:
        return None
    if _is_running(pid):
        return pid
    # Stale — clean up
    pf.unlink(missing_ok=True)
    return None


def read_port() -> int:
    """Return the port from the PID file, defaulting to 8100."""
    pf = _pid_file()
    if not pf.exists():
        return 8100
    parts = pf.read_text().strip().split(":")
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 8100


def _port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def start_server(port: int = 8100) -> int:
    """Launch uvicorn in the background; return the PID."""
    if _port_in_use(port):
        raise RuntimeError(
            f"Port {port} is already in use. "
            "Stop the existing process or choose a different port with --port."
        )
    config_dir = get_config_dir()
    log_dir = config_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agent.log"

    env = os.environ.copy()
    env["ANALYTICS_AGENT_CONFIG_DIR"] = str(config_dir)

    with open(log_path, "a") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "analytics_agent.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
            ],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
            start_new_session=True,
        )

    _pid_file().write_text(f"{proc.pid}:{port}")
    return proc.pid


def stop_server() -> bool:
    """Send SIGTERM to the running server. Returns True if a process was killed."""
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _pid_file().unlink(missing_ok=True)
    return True


def wait_for_server(port: int = 8100, timeout: int = 30) -> bool:
    """Poll health endpoint until ready or timeout (seconds). Returns True on success."""
    import urllib.error
    import urllib.request

    url = f"http://localhost:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


# ── Wizard ─────────────────────────────────────────────────────────────────────


def run_wizard(port: int = 8100) -> None:
    """Interactive quickstart wizard — configures and launches the agent."""
    click.echo(
        textwrap.dedent("""
        ╔══════════════════════════════════════════╗
        ║   DataHub Analytics Agent — Quickstart   ║
        ╚══════════════════════════════════════════╝
        """).strip()
    )

    # ── Prerequisites ──────────────────────────────────────────────────────
    click.echo("\n→ Checking prerequisites…")
    _check_prereqs(port)

    config_dir = get_config_dir()

    # ── Idempotency: existing config? ──────────────────────────────────────
    env_path = config_dir / ".env"
    if env_path.exists():
        click.echo(f"\n  Existing config found at {config_dir}/")
        choice = click.prompt(
            "  What would you like to do?",
            type=click.Choice(["start", "reconfigure", "cancel"], case_sensitive=False),
            default="start",
        )
        if choice == "cancel":
            click.echo("  Cancelled.")
            return
        if choice == "start":
            _bootstrap_and_launch(config_dir, port)
            return
        # reconfigure → fall through to wizard

    # ── Step 1: LLM provider ───────────────────────────────────────────────
    click.echo("\nStep 1 — LLM provider")
    provider = click.prompt(
        "  Which provider?",
        type=click.Choice(["anthropic", "openai", "google", "bedrock"], case_sensitive=False),
        default="anthropic",
    )

    # ── Step 2: API key ────────────────────────────────────────────────────
    click.echo("\nStep 2 — API key")
    env_updates: dict[str, str] = {"LLM_PROVIDER": provider}
    if provider == "anthropic":
        key = getpass.getpass("  Anthropic API key (sk-ant-…): ").strip()
        env_updates["ANTHROPIC_API_KEY"] = key
    elif provider == "openai":
        key = getpass.getpass("  OpenAI API key (sk-…): ").strip()
        env_updates["OPENAI_API_KEY"] = key
    elif provider == "google":
        key = getpass.getpass("  Google API key: ").strip()
        env_updates["GOOGLE_API_KEY"] = key
    elif provider == "bedrock":
        env_updates["AWS_REGION"] = _prompt("AWS region", default="us-west-2")
        env_updates["AWS_ACCESS_KEY_ID"] = _prompt("AWS Access Key ID")
        env_updates["AWS_SECRET_ACCESS_KEY"] = getpass.getpass("  AWS Secret Access Key: ").strip()

    # ── Step 3: Data source (optional) ────────────────────────────────────
    click.echo("\nStep 3 — Data source  (you can add more later in Settings)")
    engine_choices = ["snowflake", "bigquery", "postgresql", "mysql", "skip"]
    engine_type = click.prompt(
        "  Connect a data source?",
        type=click.Choice(engine_choices, case_sensitive=False),
        default="skip",
    )

    engine_name: str | None = None
    if engine_type != "skip":
        engine_name = _prompt(f"  Name for this {engine_type} connection", default=engine_type)
        click.echo(f"\n  Enter connection details for {engine_type}:")
        for label, env_var, is_secret in _ENGINE_FIELDS[engine_type]:
            env_updates[env_var] = _prompt(label, secret=is_secret)

    # ── Step 4: Write config and launch ───────────────────────────────────
    click.echo("\nStep 4 — Done")
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "data").mkdir(parents=True, exist_ok=True)

    _write_env(env_path, env_updates)
    click.echo(f"  ✓ Config written to {config_dir}/")

    if engine_type != "skip" and engine_name:
        yaml_path = config_dir / "config.yaml"
        _write_config_yaml(yaml_path, engine_type, engine_name)

    _bootstrap_and_launch(config_dir, port)


def _check_prereqs(port: int) -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        click.echo(f"  ✗ Python 3.11+ required (found {major}.{minor})", err=True)
        sys.exit(1)
    click.echo(f"  ✓ Python {major}.{minor}")

    if _port_in_use(port):
        click.echo(f"  ✗ Port {port} is already in use", err=True)
        sys.exit(1)
    click.echo(f"  ✓ Port {port} available")


def _bootstrap_and_launch(config_dir: Path, port: int) -> None:
    """Run bootstrap (migrations + seeds) then start the server."""
    import subprocess as _sp

    env = os.environ.copy()
    env["ANALYTICS_AGENT_CONFIG_DIR"] = str(config_dir)

    # Load config-dir .env into the bootstrap subprocess environment
    env_path = config_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()

    result = _sp.run(
        [sys.executable, "-m", "analytics_agent.cli", "bootstrap"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        sys.exit(result.returncode)
    click.echo("  ✓ Database initialised")

    click.echo("  → Starting server…")
    # Re-export env vars into current process so start_server picks them up
    os.environ.update(env)
    try:
        pid = start_server(port)
    except RuntimeError as e:
        click.echo(f"  ✗ {e}", err=True)
        sys.exit(1)

    if wait_for_server(port):
        click.echo(f"  ✓ Running at http://localhost:{port}  (PID {pid})")
        click.echo(f"  → Logs: {_log_file()}")
        try:
            import webbrowser

            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            pass
    else:
        click.echo(
            f"  ✗ Server did not respond within 30s — check logs: {_log_file()}",
            err=True,
        )
        sys.exit(1)


# ── Demo mode (full DataHub + Olist sample data) ───────────────────────────────

# On Linux, host.docker.internal doesn't resolve — use Docker's default bridge gateway.
_HOST_INTERNAL = "host.docker.internal" if sys.platform == "darwin" else "172.17.0.1"

_GMS_URL = "http://localhost:8080"
_DEMO_MYSQL_HOST = "localhost"
_DEMO_MYSQL_PORT = 3306
_DEMO_MYSQL_USER = "datahub"
_DEMO_MYSQL_PASS = "datahub"
_DEMO_MYSQL_DB = "analytics_agent_demo"


def _check_demo_prereqs() -> None:
    """Check Docker and datahub CLI are installed."""
    import shutil

    missing = []
    for cmd in ("docker", "datahub"):
        if not shutil.which(cmd):
            missing.append(cmd)
    if missing:
        click.echo(
            f"  ✗ Missing prerequisites: {', '.join(missing)}\n"
            "    • Docker: https://www.docker.com/products/docker-desktop\n"
            "    • DataHub CLI: pip install acryl-datahub",
            err=True,
        )
        sys.exit(1)
    click.echo("  ✓ Docker and datahub CLI found")


def _gms_healthy(url: str = _GMS_URL) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/health", timeout=3):
            return True
    except Exception:
        return False


def _start_datahub() -> None:
    """Start DataHub via `datahub docker quickstart` if not already running."""
    if _gms_healthy():
        click.echo("  ✓ DataHub GMS already running")
        return

    click.echo("  → Starting DataHub (this takes ~3-5 min on first run)…")
    result = subprocess.run(["datahub", "docker", "quickstart"], check=False)
    if result.returncode != 0:
        click.echo("  ✗ DataHub quickstart failed.", err=True)
        sys.exit(1)

    click.echo("  → Waiting for DataHub GMS to be healthy…")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if _gms_healthy():
            click.echo("  ✓ DataHub GMS is healthy")
            return
        time.sleep(5)
    click.echo("  ✗ DataHub GMS did not become healthy within 5 minutes.", err=True)
    sys.exit(1)


def _provision_datahub_token() -> str:
    """Mint a local DataHub token via `datahub init`; return the token."""
    import tempfile

    import yaml  # already a dep via pyyaml

    tmp = tempfile.mkdtemp()
    env = os.environ.copy()
    env["HOME"] = tmp
    subprocess.run(
        [
            "datahub",
            "init",
            "--username",
            "datahub",
            "--password",
            "datahub",
            "--force",
            "--host",
            _GMS_URL,
        ],
        env=env,
        capture_output=True,
    )
    try:
        cfg = yaml.safe_load((Path(tmp) / ".datahubenv").read_text())
        return (cfg.get("gms") or {}).get("token", "")
    except Exception:
        return ""


def _load_olist_data() -> None:
    """Run load_sample_data.py from the bundled demo package."""
    from analytics_agent.demo import load_sample_data  # noqa: F401

    demo_script = Path(__file__).parent / "demo" / "load_sample_data.py"
    result = subprocess.run(
        [
            sys.executable,
            str(demo_script),
            "--user",
            _DEMO_MYSQL_USER,
            "--password",
            _DEMO_MYSQL_PASS,
            "--database",
            _DEMO_MYSQL_DB,
            "--admin-user",
            "root",
            "--admin-password",
            _DEMO_MYSQL_PASS,
        ],
        check=False,
    )
    if result.returncode != 0:
        click.echo("  ✗ Olist data loading failed.", err=True)
        sys.exit(1)
    click.echo("  ✓ Olist sample data loaded")


def _ingest_metadata(gms_token: str) -> None:
    """Run ingest_metadata.py from the bundled demo package."""
    demo_script = Path(__file__).parent / "demo" / "ingest_metadata.py"
    # DataHub's ingestion executor runs inside Docker — pass the host-internal
    # address so it can reach the host MySQL (not Docker's own localhost).
    result = subprocess.run(
        [
            sys.executable,
            str(demo_script),
            "--gms-url",
            _GMS_URL,
            "--token",
            gms_token,
            "--database",
            _DEMO_MYSQL_DB,
            "--mysql-host-port",
            f"{_HOST_INTERNAL}:{_DEMO_MYSQL_PORT}",
            "--mysql-user",
            _DEMO_MYSQL_USER,
            "--mysql-password",
            _DEMO_MYSQL_PASS,
        ],
        check=False,
    )
    if result.returncode != 0:
        click.echo("  ✗ Metadata ingestion failed.", err=True)
        sys.exit(1)
    click.echo("  ✓ Olist metadata ingested into DataHub")


def _write_demo_config(config_dir: Path, gms_token: str, llm_env: dict[str, str]) -> None:
    """Write .env and config.yaml for the demo (DataHub + Olist MySQL)."""
    import shutil

    # .env
    env_updates: dict[str, str] = {
        "DATAHUB_GMS_URL": f"http://{_HOST_INTERNAL}:8080",
        "DATAHUB_GMS_TOKEN": gms_token,
        "DATABASE_URL": (
            f"mysql+aiomysql://{_DEMO_MYSQL_USER}:{_DEMO_MYSQL_PASS}"
            f"@{_HOST_INTERNAL}:{_DEMO_MYSQL_PORT}/talkster"
        ),
        "DISABLE_NEWER_GMS_FIELD_DETECTION": "true",
    }
    env_updates.update(llm_env)
    _write_env(config_dir / ".env", env_updates)

    # config.yaml — copy from bundled template
    src = Path(__file__).parent / "demo" / "config.demo.yaml"
    dest = config_dir / "config.yaml"
    shutil.copy(src, dest)
    # Patch host references in the copied config
    text = dest.read_text()
    text = text.replace("${MYSQL_HOST}", _HOST_INTERNAL)
    dest.write_text(text)

    click.echo(f"  ✓ Demo config written to {config_dir}/")


def run_demo(port: int = 8100) -> None:
    """Full demo: DataHub quickstart + Olist data + analytics agent."""
    click.echo(
        textwrap.dedent("""
        ╔══════════════════════════════════════════╗
        ║   DataHub Analytics Agent — Demo         ║
        ╚══════════════════════════════════════════╝
        """).strip()
    )
    click.echo("\n→ Checking prerequisites…")
    _check_demo_prereqs()
    _check_prereqs(port)

    # LLM key
    click.echo("\nStep 1 — LLM provider")
    provider = click.prompt(
        "  Which provider?",
        type=click.Choice(["anthropic", "openai", "google", "bedrock"], case_sensitive=False),
        default="anthropic",
    )
    llm_env: dict[str, str] = {"LLM_PROVIDER": provider}
    click.echo("\nStep 2 — API key")
    if provider == "anthropic":
        llm_env["ANTHROPIC_API_KEY"] = getpass.getpass("  Anthropic API key (sk-ant-…): ").strip()
    elif provider == "openai":
        llm_env["OPENAI_API_KEY"] = getpass.getpass("  OpenAI API key (sk-…): ").strip()
    elif provider == "google":
        llm_env["GOOGLE_API_KEY"] = getpass.getpass("  Google API key: ").strip()
    elif provider == "bedrock":
        llm_env["AWS_REGION"] = _prompt("AWS region", default="us-west-2")
        llm_env["AWS_ACCESS_KEY_ID"] = _prompt("AWS Access Key ID")
        llm_env["AWS_SECRET_ACCESS_KEY"] = getpass.getpass("  AWS Secret Access Key: ").strip()

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "data").mkdir(parents=True, exist_ok=True)

    click.echo("\n→ Starting DataHub…")
    _start_datahub()

    click.echo("\n→ Loading Olist sample data…")
    _load_olist_data()

    click.echo("\n→ Ingesting metadata into DataHub…")
    gms_token = _provision_datahub_token()
    _ingest_metadata(gms_token)

    click.echo("\n→ Writing demo config…")
    _write_demo_config(config_dir, gms_token, llm_env)

    click.echo("\n→ Bootstrapping database…")
    _bootstrap_and_launch(config_dir, port)
