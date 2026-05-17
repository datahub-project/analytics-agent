"""Human-in-the-loop configuration for the deepagents harness.

Wraps mutation-class tools so the graph pauses before they execute, giving
the user a chance to approve / reject / edit the proposed call. Resumption
is driven by `POST /api/conversations/{id}/resume` which threads the
decision back into langgraph via `Command(resume=...)`.

The set of intercepted tools is built dynamically at graph-build time:
  - DataHub mutation tools (datahub_agent_context's write tools)
  - Skill mutation tools that the user has enabled (publish_analysis,
    save_correction)
  - Optionally `execute` (sandbox shell) — gated by settings.hitl_interrupt_execute

Tools NOT in the interrupt set auto-proceed silently. Auto-approved by
default: every read-only tool (search, get_entities, execute_sql, ...).
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

# Always intercepted, regardless of operator policy. ask_user is a stub
# tool whose entire purpose is to surface a question to the user via HITL —
# it cannot function without the interrupt.
ALWAYS_INTERCEPTED: frozenset[str] = frozenset({"ask_user"})

# DataHub MCP / native write tools. Names match what
# datahub_agent_context.langchain_tools exposes when include_mutations=True.
DATAHUB_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "add_tags",
        "remove_tags",
        "add_terms",
        "remove_terms",
        "update_description",
        "update_glossary_term_description",
        "set_domains",
        "set_owners",
        "remove_owners",
        "save_document",
        "delete_entity",
    }
)

# Opt-in skill tools defined in skills/loader.py — same names users see in
# Settings → "Enabled mutation tools".
SKILL_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "publish_analysis",
        "save_correction",
    }
)


def build_interrupt_config(
    enabled_mutations: set[str] | None,
    extra_tools: set[str] | None = None,
    policy_override: list[str] | None = None,
) -> dict[str, bool | InterruptOnConfig]:
    """Build the `interrupt_on` dict passed to `create_deep_agent`.

    Args:
        enabled_mutations: Skill mutations the user has enabled (e.g.
            {"publish_analysis"}). Each enabled one always interrupts.
        extra_tools: Additional tool names to interrupt on (e.g. "execute"
            when the operator wants shell commands gated).
        policy_override: When non-empty, replaces the built-in defaults
            entirely — only the listed tools interrupt. Empty list and
            None both mean "use defaults". Operators set this via
            Settings → HITL to widen or narrow the gate.

    Returns:
        A dict mapping tool name → `True` (allowing approve/edit/reject).
        Tools not in the dict auto-proceed.
    """
    if policy_override:
        # Even with an operator override, ALWAYS_INTERCEPTED tools (e.g.
        # ask_user) are still gated — without the interrupt they would
        # return their stub default and the feature would silently break.
        return {name: True for name in (set(policy_override) | ALWAYS_INTERCEPTED)}

    enabled_mutations = enabled_mutations or set()
    extra_tools = extra_tools or set()

    intercepted: set[str] = set(ALWAYS_INTERCEPTED)
    intercepted.update(DATAHUB_MUTATION_TOOLS)
    intercepted.update(SKILL_MUTATION_TOOLS & enabled_mutations)
    intercepted.update(extra_tools)

    return {name: True for name in intercepted}


def all_known_mutation_tools() -> list[str]:
    """All tool names the operator might want to gate. Used to populate
    the Settings → HITL UI."""
    return sorted(set(DATAHUB_MUTATION_TOOLS) | set(SKILL_MUTATION_TOOLS) | {"execute"})


# Process-wide checkpointer. "sqlite" uses AsyncSqliteSaver — required
# because the agent runs through `astream_events` (async). The sync
# SqliteSaver crashes with "does not support async methods" when invoked
# from the async graph runtime.
#
# We hold the saver AND the underlying aiosqlite.Connection at module
# scope so neither is GC-closed mid-process.
_CHECKPOINTER: BaseCheckpointSaver | None = None
_CHECKPOINTER_CONN: Any = None  # aiosqlite.Connection (kept alive)
_CHECKPOINTER_LOCK: Any = None  # asyncio.Lock — created lazily on first use


def get_checkpointer() -> BaseCheckpointSaver:
    """Return the process-wide checkpointer.

    For SQLite, returns the AsyncSqliteSaver synchronously. The saver's
    own constructor is sync — only its read/write methods are async — so
    we can build it eagerly. The aiosqlite.Connection is opened on the
    running event loop the first time the agent actually awaits it.
    """
    global _CHECKPOINTER, _CHECKPOINTER_CONN
    if _CHECKPOINTER is None:
        _CHECKPOINTER, _CHECKPOINTER_CONN = _build_checkpointer()
    return _CHECKPOINTER


def _build_checkpointer() -> tuple[BaseCheckpointSaver, Any]:
    """Construct the configured checkpointer. Returns (saver, conn).

    For SQLite: builds an `aiosqlite.Connection` (lazy — actually opens
    on first await) and wraps it in `AsyncSqliteSaver`. Schema setup
    runs on the agent's event loop the first time the saver is used,
    via `AsyncSqliteSaver.aput`/`asetup` internals.

    For memory: returns InMemorySaver, conn=None.
    """
    from analytics_agent.config import settings

    backend = getattr(settings, "hitl_checkpointer", "sqlite")
    if backend == "sqlite":
        from pathlib import Path

        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = Path(settings.hitl_checkpoint_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # aiosqlite.connect returns a Connection that lazily opens on the
        # first awaited call. Safe to construct off-loop.
        conn = aiosqlite.connect(str(db_path), check_same_thread=False)
        saver = AsyncSqliteSaver(conn)
        # Schema setup happens automatically on first aput; we can't await
        # asetup here (sync caller). The saver tolerates this.
        return saver, conn
    return InMemorySaver(), None


def thread_config(conversation_id: str) -> dict[str, Any]:
    """Standard config dict for langgraph runs — the thread_id keys the
    checkpointer's per-conversation slot. All chat invocations and resumes
    must use the same thread_id."""
    return {"configurable": {"thread_id": conversation_id}}
