"""Click CLI for analytics-agent — bootstrap operations."""

from __future__ import annotations

import logging

import click


@click.group()
@click.version_option(package_name="datahub-analytics-agent")
def cli() -> None:
    """Analytics-agent admin CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
