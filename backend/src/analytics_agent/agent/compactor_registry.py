"""
Module-level registry for the active HistoryCompactor.

DataHub Cloud (or any extension) can call register_compactor() at app startup
to swap in a more sophisticated strategy (e.g. LLM summarization) without
modifying core files.
"""

from __future__ import annotations

from analytics_agent.agent.compaction import HistoryCompactor, TurnWindowCompactor

_compactor: HistoryCompactor = TurnWindowCompactor()


def register_compactor(c: HistoryCompactor) -> None:
    global _compactor
    _compactor = c


def get_compactor() -> HistoryCompactor:
    return _compactor
