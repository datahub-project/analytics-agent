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


class TestConnectionBody(BaseModel):
    config: dict
    secrets: dict = {}


class TestConnectionResult(BaseModel):
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


@router.post("/{connector_type}/test", response_model=TestConnectionResult)
async def test_connector(connector_type: str, body: TestConnectionBody) -> TestConnectionResult:
    """Ephemeral connection test — instantiates the engine from the supplied config
    without saving anything, calls list_tables, and returns the result.

    Secrets (e.g. credentials_json) are passed in body.secrets under the
    friendly key name and overlaid onto body.config before building the engine.
    """
    spec = _CONNECTOR_MAP.get(connector_type)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown connector type: {connector_type!r}")

    from analytics_agent.engines.factory import _engine_cls
    import orjson

    # Merge secrets into the config using the env_map to translate friendly keys
    merged = dict(body.config)
    for friendly_key, value in body.secrets.items():
        if value:
            merged[friendly_key] = value

    try:
        factory_fn = _engine_cls(connector_type)
        if not factory_fn:
            return TestConnectionResult(ok=False, message=f"Unknown engine type: {connector_type}")

        engine = factory_fn(merged)
        tools = await engine.get_tools_async() if hasattr(engine, "get_tools_async") else engine.get_tools()
        list_tables = next((t for t in tools if t.name == "list_tables"), None)
        if list_tables:
            result = await list_tables.ainvoke({"schema": ""})
            # MCP tools return a list of content blocks: [{"type":"text","text":"..."}]
            # Unwrap to get the actual JSON string.
            if isinstance(result, list) and result and isinstance(result[0], dict):
                result = result[0].get("text", "")
            tables = orjson.loads(result) if isinstance(result, str) else result
            if isinstance(tables, list):
                return TestConnectionResult(ok=True, message=f"Connected — {len(tables)} tables accessible")
            if isinstance(tables, dict) and "error" in tables:
                return TestConnectionResult(ok=False, message=tables["error"])
        return TestConnectionResult(ok=True, message="Connected")
    except Exception as e:
        return TestConnectionResult(ok=False, message=str(e))
    finally:
        try:
            if "engine" in dir():
                await engine.aclose()
        except Exception:
            pass
