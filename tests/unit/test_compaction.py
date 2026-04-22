"""Unit tests for chat history compaction."""

from __future__ import annotations

from analytics_agent.agent.compaction import TurnWindowCompactor, estimate_tokens
from langchain_core.messages import AIMessage, HumanMessage


def _make_turns(n: int, chars_per_turn: int = 1000) -> list[list]:
    """Build n turns of human+AI messages, each ~chars_per_turn characters."""
    turns = []
    for i in range(n):
        text = f"turn {i}: " + "x" * chars_per_turn
        turns.append([HumanMessage(content=text), AIMessage(content=text)])
    return turns


def test_estimate_tokens_basic():
    msgs = [HumanMessage(content="hello world")]
    # 100 overhead + 11 chars // 4 = 100 + 2 = 102
    assert estimate_tokens(msgs) == 102


def test_no_compaction_needed():
    turns = _make_turns(3, chars_per_turn=100)
    compactor = TurnWindowCompactor()
    result = compactor.compact(turns, max_tokens=100_000)
    assert result == turns


def test_drops_oldest_turns():
    # 50 turns × ~1000 chars each → well over 120K tokens
    turns = _make_turns(50, chars_per_turn=1000)
    compactor = TurnWindowCompactor()
    result = compactor.compact(turns, max_tokens=5_000)
    assert len(result) < len(turns)
    # Most recent turn is always preserved
    assert result[-1] is turns[-1]


def test_always_keeps_last_turn():
    # Even one huge turn should not be dropped
    turns = _make_turns(1, chars_per_turn=500_000)
    compactor = TurnWindowCompactor()
    result = compactor.compact(turns, max_tokens=100)
    assert len(result) == 1
    assert result[0] is turns[0]


def test_preserves_order():
    turns = _make_turns(10, chars_per_turn=100)
    compactor = TurnWindowCompactor()
    result = compactor.compact(turns, max_tokens=10_000)
    # Whatever subset is kept, order must be newest-at-end
    for i in range(len(result) - 1):
        original_i = turns.index(result[i])
        original_j = turns.index(result[i + 1])
        assert original_i < original_j
