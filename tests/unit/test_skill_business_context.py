"""Tests for the search_business_context skill helpers."""

from __future__ import annotations

from analytics_agent.skills.datahub_skills import _all_results_empty


def test_all_empty_when_every_subsearch_has_no_results():
    results = {
        "documentation": {"searchResults": [], "total": 0},
        "glossary_terms": {"searchResults": [], "total": 0},
        "domains": {"searchResults": [], "total": 0},
        "data_products": {"searchResults": [], "total": 0},
    }
    assert _all_results_empty(results) is True


def test_not_empty_when_any_subsearch_has_a_hit():
    results = {
        "documentation": {"searchResults": [], "total": 0},
        "glossary_terms": {
            "searchResults": [{"entity": {"urn": "urn:li:glossaryTerm:revenue"}}],
            "total": 1,
        },
        "domains": {"searchResults": [], "total": 0},
        "data_products": {"searchResults": [], "total": 0},
    }
    assert _all_results_empty(results) is False


def test_errors_count_as_empty():
    """A sub-search that errored is not a 'found something'."""
    results = {
        "documentation": {"error": "API down"},
        "glossary_terms": {"searchResults": [], "total": 0},
        "domains": {"searchResults": [], "total": 0},
        "data_products": {"searchResults": [], "total": 0},
    }
    assert _all_results_empty(results) is True


def test_missing_search_results_key_counts_as_empty():
    """Unknown / partial dict shape is treated as empty rather than crashing."""
    results = {
        "documentation": {"facets": {}},
        "glossary_terms": {},
        "domains": {"searchResults": []},
        "data_products": {"searchResults": []},
    }
    assert _all_results_empty(results) is True
