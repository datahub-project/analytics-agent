"""
Tests for the always-on check_data_quality skill (PR #96 + wiring).

Two concerns:
  1. Wiring — the skill's SKILL.md body is injected into the system prompt
     (the gap that made the skill a no-op: it was never registered).
  2. Contract — the tool the skill tells the agent to call
     (get_dataset_assertions) exists and, given a FAILING freshness assertion,
     surfaces exactly the fields the skill instructs the agent to read
     (type / latestResultType / description).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from analytics_agent.prompts.system import build_system_prompt
from analytics_agent.skills.loader import get_check_data_quality_prompt_section

# ---------------------------------------------------------------------------
# 1. Wiring — the skill reaches the system prompt
# ---------------------------------------------------------------------------


def test_check_data_quality_section_loads_and_mentions_the_tool() -> None:
    section = get_check_data_quality_prompt_section()
    assert section.strip(), "check_data_quality section must not be empty"
    # It routes through the real native tool and is about assertions/freshness.
    assert "get_dataset_assertions" in section
    assert "assertion" in section.lower()
    assert "fresh" in section.lower()


def test_system_prompt_includes_check_data_quality_section() -> None:
    """The always-on wiring: build_system_prompt must inject the skill body."""
    prompt = build_system_prompt("snowflake")
    assert "check_data_quality" in prompt
    assert "get_dataset_assertions" in prompt


# ---------------------------------------------------------------------------
# 2. Contract — the referenced tool exists and yields the fields the skill reads
# ---------------------------------------------------------------------------


def test_get_dataset_assertions_is_importable_with_compatible_signature() -> None:
    import inspect

    da = pytest.importorskip("datahub_agent_context.mcp_tools.assertions")
    params = inspect.signature(da.get_dataset_assertions).parameters
    # The skill calls get_dataset_assertions(urn=..., count=10)
    assert "urn" in params
    assert "count" in params


def test_get_dataset_assertions_surfaces_failing_freshness() -> None:
    """Mocked assertions response: a FAILING freshness assertion must surface as
    type=FRESHNESS + latestResultType=FAILURE — the exact fields the skill reads."""
    da = pytest.importorskip("datahub_agent_context.mcp_tools.assertions")

    raw_assertion = {
        "urn": "urn:li:assertion:orders-mart-freshness",
        "info": {
            "type": "FRESHNESS",
            "description": "orders_mart must be < 24h behind its source",
        },
        "runEvents": {
            "total": 5,
            "succeeded": 3,
            "failed": 2,
            "runEvents": [{"result": {"type": "FAILURE"}}],
        },
    }
    gql_response = {
        "searchAcrossEntities": {
            "start": 0,
            "total": 1,
            "searchResults": [{"entity": raw_assertion}],
        }
    }

    with (
        patch.object(da, "execute_graphql", return_value=gql_response),
        patch.object(da, "get_graph", return_value=MagicMock()),
    ):
        result = da.get_dataset_assertions(
            urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.orders_mart,PROD)",
            count=10,
        )

    assert result["success"] is True
    assertions = result["data"]["assertions"]
    assert len(assertions) == 1
    a = assertions[0]
    assert a["type"] == "FRESHNESS"
    assert a["latestResultType"] == "FAILURE"
    assert a["description"]
