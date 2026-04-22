"""
DataHub write-back skill implementations.

These are bare Python functions — the agent guidance lives in the companion
SKILL.md files under each skill's sub-directory. loader.py wraps these
functions into LangChain StructuredTools with SKILL.md-sourced descriptions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)

# Stable folder IDs for the skill-managed document hierarchy
_ANALYSES_FOLDER_ID = "__analytics-agent-analyses"
_ANALYSES_PRIVATE_FOLDER_ID = "__analytics-agent-analyses-private"
_ANALYSES_TEAM_FOLDER_ID = "__analytics-agent-analyses-teams"
_ANALYSES_GLOBAL_FOLDER_ID = "__analytics-agent-analyses-reports"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_folder(doc_id: str, title: str, description: str, parent_urn: str | None) -> str:
    """Ensure a Folder document exists with showInGlobalContext=True; create if not."""
    from datahub.sdk import Document
    from datahub_agent_context.context import get_datahub_client

    client = get_datahub_client()
    doc_urn = f"urn:li:document:{doc_id}"
    try:
        existing = client.entities.get(doc_urn)
        if existing is not None:
            # Ensure DocumentSettings is present even on pre-existing folders
            aspects = getattr(existing, "_aspects", {})
            if "documentSettings" not in aspects:
                _attach_doc_settings(existing, None)
                client.entities.upsert(existing)
            return doc_urn
    except Exception:
        pass

    doc = Document.create_document(
        id=doc_id,
        title=title,
        text=description,
        subtype="Folder",
        parent_document=parent_urn,
        show_in_global_context=True,
    )
    _attach_doc_settings(doc, None)
    try:
        client.entities.upsert(doc)
    except Exception as e:
        logger.warning("Folder upsert may have raced (%s): %s", doc_id, e)
    return doc_urn


def _make_safe_id(text: str, max_length: int = 30) -> str:
    import re

    safe = "".join(c if c.isalnum() else "-" for c in text.lower())[:max_length]
    return re.sub(r"-+", "-", safe).strip("-")


def _get_user_info() -> dict | None:
    from datahub_agent_context.context import get_datahub_client
    from datahub_agent_context.mcp_tools.base import execute_graphql

    client = get_datahub_client()
    query = """
        query getMe { me { corpUser { urn username
            info { displayName fullName firstName lastName }
            editableProperties { displayName }
        }}}
    """
    try:
        result = execute_graphql(client._graph, query=query, variables={}, operation_name="getMe")
        return (result.get("me") or {}).get("corpUser")
    except Exception:
        return None


def _display_name(user_info: dict | None) -> str:
    if not user_info:
        return "Unknown User"
    editable = user_info.get("editableProperties") or {}
    info = user_info.get("info") or {}
    return (
        editable.get("displayName")
        or info.get("displayName")
        or info.get("fullName")
        or f"{info.get('firstName', '')} {info.get('lastName', '')}".strip()
        or user_info.get("username", "Unknown User")
    )


def _attach_doc_settings(doc: object, user_urn: str | None) -> None:
    try:
        from datahub.metadata import schema_classes as models

        actor = user_urn or "urn:li:corpuser:datahub"
        audit = models.AuditStampClass(time=int(datetime.now().timestamp() * 1000), actor=actor)
        doc._set_aspect(models.DocumentSettingsClass(showInGlobalContext=True, lastModified=audit))  # type: ignore[attr-defined]
    except Exception as e:
        logger.debug("Could not attach DocumentSettings: %s", e)


# ---------------------------------------------------------------------------
# publish_analysis — implementation
# ---------------------------------------------------------------------------


_MAX_DOC_CHARS = (
    40_000  # DataHub GraphQL parser limit ~15k grammar tokens ≈ 88K chars; stay well under
)


def _publish_analysis_impl(
    title: str,
    body: str,
    visibility: Literal["private", "team", "global"],
    related_dataset_urns: list[str] | None = None,
    topics: list[str] | None = None,
) -> dict:
    if len(body) > _MAX_DOC_CHARS:
        body = body[:_MAX_DOC_CHARS] + "\n\n_[Content truncated to fit DataHub document limits]_"
    from datahub.sdk import Document
    from datahub_agent_context.context import DataHubContext, get_datahub_client

    from analytics_agent.context.datahub import get_datahub_client as _get_client

    client = _get_client()
    if client is None:
        return {"success": False, "urn": None, "message": "DataHub is not configured."}

    with DataHubContext(client):
        try:
            user_info = _get_user_info()
            user_urn = (user_info or {}).get("urn")

            # Ensure the DataHub-standard root folder exists
            root_urn = _ensure_folder(
                "__system_shared_documents",
                "Shared",
                "Contains shared documents authored through AI agents.",
                None,
            )

            analyses_urn = _ensure_folder(
                _ANALYSES_FOLDER_ID,
                "Analyses",
                "Data analyses published via the AI assistant.",
                root_urn,
            )

            if visibility == "private":
                private_urn = _ensure_folder(
                    _ANALYSES_PRIVATE_FOLDER_ID,
                    "Private",
                    "Analyses visible only to their authors.",
                    analyses_urn,
                )
                username = (user_info or {}).get("username", "unknown")
                name = _display_name(user_info)
                user_folder_id = f"__analytics-agent-analyses-private-{_make_safe_id(username)}"
                parent_urn = _ensure_folder(
                    user_folder_id,
                    name,
                    f"Private analyses for {name}.",
                    private_urn,
                )
            elif visibility == "team":
                parent_urn = _ensure_folder(
                    _ANALYSES_TEAM_FOLDER_ID,
                    "Teams",
                    "Team-shared analyses.",
                    analyses_urn,
                )
            else:
                parent_urn = _ensure_folder(
                    _ANALYSES_GLOBAL_FOLDER_ID,
                    "Reports",
                    "Org-wide analysis reports.",
                    analyses_urn,
                )

            doc_id = f"analytics-agent-analysis-{uuid.uuid4()}"
            tag_urns = [f"urn:li:tag:{t}" for t in (topics or [])] or None

            doc = Document.create_document(
                id=doc_id,
                title=title,
                text=body,
                subtype="Analysis",
                parent_document=parent_urn,
                related_assets=related_dataset_urns or None,
                owners=[user_urn] if user_urn else None,
                tags=tag_urns,
                show_in_global_context=True,
            )
            _attach_doc_settings(doc, user_urn)

            get_datahub_client().entities.upsert(doc)

            doc_urn = f"urn:li:document:{doc_id}"
            logger.info("Published analysis '%s' (%s) → %s", title, visibility, doc_urn)
            return {
                "success": True,
                "urn": doc_urn,
                "message": f"Analysis '{title}' published ({visibility}).",
                "author": _display_name(user_info),
            }

        except Exception as e:
            logger.exception("publish_analysis failed")
            return {"success": False, "urn": None, "message": f"Error: {e}"}


# ---------------------------------------------------------------------------
# save_correction — implementation
# ---------------------------------------------------------------------------


_MAX_DESC_CHARS = 10_000  # descriptions are shorter; keep mutations small


def _save_correction_impl(
    # Mode 1 — entity/field description: provide entity_urn + corrected_description
    entity_urn: str | None = None,
    corrected_description: str | None = None,
    field_path: str | None = None,
    operation: Literal["replace", "append"] = "replace",
    # Mode 2 — update existing doc: provide doc_urn + doc_title + doc_body
    # Mode 3 — create new doc:       provide doc_title + doc_body + parent_doc_urn (no doc_urn)
    doc_urn: str | None = None,
    doc_title: str | None = None,
    doc_body: str | None = None,
    parent_doc_urn: str | None = None,
    related_entity_urns: list[str] | None = None,
) -> dict:
    from analytics_agent.context.datahub import get_datahub_client

    client = get_datahub_client()
    if client is None:
        return {"success": False, "urn": None, "message": "DataHub is not configured."}

    # --- Mode 1: entity / field description ---------------------------------
    if entity_urn is not None:
        if not corrected_description:
            return {
                "success": False,
                "urn": entity_urn,
                "message": "corrected_description is required for entity corrections.",
            }
        if len(corrected_description) > _MAX_DESC_CHARS:
            corrected_description = corrected_description[:_MAX_DESC_CHARS]
        from datahub_agent_context.context import DataHubContext
        from datahub_agent_context.mcp_tools.descriptions import update_description

        with DataHubContext(client):
            try:
                result = update_description(
                    entity_urn=entity_urn,
                    operation=operation,
                    description=corrected_description,
                    column_path=field_path,
                )
                logger.info(
                    "Saved description correction to %s (field=%s, op=%s)",
                    entity_urn,
                    field_path,
                    operation,
                )
                return result
            except Exception as e:
                logger.exception("save_correction (entity) failed")
                return {"success": False, "urn": entity_urn, "message": f"Error: {e}"}

    # --- Modes 2 & 3: document upsert ---------------------------------------
    if not doc_title or not doc_body:
        return {
            "success": False,
            "urn": None,
            "message": "doc_title and doc_body are required for document corrections.",
        }
    if len(doc_body) > _MAX_DOC_CHARS:
        doc_body = (
            doc_body[:_MAX_DOC_CHARS] + "\n\n_[Content truncated to fit DataHub document limits]_"
        )

    from datahub.sdk import Document
    from datahub_agent_context.context import DataHubContext
    from datahub_agent_context.context import get_datahub_client as _ctx_client

    with DataHubContext(client):
        try:
            user_info = _get_user_info()
            user_urn = (user_info or {}).get("urn")

            if doc_urn:
                # Mode 2: update existing doc — extract stable ID from URN
                doc_id = doc_urn.split("urn:li:document:")[-1]
                # Preserve existing parent unless caller explicitly provides one
                parent_urn: str | None
                if parent_doc_urn:
                    parent_urn = parent_doc_urn
                else:
                    try:
                        existing = _ctx_client().entities.get(doc_urn)
                        parent_urn = (
                            getattr(existing, "parent_document", None) if existing else None
                        )
                    except Exception:
                        parent_urn = None
            else:
                # Mode 3: create new doc
                doc_id = f"analytics-agent-correction-{uuid.uuid4()}"
                parent_urn = parent_doc_urn

            doc = Document.create_document(
                id=doc_id,
                title=doc_title,
                text=doc_body,
                subtype="Reference",
                parent_document=parent_urn,
                related_assets=related_entity_urns or None,
                owners=[user_urn] if user_urn else None,
                show_in_global_context=True,
            )
            _attach_doc_settings(doc, user_urn)
            _ctx_client().entities.upsert(doc)

            result_urn = f"urn:li:document:{doc_id}"
            action = "Updated" if doc_urn else "Created"
            logger.info("%s correction doc '%s' → %s", action, doc_title, result_urn)
            return {
                "success": True,
                "urn": result_urn,
                "message": f"{action} document '{doc_title}'.",
                "author": _display_name(user_info),
            }
        except Exception as e:
            logger.exception("save_correction (doc) failed")
            return {"success": False, "urn": doc_urn, "message": f"Error: {e}"}


# ---------------------------------------------------------------------------
# search_business_context — implementation
# ---------------------------------------------------------------------------


def _search_business_context_impl(topic: str) -> dict:
    """Fan out to DataHub docs, glossary terms, domains, and data products for a topic."""
    from analytics_agent.context.datahub import get_datahub_client

    client = get_datahub_client()
    if client is None:
        return {"error": "DataHub is not configured."}

    from datahub_agent_context.context import DataHubContext
    from datahub_agent_context.mcp_tools.documents import search_documents
    from datahub_agent_context.mcp_tools.search import search

    results: dict = {}

    with DataHubContext(client):
        for label, fn, kwargs in [
            ("documentation", search_documents, {"query": topic, "num_results": 5}),
            (
                "glossary_terms",
                search,
                {"query": topic, "filter": "entity_type = glossaryTerm", "num_results": 10},
            ),
            (
                "domains",
                search,
                {"query": topic, "filter": "entity_type = domain", "num_results": 10},
            ),
            (
                "data_products",
                search,
                {"query": topic, "filter": "entity_type = dataProduct", "num_results": 10},
            ),
        ]:
            try:
                results[label] = fn(**kwargs)  # type: ignore[operator]
            except Exception as e:
                results[label] = {"error": str(e)}

    return results


# ---------------------------------------------------------------------------
# Public API used by loader.py
# ---------------------------------------------------------------------------


def build_skill_tools(enabled_skills: set[str]) -> list:
    """Delegate to loader.py — kept here for backwards-compat import paths."""
    from analytics_agent.skills.loader import build_skill_tools as _build

    return _build(enabled_skills)
