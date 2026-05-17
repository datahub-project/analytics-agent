"""Unit tests for the typed final-response schema."""

from __future__ import annotations

from analytics_agent.agent.response_format import AnalystResponse


def test_analyst_response_minimum_shape():
    r = AnalystResponse(summary="42 users last week.")
    assert r.summary == "42 users last week."
    # default empty list — chips just hide
    assert r.follow_ups == []


def test_analyst_response_with_follow_ups():
    r = AnalystResponse(
        summary="Sales were down 12% week-over-week.",
        follow_ups=[
            "Break this down by region",
            "Show the same metric for last quarter",
        ],
    )
    assert len(r.follow_ups) == 2


def test_schema_has_no_optional_unions():
    """Bedrock caps union-typed parameters across the tool surface. Keep
    follow_ups as a plain array (not array | null) so structured-output
    on Bedrock doesn't burn one of the 16 slots on this schema."""
    schema = AnalystResponse.model_json_schema()
    props = schema["properties"]
    # follow_ups must be a plain `array`, not a union with null
    assert props["follow_ups"]["type"] == "array"
    assert "anyOf" not in props["follow_ups"]
