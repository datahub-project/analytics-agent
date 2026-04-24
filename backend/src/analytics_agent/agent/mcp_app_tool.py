"""Side-channel for MCP App tool results.

Mirrors the _pending_charts pattern in chart_tool.py:
- The wrapped tool returns a short marker string (MCP_APP_READY:<app_id>).
- The actual structured payload lives here, keyed by app_id.
- streaming.py pops from this dict when it sees the marker in on_tool_end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingApp:
    app_id: str
    connection_key: str
    server_name: str
    tool_name: str
    tool_input: dict
    # Structured CallToolResult content (list of content blocks), preserved so
    # the frontend can forward it verbatim as `ui/notifications/tool-result`
    # params per the MCP Apps spec.
    tool_result: Any
    resource_uri: str
    csp: str | None = None
    permissions: list[str] = field(default_factory=list)
    # Tool names scoped to this app's connection that the iframe is allowed to
    # call via the Phase 2 tool-proxy endpoint. Populated at wrap time from the
    # full tool list for the originating connection_key. Persisted in the MCP_APP
    # SSE payload so the endpoint can rehydrate it from the DB row.
    allowed_tools: list[str] = field(default_factory=list)


# Keyed by app_id; popped once streaming.py emits the MCP_APP SSE event.
_pending_apps: dict[str, PendingApp] = {}
