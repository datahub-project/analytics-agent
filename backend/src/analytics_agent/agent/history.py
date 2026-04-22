"""
Reconstruct LangChain-compatible message history from DB-persisted events.

Strategy:
- Group stored messages by user turn (each user TEXT starts a new turn).
- Each turn emits: HumanMessage → [tool call/result pairs] → AIMessage (final text).
- Tool calls and results are matched by sequence order within a turn.
- If a turn had no tool calls and no COMPLETE text, we fall back to TEXT chunks.
- Turns that have no assistant response at all (e.g. error turns) are skipped entirely
  to avoid consecutive HumanMessages which LangGraph rejects.
- An optional HistoryCompactor drops the oldest turns to stay within the token budget.
"""

from __future__ import annotations

import re

import orjson
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from analytics_agent.agent.compaction import HistoryCompactor


def build_history(
    stored_messages: list,
    current_user_text: str,
    compactor: HistoryCompactor | None = None,
    max_history_tokens: int = 120_000,
) -> list[BaseMessage]:
    """
    Convert persisted message rows into a LangChain message list ending with
    the current user turn.

    If a compactor is provided, oldest turns are dropped to stay within
    max_history_tokens before returning.
    """
    # Split into turns at each user TEXT message
    raw_turns: list[list] = []
    current_turn: list = []
    for msg in stored_messages:
        payload = orjson.loads(msg.payload) if isinstance(msg.payload, str) else msg.payload
        if msg.role == "user" and msg.event_type == "TEXT":
            if current_turn:
                raw_turns.append(current_turn)
            current_turn = [("user", payload.get("text", ""), msg)]
        else:
            current_turn.append((msg.role, payload, msg))
    if current_turn:
        raw_turns.append(current_turn)

    # Build LangChain messages per turn
    lc_turns: list[list[BaseMessage]] = []
    for turn in raw_turns:
        role0, content0, _ = turn[0]
        if role0 != "user":
            continue

        tool_calls: list[dict] = []
        tool_results: list[dict] = []
        text_chunks: list[str] = []
        final_text = ""
        has_chart = False

        for role, payload, msg in turn[1:]:
            if role != "assistant":
                continue
            evt = msg.event_type

            if evt == "TOOL_CALL":
                tool_calls.append(
                    {
                        "id": msg.id,
                        "name": payload.get("tool_name", ""),
                        "input": payload.get("tool_input", {}),
                    }
                )
            elif evt in ("TOOL_RESULT", "SQL"):
                idx = len(tool_results)
                call_id = tool_calls[idx]["id"] if idx < len(tool_calls) else msg.id
                tool_results.append(
                    {
                        "id": call_id,
                        "name": payload.get("tool_name", ""),
                        "result": payload.get("result", payload.get("sql", ""))[:4000],
                    }
                )
            elif evt == "TEXT":
                chunk = payload.get("text", "")
                if chunk:
                    text_chunks.append(chunk)
            elif evt == "COMPLETE":
                final_text = payload.get("text", "")
            elif evt == "CHART":
                has_chart = True

        if not final_text:
            assembled = "".join(text_chunks)
            assembled = re.sub(
                r"```(?:json)?\s*\{.*?\"chart_schema\".*?\}\s*```", "", assembled, flags=re.DOTALL
            ).strip()
            final_text = assembled[:500] if assembled else ""

        if not final_text and has_chart:
            final_text = "[Chart rendered]"

        has_any_assistant_content = tool_calls or final_text or has_chart
        if not has_any_assistant_content:
            continue

        turn_msgs: list[BaseMessage] = []
        turn_msgs.append(HumanMessage(content=content0))

        if tool_calls:
            lc_tool_calls = [
                {
                    "id": tc["id"],
                    "name": tc["name"],
                    "args": tc["input"],
                    "type": "tool_call",
                }
                for tc in tool_calls
            ]
            turn_msgs.append(AIMessage(content="", tool_calls=lc_tool_calls))

            # Every tool_call must have a ToolMessage with its exact ID.
            # Pad missing results; always use tc["id"] as tool_call_id so
            # the IDs are guaranteed to match the AIMessage (avoids Anthropic
            # "unexpected tool_use_id" errors from orphaned DB records).
            for i, tc in enumerate(tool_calls):
                if i < len(tool_results):
                    tr = tool_results[i]
                    turn_msgs.append(
                        ToolMessage(
                            content=str(tr["result"]),
                            tool_call_id=tc["id"],
                            name=tr["name"],
                        )
                    )
                else:
                    turn_msgs.append(
                        ToolMessage(
                            content="[Tool did not return a result]",
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )

        if final_text or not tool_calls:
            turn_msgs.append(AIMessage(content=final_text or "Done."))

        lc_turns.append(turn_msgs)

    # Drop oldest turns if needed
    if compactor is not None and lc_turns:
        lc_turns = compactor.compact(lc_turns, max_tokens=max_history_tokens)

    result = [msg for turn in lc_turns for msg in turn]
    result.append(HumanMessage(content=current_user_text))
    return result
