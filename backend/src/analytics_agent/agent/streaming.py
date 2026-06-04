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

# Per-conversation snapshot of the deepagents virtual filesystem. Populated
# during streaming whenever write_file/edit_file fires (and at end-of-turn).
# The `/files` HTTP endpoint reads this so the Files panel can survive a reload
# without depending on outer-graph checkpoint propagation, which is unreliable
# for the `files` DeltaChannel.
FILES_SNAPSHOTS: dict[str, dict[str, str]] = {}


def _normalize_files(raw: Any) -> dict[str, str]:
    """Coerce a deepagents `files` channel value into {path: content_str}.

    deepagents stores entries as `FileData` dicts (`{content, encoding, ...}`)
    in v2 format and plain strings in v1. We surface only the content for the
    UI panel — encoding/mtime aren't displayed.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for path, data in raw.items():
        if isinstance(data, str):
            out[path] = data
        elif isinstance(data, dict):
            content = data.get("content")
            if isinstance(content, str):
                out[path] = content
            elif isinstance(content, list):
                # v1 stored content as list[str] (lines)
                out[path] = "\n".join(str(line) for line in content)
    return out


async def _snapshot_virtual_files(graph: Any, cfg: dict) -> dict[str, str]:
    """Read the current virtual-filesystem snapshot from the live graph.

    `aget_state(subgraphs=True)` walks into the deepagents subgraph so we pick
    up files even when the outer state's `files` channel hasn't received the
    subgraph's delta yet (DeltaChannel propagation across StateGraph nodes is
    not guaranteed to be synchronous within a single agent step).
    """
    try:
        snap = await graph.aget_state(cfg, subgraphs=True)
    except Exception:
        return {}
    files = _normalize_files((snap.values or {}).get("files"))
    # Walk pending subgraph tasks; deepagents writes files inside the inner
    # agent's state and we want those even mid-step.
    for task in getattr(snap, "tasks", ()) or ():
        sub = getattr(task, "state", None)
        sub_values = getattr(sub, "values", None) if sub is not None else None
        if isinstance(sub_values, dict):
            files.update(_normalize_files(sub_values.get("files")))
    return files


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

    # A per-turn thread id so the (per-request) InMemorySaver checkpoints this
    # run's state, letting us snapshot the deepagents virtual filesystem via
    # `aget_state`. The graph is rebuilt per request, so this never leaks state.
    cfg: dict[str, Any] = {"configurable": {"thread_id": conversation_id}}

    def _emit_files(files: dict[str, str]) -> dict | None:
        """Cache + build a FILES_UPDATE event, or None if nothing changed."""
        if FILES_SNAPSHOTS.get(conversation_id) == files:
            return None
        FILES_SNAPSHOTS[conversation_id] = files
        return {
            "event": "FILES_UPDATE",
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "payload": {"files": files},
        }

    try:
        from analytics_agent.config import settings as _settings

        cfg["recursion_limit"] = _settings.agent_recursion_limit
        async for event in graph.astream_events(inputs, version="v2", config=cfg):
            event_type: str = event.get("event", "")
            data: dict[str, Any] = event.get("data", {})
            name: str = event.get("name", "")
            run_id: str = event.get("run_id", "")
            node: str = event.get("metadata", {}).get("langgraph_node", "")

            # ── TEXT ──
            if event_type == "on_chat_model_stream" and node not in ("chart", ""):
                chunk = data.get("chunk")
                if chunk is None:
                    continue
                if getattr(chunk, "tool_call_chunks", None):
                    continue
                content = chunk.content if hasattr(chunk, "content") else ""
                if isinstance(content, str) and content:
                    final_text_parts.append(content)
                    yield {
                        "event": "TEXT",
                        "conversation_id": conversation_id,
                        "message_id": run_id,
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
                                    "message_id": run_id,
                                    "payload": {"text": text},
                                }

            # ── TOOL_CALL ──
            elif event_type == "on_tool_start":
                tool_input = data.get("input", {})
                if name == "execute_sql":
                    pending_sql[run_id] = tool_input.get("sql", "")
                # create_chart renders as a CHART event — don't show a tool call bubble
                if name == "create_chart":
                    continue
                # `write_todos` is the deepagents planning tool — surface as a
                # dedicated TODOS event so the UI plan panel can subscribe.
                if name == "write_todos":
                    yield {
                        "event": "TODOS",
                        "conversation_id": conversation_id,
                        "message_id": str(uuid.uuid4()),
                        "payload": {"todos": tool_input.get("todos", [])},
                    }
                    continue
                yield {
                    "event": "TOOL_CALL",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": {"tool_name": name, "tool_input": tool_input},
                }

            # ── TOOL_ERROR (unhandled exception from tool) ──
            elif event_type == "on_tool_error":
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

            # ── SQL / TOOL_RESULT / CHART ──
            elif event_type == "on_tool_end":
                # File-mutating deepagents tools — re-snapshot the virtual FS so
                # the Files panel updates live as the agent writes scratch files.
                if name in ("write_file", "edit_file"):
                    files_evt = _emit_files(await _snapshot_virtual_files(graph, cfg))
                    if files_evt is not None:
                        yield files_evt

                if name == "write_todos":
                    # The TODOS event was already emitted at tool_start with the
                    # full planned list; the tool_end output is just an ack.
                    continue

                output = data.get("output", "")
                if hasattr(output, "content"):
                    output = output.content
                # MCP tools return a list of content blocks: [{"type":"text","text":"...","id":"..."}]
                # Unwrap to the inner text so the rest of the pipeline sees a plain JSON string.
                if (
                    isinstance(output, list)
                    and output
                    and isinstance(output[0], dict)
                    and "text" in output[0]
                ):
                    output = output[0]["text"]
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
                    rmeta = getattr(output, "response_metadata", None) or {}
                    model_name = (
                        rmeta.get("model_name") or rmeta.get("model") or _settings.get_llm_model()
                    )
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
                            "model": model_name,
                            "provider": _settings.llm_provider,
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

    # End-of-turn filesystem snapshot — catches files the FilesystemMiddleware
    # offloaded large tool results into (e.g. /large_tool_results/<id>) that no
    # write_file/edit_file event covered.
    files_evt = _emit_files(await _snapshot_virtual_files(graph, cfg))
    if files_evt is not None:
        yield files_evt

    yield {
        "event": "COMPLETE",
        "conversation_id": conversation_id,
        "message_id": str(uuid.uuid4()),
        "payload": {"text": "".join(final_text_parts)},
    }
