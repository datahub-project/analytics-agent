from __future__ import annotations

import logging
import uuid
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Side-channel: keyed by prop_id so streaming.py can fetch the payload
# without the model ever seeing the full JSON.
_pending_proposals: dict[str, dict] = {}


class ProposalItem(BaseModel):
    id: str
    kind: Literal["new_doc", "update_doc", "fix_description"]
    title: str
    detail: str
    target: dict | None = None  # e.g. {"urn": "...", "field_path": "..."}


@tool
async def present_proposals(
    prompt: str,
    proposals: list[dict],
) -> str:
    """
    Present a list of improvement proposals to the user for review and selection.
    Call this at the end of Step 3 of the /improve-context workflow, after drafting
    proposals. The UI will render a card with checkboxes — do NOT print a markdown
    list yourself.

    Args:
        prompt: Short framing sentence shown above the proposals
                (e.g. "I found 3 improvements based on our conversation.")
        proposals: List of proposal dicts, each with:
            - id: unique string identifier (e.g. "1", "2", "3")
            - kind: one of "new_doc", "update_doc", "fix_description"
            - title: short title for the proposal
            - detail: 1-2 sentence description of what to add/change
            - target: optional dict with "urn" and/or "field_path" for existing entities

    Example:
        present_proposals(
            prompt="Based on our conversation, here are 3 documentation improvements:",
            proposals=[
                {"id": "1", "kind": "new_doc", "title": "Revenue Metrics Guide",
                 "detail": "Define net ARR vs gross ARR and specify the revenue table."},
                {"id": "2", "kind": "fix_description", "title": "orders.status column",
                 "detail": "Current description is empty. Values: pending, confirmed, shipped.",
                 "target": {"urn": "urn:li:dataset:...", "field_path": "status"}},
            ]
        )
    """
    try:
        validated = [ProposalItem(**p) for p in proposals]
    except Exception as e:
        return f"present_proposals: invalid proposals format — {e}"

    prop_id = str(uuid.uuid4())
    _pending_proposals[prop_id] = {
        "prompt": prompt,
        "proposals": [p.model_dump() for p in validated],
    }

    return (
        f"PROPOSALS_READY:{prop_id} "
        f"({len(validated)} proposals; awaiting user selection)"
    )
