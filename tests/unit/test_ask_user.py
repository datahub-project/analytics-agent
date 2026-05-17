"""Unit tests for the ask_user tool."""

from __future__ import annotations

from analytics_agent.agent.ask_user import ask_user


def test_ask_user_returns_default_when_no_answer():
    """Without a submitted answer (reject path), the tool returns a stub
    so the agent sees an explicit signal rather than empty string."""
    out = ask_user.invoke({"question": "Pick one", "options": ["a", "b"], "answer": ""})
    assert out == "User declined to answer."


def test_ask_user_returns_answer_verbatim():
    """When the harness fills in answer=<user reply>, the tool returns it
    so the agent's next ToolMessage carries the user's text exactly."""
    out = ask_user.invoke({"question": "Pick one", "options": ["a", "b"], "answer": "a"})
    assert out == "a"


def test_ask_user_handles_default_options():
    """options defaults to [] — pure free-text path."""
    out = ask_user.invoke({"question": "What's up?", "answer": "ok"})
    assert out == "ok"


def test_ask_user_schema_has_no_optional_unions():
    """Bedrock caps union-typed parameters across the tool surface; keep
    options as plain `array` (not `array | null`)."""
    schema = ask_user.args_schema.model_json_schema()
    props = schema["properties"]
    # `options` should be a list type, not anyOf with null
    assert "anyOf" not in props["options"]
