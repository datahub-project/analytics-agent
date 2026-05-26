"""Unit tests for MCPQueryEngine._build_conn transport routing."""

from __future__ import annotations

from analytics_agent.engines.mcp.engine import MCPQueryEngine


def _engine(cfg: dict) -> MCPQueryEngine:
    return MCPQueryEngine.__new__(MCPQueryEngine, _mcp_cfg=cfg)


def _make(cfg: dict) -> MCPQueryEngine:
    eng = object.__new__(MCPQueryEngine)
    eng._mcp_cfg = cfg
    return eng


def test_build_conn_streamable_http() -> None:
    eng = _make(
        {
            "transport": "streamable_http",
            "url": "https://mcp.example.com/mcp",
            "headers": {"Auth": "x"},
        }
    )
    conn = eng._build_conn()
    assert conn["transport"] == "http"
    assert conn["url"] == "https://mcp.example.com/mcp"
    assert conn["headers"] == {"Auth": "x"}


def test_build_conn_http_alias() -> None:
    eng = _make({"transport": "http", "url": "https://mcp.example.com/mcp"})
    conn = eng._build_conn()
    assert conn["transport"] == "http"


def test_build_conn_streamable_alias() -> None:
    """Cursor/Claude Desktop use "type": "streamable" — must route to http."""
    eng = _make({"transport": "streamable", "url": "https://mcp.example.com/mcp"})
    conn = eng._build_conn()
    assert conn["transport"] == "http"


def test_build_conn_type_key_fallback() -> None:
    """If "transport" is absent, fall back to "type" key."""
    eng = _make({"type": "streamable", "url": "https://mcp.example.com/mcp"})
    conn = eng._build_conn()
    assert conn["transport"] == "http"


def test_build_conn_sse() -> None:
    eng = _make({"transport": "sse", "url": "https://mcp.example.com/sse"})
    conn = eng._build_conn()
    assert conn["transport"] == "sse"
    assert conn["url"] == "https://mcp.example.com/sse"


def test_build_conn_stdio() -> None:
    eng = _make({"transport": "stdio", "command": "npx", "args": ["-y", "pkg"], "env": {"K": "v"}})
    conn = eng._build_conn()
    assert conn["transport"] == "stdio"
    assert conn["command"] == "npx"
    assert conn["args"] == ["-y", "pkg"]


def test_build_conn_default_is_sse() -> None:
    """No transport key → defaults to SSE (preserves existing behaviour)."""
    eng = _make({"url": "https://mcp.example.com/sse"})
    conn = eng._build_conn()
    assert conn["transport"] == "sse"
