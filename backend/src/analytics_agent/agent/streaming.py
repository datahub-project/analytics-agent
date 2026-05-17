from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import orjson
from langchain_core.messages import BaseMessage

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


def _normalize_interrupts(raw: Any) -> list[dict]:
    """Convert langgraph Interrupt objects into JSON-safe dicts for the UI.

    langgraph emits `__interrupt__` as a tuple of `Interrupt` objects whose
    `.value` is the `HITLRequest` from langchain — a dict with
    `action_requests` and `review_configs` lists. We pass it through with
    a stable `interrupt_id` and shape suitable for the frontend card.
    """
    out: list[dict] = []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    for it in items:
        value = getattr(it, "value", it)
        # Some langgraph versions wrap in {"value": ...}; flatten.
        if isinstance(value, dict) and set(value.keys()) == {"value"}:
            value = value["value"]
        action_requests = (
            value.get("action_requests", []) if isinstance(value, dict) else []
        )
        review_configs = (
            value.get("review_configs", []) if isinstance(value, dict) else []
        )
        # Pair each action with its review config (allowed_decisions, etc.)
        actions: list[dict] = []
        for idx, action in enumerate(action_requests):
            review = review_configs[idx] if idx < len(review_configs) else {}
            actions.append(
                {
                    "tool_name": action.get("action", "") if isinstance(action, dict) else "",
                    "tool_input": action.get("args", {}) if isinstance(action, dict) else {},
                    "description": action.get("description", "")
                    if isinstance(action, dict)
                    else "",
                    "allowed_decisions": (
                        review.get("allowed_decisions", ["approve", "reject"])
                        if isinstance(review, dict)
                        else ["approve", "reject"]
                    ),
                }
            )
        out.append(
            {
                "interrupt_id": getattr(it, "id", None) or getattr(it, "ns", [""])[-1] or "",
                "actions": actions,
            }
        )
    return out


def _stringify_tool_output(output: Any) -> str:
    """Coerce a tool's `on_tool_end` output to a string for SSE/storage.

    Handles four shapes that show up under deepagents:
      - str: pass through
      - langchain `BaseMessage` (ToolMessage, AIMessage): extract `.content`
      - langgraph `Command` (returned by the `task` sub-agent dispatch tool):
        pull the last message off `Command.update["messages"]`
      - anything else: orjson.dumps with a string-fallback default for any
        nested unserializable object (e.g. an embedded BaseMessage).
    """
    if isinstance(output, str):
        return output
    if isinstance(output, BaseMessage):
        content = output.content
        return content if isinstance(content, str) else orjson.dumps(content, default=str).decode()
    update = getattr(output, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages") or []
        if messages:
            last = messages[-1]
            if isinstance(last, BaseMessage):
                content = last.content
                return (
                    content
                    if isinstance(content, str)
                    else orjson.dumps(content, default=str).decode()
                )
    try:
        return orjson.dumps(output, default=str).decode()
    except (TypeError, ValueError):
        return str(output)


async def stream_graph_events(
    graph,
    user_text: str,
    conversation_id: str,
    engine_name: str,
    keepalive_interval: int = 15,
    history: list | None = None,
    resume_payload: Any | None = None,
) -> AsyncIterator[dict]:
    """
    Yield event dicts from the LangGraph graph.
    Callers convert to SSE strings via to_sse().
    history: reconstructed LangChain messages for prior turns (from history.py)
    resume_payload: when set, the graph resumes from a prior interrupt with
        this `Command(resume=...)` payload instead of starting a new turn.
    """
    if resume_payload is not None:
        # Resuming: pass the Command to astream_events; messages/inputs are
        # ignored because state is recovered from the checkpointer.
        from langgraph.types import Command

        inputs: Any = Command(resume=resume_payload)
    else:
        messages = history if history else [{"role": "user", "content": user_text}]
        inputs = {
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

    try:
        from analytics_agent.agent.hitl import thread_config
        from analytics_agent.config import settings as _settings

        cfg = {
            "recursion_limit": _settings.agent_recursion_limit,
            **thread_config(conversation_id),
        }
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
                output = data.get("output", "")
                # MCP tools return a list of content blocks: [{"type":"text","text":"...","id":"..."}]
                # Unwrap to the inner text so the rest of the pipeline sees a plain JSON string.
                if (
                    isinstance(output, list)
                    and output
                    and isinstance(output[0], dict)
                    and "text" in output[0]
                ):
                    output = output[0]["text"]
                output_str = _stringify_tool_output(output)

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
                # Detect HITL interrupts. langgraph surfaces them in the
                # final chain output as `__interrupt__: tuple[Interrupt]`.
                if isinstance(output, dict) and "__interrupt__" in output:
                    for interrupt_evt in _normalize_interrupts(output["__interrupt__"]):
                        yield {
                            "event": "INTERRUPT",
                            "conversation_id": conversation_id,
                            "message_id": str(uuid.uuid4()),
                            "payload": interrupt_evt,
                        }

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

    # Structured response (when create_deep_agent was built with
    # response_format=AnalystResponse). Lives at state.structured_response.
    # We only surface follow-ups — the summary text is already covered by
    # the streamed TEXT events / COMPLETE payload.
    structured = final_state.get("structured_response") if final_state else None
    follow_ups: list[str] = []
    if structured is not None:
        raw_follow_ups = (
            structured.follow_ups
            if hasattr(structured, "follow_ups")
            else structured.get("follow_ups", []) if isinstance(structured, dict) else []
        )
        if isinstance(raw_follow_ups, list):
            follow_ups = [str(s).strip() for s in raw_follow_ups if str(s).strip()][:3]
    if follow_ups:
        yield {
            "event": "FOLLOW_UPS",
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "payload": {"questions": follow_ups},
        }

    # Post-iteration interrupt detection. HumanInTheLoopMiddleware pauses
    # the graph BEFORE the tool actually runs, so there's no `on_tool_start`
    # event and the `on_chain_end` event for the outer LangGraph may not
    # include `__interrupt__` (depending on langgraph version). Inspect the
    # checkpointed state directly so an interrupt always surfaces.
    interrupted = False
    try:
        snap = await graph.aget_state(cfg)
        pending_interrupts: list[Any] = []
        for task in getattr(snap, "tasks", ()) or ():
            for it in (getattr(task, "interrupts", None) or ()):
                pending_interrupts.append(it)
        if pending_interrupts:
            interrupted = True
            for interrupt_evt in _normalize_interrupts(pending_interrupts):
                yield {
                    "event": "INTERRUPT",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": interrupt_evt,
                }
    except Exception:
        # State inspection failed (e.g. no checkpointer mid-config); don't
        # block COMPLETE — fall through.
        pass

    if not interrupted:
        yield {
            "event": "COMPLETE",
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "payload": {"text": "".join(final_text_parts)},
        }
