"""
Pluggable chat history compaction.

OSS default: TurnWindowCompactor drops oldest turns by token budget.
DataHub Cloud (or other extensions) can register a SummarizingCompactor
via compactor_registry.register_compactor() at app startup.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage


@runtime_checkable
class HistoryCompactor(Protocol):
    def compact(
        self,
        turns: list[list[BaseMessage]],
        max_tokens: int,
    ) -> list[list[BaseMessage]]:
        """Return a (possibly shorter) list of turns that fits within max_tokens.

        Turns are in chronological order; always keep the most recent turn.
        Never return an empty list when given a non-empty input.
        """
        ...


def estimate_tokens(msgs: list[BaseMessage]) -> int:
    """Fast character-based token estimate (~4 chars per token)."""
    total = 0
    for msg in msgs:
        total += 100  # per-message overhead (role, metadata, framing)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(content) // 4
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls or []:
                total += len(str(tc.get("args", ""))) // 4
    return total


class TurnWindowCompactor:
    """Drop oldest turns until the flattened history fits within max_tokens."""

    def compact(
        self,
        turns: list[list[BaseMessage]],
        max_tokens: int,
    ) -> list[list[BaseMessage]]:
        while len(turns) > 1:
            flat = [msg for turn in turns for msg in turn]
            if estimate_tokens(flat) <= max_tokens:
                break
            turns = turns[1:]
        return turns
