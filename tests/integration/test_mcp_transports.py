"""End-to-end transport tests for MCPQueryEngine.

Each test starts the echo_mcp_server fixture (two tools: echo, add) via the
transport under test, then exercises the full MCPQueryEngine.get_tools_async()
path and invokes one tool to verify the round-trip.

Run with:
    uv run pytest tests/integration/test_mcp_transports.py -v -s
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from analytics_agent.engines.mcp.engine import MCPQueryEngine

ECHO_SERVER = Path(__file__).parent.parent / "fixtures" / "echo_mcp_server.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(host: str, port: int, timeout: float = 10.0) -> None:
    """Poll until a TCP connection to host:port succeeds or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Port {port} on {host} did not open within {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sse_server():
    """Start echo_mcp_server in SSE mode; yield base URL; terminate on teardown."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ECHO_SERVER), "--transport", "sse", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port("127.0.0.1", port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture()
def streamable_http_server():
    """Start echo_mcp_server in streamable-http mode; yield base URL; terminate on teardown."""
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ECHO_SERVER),
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port("127.0.0.1", port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------


def _tool_by_name(tools, name: str):
    matches = [t for t in tools if t.name == name]
    assert matches, f"Tool '{name}' not found in {[t.name for t in tools]}"
    return matches[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_discovers_tools_and_invokes_echo():
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(ECHO_SERVER), "--transport", "stdio"],
            }
        }
    )
    tools = await engine.get_tools_async()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"echo", "add"}

    echo_tool = _tool_by_name(tools, "echo")
    result = await echo_tool.ainvoke({"text": "hello"})
    assert "hello" in str(result)


@pytest.mark.asyncio
async def test_stdio_add_tool():
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(ECHO_SERVER), "--transport", "stdio"],
            }
        }
    )
    tools = await engine.get_tools_async()
    add_tool = _tool_by_name(tools, "add")
    result = await add_tool.ainvoke({"a": 3, "b": 4})
    assert "7" in str(result)


@pytest.mark.asyncio
async def test_sse_discovers_tools_and_invokes_echo(sse_server: str):
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "transport": "sse",
                "url": f"{sse_server}/sse",
            }
        }
    )
    tools = await engine.get_tools_async()
    assert {t.name for t in tools} == {"echo", "add"}

    echo_tool = _tool_by_name(tools, "echo")
    result = await echo_tool.ainvoke({"text": "sse-works"})
    assert "sse-works" in str(result)


@pytest.mark.asyncio
async def test_streamable_http_discovers_tools_and_invokes_echo(streamable_http_server: str):
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "transport": "streamable_http",
                "url": f"{streamable_http_server}/mcp",
            }
        }
    )
    tools = await engine.get_tools_async()
    assert {t.name for t in tools} == {"echo", "add"}

    echo_tool = _tool_by_name(tools, "echo")
    result = await echo_tool.ainvoke({"text": "streamable-http-works"})
    assert "streamable-http-works" in str(result)


@pytest.mark.asyncio
async def test_streamable_http_via_http_alias(streamable_http_server: str):
    """The 'http' alias (what _build_conn outputs) must also work end-to-end."""
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "transport": "streamable_http",
                "url": f"{streamable_http_server}/mcp",
            }
        }
    )
    # Force _build_conn to emit "http" transport alias by reading internal dict
    conn = engine._build_conn()
    assert conn["transport"] == "http"  # verify our normalization is still in effect

    tools = await engine.get_tools_async()
    assert len(tools) == 2


@pytest.mark.asyncio
async def test_streamable_cursor_type_key(streamable_http_server: str):
    """Config using 'type': 'streamable' (Cursor/Claude Desktop format) must work."""
    engine = MCPQueryEngine(
        {
            "_mcp": {
                "type": "streamable",
                "url": f"{streamable_http_server}/mcp",
            }
        }
    )
    tools = await engine.get_tools_async()
    assert {t.name for t in tools} == {"echo", "add"}
