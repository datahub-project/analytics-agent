#!/usr/bin/env python3
"""Minimal MCP server for transport integration tests.

Exposes two tools — echo and add — over stdio, SSE, or Streamable HTTP.

Usage:
    python echo_mcp_server.py --transport stdio
    python echo_mcp_server.py --transport sse --port 9100
    python echo_mcp_server.py --transport streamable-http --port 9100
"""

import argparse
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-test-server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text back unchanged."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        import uvicorn

        uvicorn.run(
            mcp.sse_app(),
            host="127.0.0.1",
            port=args.port,
            log_level="error",
        )
    elif args.transport == "streamable-http":
        import uvicorn

        uvicorn.run(
            mcp.streamable_http_app(),
            host="127.0.0.1",
            port=args.port,
            log_level="error",
        )
    else:
        sys.exit(f"Unknown transport: {args.transport}")
