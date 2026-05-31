"""
Unit tests for _search_business_context_impl fallback behaviour (issue #61).

When a dataset exists in DataHub but has no docs / glossary / domain / data-product
entries, the four business-context sub-searches all return empty.  The impl must
automatically fall back to a general catalog search and surface the result so the
agent doesn't incorrectly tell the user the entity "doesn't exist".
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from analytics_agent.skills.datahub_skills import (
    _is_empty_search_result,
    _search_business_context_impl,
)

# ---------------------------------------------------------------------------
# _is_empty_search_result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result, expected",
    [
        (None, True),
        ([], True),
        ({}, True),  # no recognised keys → no entities found
        ({"total": 0, "entities": []}, True),
        ({"total": 1, "entities": [{"urn": "urn:li:dataset:(x,y,PROD)"}]}, False),
        ({"results": []}, True),
        ({"results": [{"urn": "x"}]}, False),
        ({"error": "something went wrong"}, True),
    ],
)
def test_is_empty_search_result(result, expected):
    assert _is_empty_search_result(result) == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY = {"total": 0, "entities": []}
_HIT = {
    "total": 1,
    "entities": [{"urn": "urn:li:dataset:(urn:li:dataPlatform:hive,SampleHiveDataset,PROD)"}],
}


def _mock_datahub_context():
    """Patch DataHubContext so it works as a no-op context manager."""
    ctx_cls = MagicMock()
    ctx_cls.return_value.__enter__ = MagicMock(return_value=None)
    ctx_cls.return_value.__exit__ = MagicMock(return_value=False)
    return patch("datahub_agent_context.context.DataHubContext", ctx_cls)


# ---------------------------------------------------------------------------
# _search_business_context_impl — fallback to catalog search
# ---------------------------------------------------------------------------


def test_fallback_triggered_when_all_empty():
    """Catalog search is included when all business-context sub-searches are empty."""

    def _search_side_effect(**kwargs):
        # Filtered calls (glossaryTerm, domain, dataProduct) → empty;
        # un-filtered fallback call → hit
        if kwargs.get("filter"):
            return _EMPTY
        return _HIT

    mock_client = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(
            patch("analytics_agent.context.datahub.get_datahub_client", return_value=mock_client)
        )
        stack.enter_context(_mock_datahub_context())
        stack.enter_context(
            patch(
                "datahub_agent_context.mcp_tools.documents.search_documents",
                return_value=_EMPTY,
            )
        )
        stack.enter_context(
            patch(
                "datahub_agent_context.mcp_tools.search.search",
                side_effect=_search_side_effect,
            )
        )
        result = _search_business_context_impl("SampleHiveDataset")

    assert "catalog_search" in result, "Fallback catalog_search key must be present"
    assert result["catalog_search"] == _HIT
    assert "note" in result, "A note explaining the fallback must be present"


def test_no_fallback_when_business_context_found():
    """Catalog fallback is NOT added when at least one business-context search has results."""

    def _search_side_effect(**kwargs):
        if "glossaryTerm" in kwargs.get("filter", ""):
            return _HIT  # glossary found something
        return _EMPTY

    mock_client = MagicMock()
    with ExitStack() as stack:
        stack.enter_context(
            patch("analytics_agent.context.datahub.get_datahub_client", return_value=mock_client)
        )
        stack.enter_context(_mock_datahub_context())
        stack.enter_context(
            patch(
                "datahub_agent_context.mcp_tools.documents.search_documents",
                return_value=_EMPTY,
            )
        )
        stack.enter_context(
            patch(
                "datahub_agent_context.mcp_tools.search.search",
                side_effect=_search_side_effect,
            )
        )
        result = _search_business_context_impl("SomeMetric")

    assert "catalog_search" not in result
    assert "note" not in result


def test_returns_error_when_no_client():
    """Returns error dict immediately when DataHub is not configured."""
    with patch("analytics_agent.context.datahub.get_datahub_client", return_value=None):
        result = _search_business_context_impl("anything")
    assert result == {"error": "DataHub is not configured."}
