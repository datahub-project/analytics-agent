"""Connector lifecycle API — install status + installation for native connector packages."""

from __future__ import annotations

import subprocess
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from analytics_agent.engines.factory import _CONNECTOR_MAP

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class ConnectorStatus(BaseModel):
    type: str
    package: str
    installed: bool


class InstallResult(BaseModel):
    ok: bool
    message: str


def _is_installed(package: str) -> bool:
    """Check if a connector package is installed via `uv tool install`."""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return package in result.stdout
    except Exception:
        return False


@router.get("/{connector_type}/status", response_model=ConnectorStatus)
async def get_connector_status(connector_type: str) -> ConnectorStatus:
    """Check whether a native connector package is installed."""
    spec = _CONNECTOR_MAP.get(connector_type)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown connector type: {connector_type!r}")

    return ConnectorStatus(
        type=connector_type,
        package=spec.package,
        installed=_is_installed(spec.package),
    )


@router.post("/{connector_type}/install", response_model=InstallResult)
async def install_connector(connector_type: str) -> InstallResult:
    """Install a native connector package via `uv tool install`.

    Idempotent — safe to call if already installed.
    """
    spec = _CONNECTOR_MAP.get(connector_type)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown connector type: {connector_type!r}")

    logger.info("Installing connector package: %s", spec.package)
    try:
        result = subprocess.run(
            ["uv", "tool", "install", spec.package],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Connector installation timed out after 120s.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="`uv` is not available in PATH.")

    if result.returncode != 0:
        logger.error("Connector install failed: %s", result.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"Installation failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    logger.info("Connector installed: %s", spec.package)
    return InstallResult(ok=True, message=f"{spec.package} installed successfully.")
