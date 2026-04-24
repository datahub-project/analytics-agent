from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import orjson

_CHART_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\"chart_schema\"\s*:.*?\})\s*```",
    re.DOTALL,
)


def _extract_chart_from_text(text: str) -> dict | None:
    """Extract a Vega-Lite chart spec if the model output it as a JSON code block."""
    match = _CHART_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        data = orjson.loads(match.group(1))
        schema = data.get("chart_schema", {})
        if not schema:
            return None
        return {
            "vega_lite_spec": schema,
            "reasoning": data.get("reasoning", ""),
            "chart_type": data.get("chart_type", ""),
        }
    except Exception:
        return None


def _strip_chart_json_blocks(text: str) -> str:
    return _CHART_BLOCK_RE.sub("", text).strip()


def to_sse(data: dict) -> str:
    return f"data: {orjson.dumps(data).decode()}\n\n"


async def stream_graph_events(
    graph,
    user_text: str,
    conversation_id: str,
    engine_name: str,
    keepalive_interval: int = 15,
    history: list | None = None,
) -> AsyncIterator[dict]:
    """
    Yield event dicts from the LangGraph graph.
    Callers convert to SSE strings via to_sse().
    history: reconstructed LangChain messages for prior turns (from history.py)
    """
    messages = history if history else [{"role": "user", "content": user_text}]
    inputs: dict[str, Any] = {
        "messages": messages,
        "last_sql_result": None,
        "pending_chart": None,
        "conversation_id": conversation_id,
        "engine_name": engine_name,
        "user_question": user_text,
    }

    pending_sql: dict[str, str] = {}
    final_text_parts: list[str] = []
    final_state: dict[str, Any] = {}
    chart_emitted = False  # guard against double-emitting CHART
    # Once report_proposal_results emits, the PROPOSAL_RESULTS card IS the summary
    # for the remainder of the turn — suppress any trailing model text so the user
    # doesn't see the card AND a redundant narrative explanation underneath.
    suppress_trailing_text = False

    # Track active tool runs by run_id -> tool_name so we can detect when a
    # wrapped tool (e.g. MCP UI wrapper) invokes an inner tool of the same name.
    # LangGraph v2 fires on_tool_start/on_tool_end for both the outer StructuredTool
    # and the inner delegated tool, which would otherwise double-record TOOL_CALL
    # and emit a redundant TOOL_RESULT alongside the MCP_APP bubble.
    active_tool_runs: dict[str, str] = {}
    suppressed_tool_runs: set[str] = set()

    try:
        from analytics_agent.config import settings as _settings

        async for event in graph.astream_events(
            inputs, version="v2", config={"recursion_limit": _settings.agent_recursion_limit}
        ):
            event_type: str = event.get("event", "")
            data: dict[str, Any] = event.get("data", {})
            name: str = event.get("name", "")
            run_id: str = event.get("run_id", "")
            parent_ids: list[str] = event.get("parent_ids", []) or []
            node: str = event.get("metadata", {}).get("langgraph_node", "")

            # ── TEXT ──
            if event_type == "on_chat_model_stream" and node not in ("chart", ""):
                if suppress_trailing_text:
                    continue
                chunk = data.get("chunk")
                if chunk is None:
                    continue
                if getattr(chunk, "tool_call_chunks", None):
                    continue
                content = chunk.content if hasattr(chunk, "content") else ""
                # Each chunk gets its own unique message_id. All other event
                # types already do this (uuid4). Sharing run_id across chunks
                # collides on the Message.id primary key in persistence and
                # silently drops every chunk after the first (see chat.py).
                if isinstance(content, str) and content:
                    final_text_parts.append(content)
                    yield {
                        "event": "TEXT",
                        "conversation_id": conversation_id,
                        "message_id": str(uuid.uuid4()),
                        "payload": {"text": content},
                    }
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                final_text_parts.append(text)
                                yield {
                                    "event": "TEXT",
                                    "conversation_id": conversation_id,
                                    "message_id": str(uuid.uuid4()),
                                    "payload": {"text": text},
                                }

            # ── TOOL_CALL ──
            elif event_type == "on_tool_start":
                tool_input = data.get("input", {})
                # Suppress inner tool calls nested under a same-named outer tool
                # (MCP UI wrapper pattern) so the bubble/history isn't duplicated.
                if any(active_tool_runs.get(pid) == name for pid in parent_ids):
                    suppressed_tool_runs.add(run_id)
                    continue
                active_tool_runs[run_id] = name
                if name == "execute_sql":
                    pending_sql[run_id] = tool_input.get("sql", "")
                # create_chart / present_proposals / report_proposal_results render as dedicated events — no tool call bubble
                if name in ("create_chart", "present_proposals", "report_proposal_results"):
                    continue
                yield {
                    "event": "TOOL_CALL",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": {"tool_name": name, "tool_input": tool_input},
                }

            # ── TOOL_ERROR (unhandled exception from tool) ──
            elif event_type == "on_tool_error":
                if run_id in suppressed_tool_runs:
                    suppressed_tool_runs.discard(run_id)
                    active_tool_runs.pop(run_id, None)
                    pending_sql.pop(run_id, None)
                    continue
                error_msg = str(data.get("error", "Tool failed"))
                yield {
                    "event": "TOOL_RESULT",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": {
                        "tool_name": name,
                        "result": error_msg,
                        "is_error": True,
                    },
                }
                pending_sql.pop(run_id, None)
                active_tool_runs.pop(run_id, None)

            # ── SQL / TOOL_RESULT / CHART ──
            elif event_type == "on_tool_end":
                if run_id in suppressed_tool_runs:
                    suppressed_tool_runs.discard(run_id)
                    active_tool_runs.pop(run_id, None)
                    pending_sql.pop(run_id, None)
                    continue
                active_tool_runs.pop(run_id, None)
                output = data.get("output", "")
                if hasattr(output, "content"):
                    output = output.content
                output_str = output if isinstance(output, str) else orjson.dumps(output).decode()

                if name == "execute_sql":
                    sql_text = pending_sql.pop(run_id, "")
                    try:
                        result = orjson.loads(output_str)
                        if "error" in result:
                            yield {
                                "event": "TOOL_RESULT",
                                "conversation_id": conversation_id,
                                "message_id": str(uuid.uuid4()),
                                "payload": {
                                    "tool_name": name,
                                    "result": result["error"],
                                    "is_error": True,
                                },
                            }
                        else:
                            yield {
                                "event": "SQL",
                                "conversation_id": conversation_id,
                                "message_id": str(uuid.uuid4()),
                                "payload": {
                                    "sql": sql_text,
                                    "columns": result.get("columns", []),
                                    "rows": result.get("rows", []),
                                    "truncated": result.get("truncated", False),
                                },
                            }
                    except Exception:
                        yield {
                            "event": "TOOL_RESULT",
                            "conversation_id": conversation_id,
                            "message_id": str(uuid.uuid4()),
                            "payload": {
                                "tool_name": name,
                                "result": output_str[:2000],
                                "is_error": True,
                            },
                        }
                elif output_str.startswith("MCP_APP_READY:"):
                    # Pop the PendingApp from the side-channel and emit an MCP_APP event.
                    # HTML is never included in the SSE payload — the frontend fetches
                    # it via GET .../mcp-app/{message_id}/ui (prefetch warms the cache).
                    app_id = output_str.split(":", 1)[1].split()[0].strip()
                    from analytics_agent.agent.mcp_app_tool import _pending_apps

                    pending_app = _pending_apps.pop(app_id, None)
                    if pending_app:
                        yield {
                            "event": "MCP_APP",
                            "conversation_id": conversation_id,
                            "message_id": str(uuid.uuid4()),
                            "payload": {
                                "app_id": app_id,
                                "connection_key": pending_app.connection_key,
                                "server_name": pending_app.server_name,
                                "tool_name": pending_app.tool_name,
                                "tool_input": pending_app.tool_input,
                                "tool_result": pending_app.tool_result,
                                "resource_uri": pending_app.resource_uri,
                                "csp": pending_app.csp,
                                "permissions": pending_app.permissions,
                                "allowed_tools": pending_app.allowed_tools,
                            },
                        }
                elif output_str.startswith("PROPOSALS_READY:"):
                    prop_id = output_str.split(":", 1)[1].split()[0].strip()
                    from analytics_agent.agent.proposals_tool import _pending_proposals

                    pending = _pending_proposals.pop(prop_id, None)
                    if pending:
                        yield {
                            "event": "PROPOSALS",
                            "conversation_id": conversation_id,
                            "message_id": str(uuid.uuid4()),
                            "payload": pending,
                        }
                elif output_str.startswith("RESULTS_READY:"):
                    result_id = output_str.split(":", 1)[1].split()[0].strip()
                    from analytics_agent.agent.results_tool import _pending_results

                    pending_result = _pending_results.pop(result_id, None)
                    if pending_result:
                        yield {
                            "event": "PROPOSAL_RESULTS",
                            "conversation_id": conversation_id,
                            "message_id": str(uuid.uuid4()),
                            "payload": pending_result,
                        }
                        suppress_trailing_text = True
                elif name == "create_chart":
                    # Fetch chart spec from side-channel (tool returns only a short marker)
                    if output_str.startswith("CHART_READY:"):
                        # Format: "CHART_READY:<id> (...)\ndata=[...]"
                        chart_id = output_str.split(":", 1)[1].split()[0].strip()
                        from analytics_agent.agent.chart_tool import _pending_charts

                        pending_chart = _pending_charts.pop(chart_id, None)
                        if pending_chart:
                            chart_emitted = True
                            yield {
                                "event": "CHART",
                                "conversation_id": conversation_id,
                                "message_id": str(uuid.uuid4()),
                                "payload": pending_chart,
                            }
                    # else: silently skip (chart failed, model will explain in text)
                else:
                    is_error = False
                    result_text = output_str[:2000]
                    try:
                        parsed = orjson.loads(output_str)
                        if isinstance(parsed, dict) and "error" in parsed:
                            is_error = True
                            result_text = parsed["error"]
                    except Exception:
                        pass
                    yield {
                        "event": "TOOL_RESULT",
                        "conversation_id": conversation_id,
                        "message_id": str(uuid.uuid4()),
                        "payload": {
                            "tool_name": name,
                            "result": result_text,
                            "is_error": is_error,
                        },
                    }

            # ── USAGE (token counts per LLM call) ──
            elif event_type == "on_chat_model_end" and node not in ("chart", ""):
                output = data.get("output")
                usage = getattr(output, "usage_metadata", None) if output is not None else None
                if usage:
                    input_tokens = int(usage.get("input_tokens", 0) or 0)
                    output_tokens = int(usage.get("output_tokens", 0) or 0)
                    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
                    details = usage.get("input_token_details") or {}
                    cache_read = int(details.get("cache_read", 0) or 0)
                    cache_creation = int(details.get("cache_creation", 0) or 0)
                    yield {
                        "event": "USAGE",
                        "conversation_id": conversation_id,
                        "message_id": run_id,
                        "payload": {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                            "cache_read_tokens": cache_read,
                            "cache_creation_tokens": cache_creation,
                            "node": node,
                        },
                    }

            # ── Capture final state for CHART ──
            elif event_type == "on_chain_end" and name == "LangGraph":
                output = data.get("output", {})
                if isinstance(output, dict):
                    final_state = output

    except Exception as exc:
        yield {
            "event": "ERROR",
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "payload": {"error": str(exc)},
        }

    # Emit CHART if chart_node populated pending_chart
    # Emit CHART from chart_node state (SQL-path charts)
    state_chart = final_state.get("pending_chart")
    if state_chart and not chart_emitted:
        chart_emitted = True
        yield {
            "event": "CHART",
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "payload": {
                "vega_lite_spec": state_chart.get("vega_lite_spec", {}),
                "reasoning": state_chart.get("reasoning", ""),
                "chart_type": state_chart.get("chart_type", ""),
            },
        }

    # Fallback: model outputs chart spec as JSON text — only if no CHART was already emitted
    full_text = "".join(final_text_parts)
    if not chart_emitted:
        extracted_chart = _extract_chart_from_text(full_text)
        if extracted_chart:
            clean_text = _strip_chart_json_blocks(full_text)
            final_text_parts[:] = [clean_text]
            yield {
                "event": "CHART",
                "conversation_id": conversation_id,
                "message_id": str(uuid.uuid4()),
                "payload": extracted_chart,
            }
    else:
        # Strip any chart JSON from text even if chart was already emitted via tool
        clean_text = _strip_chart_json_blocks(full_text)
        if clean_text != full_text:
            final_text_parts[:] = [clean_text]

    yield {
        "event": "COMPLETE",
        "conversation_id": conversation_id,
        "message_id": str(uuid.uuid4()),
        "payload": {"text": "".join(final_text_parts)},
    }
