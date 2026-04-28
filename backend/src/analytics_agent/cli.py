"""Click CLI for analytics-agent — bootstrap operations."""

from __future__ import annotations

import asyncio
import logging

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
    click.echo("→ Running migrations…")
    bootstrap.run_migrations()
    click.echo("→ Seeding integrations…")
    asyncio.run(bootstrap.seed_integrations_from_yaml())
    click.echo("→ Seeding context platforms…")
    asyncio.run(bootstrap.seed_context_platforms_from_yaml())
    click.echo("→ Writing first-run defaults…")
    asyncio.run(bootstrap.seed_default_settings())
    click.echo("✓ Bootstrap complete.")
