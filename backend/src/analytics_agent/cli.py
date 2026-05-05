"""Click CLI for analytics-agent — bootstrap and server operations."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

import click

from analytics_agent import bootstrap


@click.group()
@click.version_option(package_name="datahub-analytics-agent")
def cli() -> None:
    """Analytics-agent admin CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )


# ── Bootstrap commands (unchanged) ────────────────────────────────────────────


@cli.command("migrate")
def migrate() -> None:
    """Apply Alembic migrations to the configured database."""
    click.echo("→ Running database migrations…")
    bootstrap.run_migrations()
    click.echo("✓ Migrations complete.")


@cli.command("seed-integrations")
def seed_integrations() -> None:
    """Upsert config.yaml engines into the integrations table."""
    click.echo("→ Seeding integrations from config.yaml…")
    asyncio.run(bootstrap.seed_integrations_from_yaml())
    click.echo("✓ Integrations seeded.")


@cli.command("seed-context-platforms")
def seed_context_platforms() -> None:
    """Upsert config.yaml context platforms into the DB."""
    click.echo("→ Seeding context platforms from config.yaml…")
    asyncio.run(bootstrap.seed_context_platforms_from_yaml())
    click.echo("✓ Context platforms seeded.")


@cli.command("seed-defaults")
def seed_defaults() -> None:
    """Write first-run defaults to the settings table."""
    click.echo("→ Writing first-run default settings…")
    asyncio.run(bootstrap.seed_default_settings())
    click.echo("✓ Defaults written.")


@cli.command("bootstrap")
def bootstrap_cmd() -> None:
    """Run migrations + all seeds (idempotent). Intended for Helm hooks."""

    async def _run_all_seeds() -> None:
        await bootstrap.seed_integrations_from_yaml()
        await bootstrap.seed_context_platforms_from_yaml()
        await bootstrap.seed_default_settings()

    click.echo("→ Running migrations…")
    bootstrap.run_migrations()
    click.echo("→ Seeding integrations, context platforms, and defaults…")
    asyncio.run(_run_all_seeds())
    click.echo("✓ Bootstrap complete.")


# ── Quickstart / server lifecycle ─────────────────────────────────────────────


@cli.command("quickstart")
@click.option("--port", default=8100, show_default=True, help="Port to listen on.")
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Full demo: start DataHub, load Olist sample data, and launch the agent.",
)
@click.option(
    "--reconfigure",
    is_flag=True,
    default=False,
    help="Open the setup wizard in the browser to change model or API key.",
)
def quickstart(port: int, demo: bool, reconfigure: bool) -> None:
    """Configure and launch the agent. Re-run any time to restart."""
    if demo:
        from analytics_agent.quickstart import run_demo

        run_demo(port=port)
    else:
        from analytics_agent.quickstart import run_wizard

        run_wizard(port=port, reconfigure=reconfigure)


@cli.command("start")
@click.option("--port", default=8100, show_default=True, help="Port to listen on.")
def start(port: int) -> None:
    """Start the server from existing config (no wizard)."""
    from analytics_agent.config import get_config_dir
    from analytics_agent.quickstart import read_pid, start_server, wait_for_server

    if read_pid() is not None:
        click.echo("Server is already running. Use `analytics-agent status` for details.")
        sys.exit(1)

    config_dir = get_config_dir()
    env_path = config_dir / ".env"
    if not env_path.exists():
        click.echo(
            f"No config found at {config_dir}. Run `analytics-agent quickstart` first.",
            err=True,
        )
        sys.exit(1)

    click.echo("→ Starting server…")
    try:
        pid = start_server(port)
    except RuntimeError as e:
        click.echo(f"✗ {e}", err=True)
        sys.exit(1)
    if wait_for_server(port):
        click.echo(f"✓ Running at http://localhost:{port}  (PID {pid})")
    else:
        click.echo("✗ Server did not respond within 30s.", err=True)
        sys.exit(1)


@cli.command("stop")
def stop() -> None:
    """Stop the running server."""
    from analytics_agent.quickstart import stop_server

    if stop_server():
        click.echo("✓ Server stopped.")
    else:
        click.echo("No running server found.")


@cli.command("status")
def status() -> None:
    """Show whether the server is running and its URL."""
    from analytics_agent.quickstart import read_pid, read_port

    pid = read_pid()
    if pid:
        port = read_port()
        click.echo(f"✓ Running  (PID {pid})  →  http://localhost:{port}")
    else:
        click.echo("✗ Not running")


@cli.command("logs")
@click.option("-n", "--lines", default=50, show_default=True, help="Lines to show initially.")
def logs(lines: int) -> None:
    """Tail the agent log file."""
    from analytics_agent.quickstart import _log_file

    log_path = _log_file()
    if not log_path.exists():
        click.echo(f"Log file not found: {log_path}", err=True)
        sys.exit(1)

    try:
        subprocess.run(["tail", "-n", str(lines), "-f", str(log_path)])
    except KeyboardInterrupt:
        pass


@cli.command("config")
def config_cmd() -> None:
    """Open the config directory in $EDITOR or print its path."""
    from analytics_agent.config import get_config_dir

    config_dir = get_config_dir()
    editor = os.environ.get("EDITOR", "")
    if editor:
        subprocess.run([editor, str(config_dir)])
    else:
        click.echo(str(config_dir))


def _install_kind() -> str:
    """Return 'editable', 'uvx', or 'pip' to describe how the package is installed."""
    import json

    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("datahub-analytics-agent")
        raw = dist.read_text("direct_url.json")
        if raw:
            data = json.loads(raw)
            if data.get("dir_info", {}).get("editable"):
                return "editable"
    except Exception:
        pass

    # uvx tools land in a path like …/uv/tools/datahub-analytics-agent/…
    exe = sys.executable.replace("\\", "/")
    if "/uv/tools/" in exe:
        return "uvx"

    return "pip"


@cli.command("upgrade")
@click.option(
    "--to",
    "version",
    default=None,
    metavar="VERSION",
    help="Specific version to install, e.g. 0.2.1 (default: latest).",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def upgrade_cmd(version: str | None, yes: bool) -> None:
    """Upgrade analytics-agent to the latest (or a specific) version.

    Examples:

    \b
      analytics-agent upgrade             # → latest
      analytics-agent upgrade --to 0.2.1  # → pin to 0.2.1
    """
    import importlib.metadata

    kind = _install_kind()

    if kind == "editable":
        click.echo(
            "✗ This installation is running directly from a source checkout.\n"
            "  Use git to update instead:\n\n"
            "    git pull\n"
            "    uv sync\n"
            "    analytics-agent bootstrap   # if migrations changed",
            err=True,
        )
        sys.exit(1)

    if kind == "uvx":
        pkg = "datahub-analytics-agent"
        if version:
            pkg = f"datahub-analytics-agent=={version}"
        click.echo(
            "✗ This installation is managed by uvx.\n"
            "  Use uv to upgrade instead:\n\n"
            f"    uv tool upgrade {pkg}",
            err=True,
        )
        sys.exit(1)

    try:
        current = importlib.metadata.version("datahub-analytics-agent")
    except Exception:
        current = "unknown"

    pkg = f"datahub-analytics-agent=={version}" if version else "datahub-analytics-agent"
    label = f"v{version}" if version else "latest"

    click.echo(f"→ Installing {label}  (installed: {current})")

    if not yes:
        click.confirm("  Continue?", default=True, abort=True)

    from analytics_agent.quickstart import read_pid

    running_pid = read_pid()
    if running_pid:
        click.echo(
            f"  ⚠  Server is running (PID {running_pid}) — "
            "you will need to restart it after the upgrade."
        )

    click.echo("  → Running pip install…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
    )

    if result.returncode != 0:
        click.echo("✗ Installation failed.", err=True)
        sys.exit(result.returncode)

    # importlib.metadata caches metadata paths — invalidate so we can read the new version
    import importlib

    importlib.invalidate_caches()
    try:
        new_version = importlib.metadata.version("datahub-analytics-agent")
    except Exception:
        new_version = "unknown"

    if new_version != current:
        click.echo(f"✓ Upgraded  {current}  →  {new_version}")
    else:
        click.echo(f"✓ Already at {new_version} — nothing to do.")

    if running_pid:
        click.echo("\n  Restart to apply:")
        click.echo("    analytics-agent stop && analytics-agent start")


if __name__ == "__main__":
    cli()
