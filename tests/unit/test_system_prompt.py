"""Regression tests for system prompt rendering."""

from __future__ import annotations

from analytics_agent.prompts.system import build_system_prompt


def test_build_system_prompt_substitutes_engine_name():
    out = build_system_prompt("snowflake")
    assert "snowflake" in out


def test_build_system_prompt_does_not_format_literal_braces():
    """The shipped prompt embeds jq snippets like `{has_owner: ...}`.
    Using str.format() interprets those as placeholders and raises
    KeyError. Verify our renderer survives them — repro for the crash
    that shipped in 638c372."""
    out = build_system_prompt("snowflake")
    # The jq snippet's literal `{has_owner: ...}` should still be in the
    # rendered prompt, not stripped or substituted.
    assert "{has_owner" in out
