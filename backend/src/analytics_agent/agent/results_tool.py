from __future__ import annotations

import logging
import uuid
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Side-channel: keyed by result_id so streaming.py can fetch the payload
# without the model ever seeing the full JSON.
_pending_results: dict[str, dict] = {}


class ProposalResultItem(BaseModel):
    id: str
    kind: Literal["new_doc", "update_doc", "fix_description"]
    title: str
    status: Literal["success", "error"]
    urn: str | None = None
    error: str | None = None


@tool
async def report_proposal_results(
    results: list[dict],
) -> str:
    """
    Report the outcomes of writing approved proposals back to DataHub.
    Call this ONCE after all save_correction calls have completed in Step 5
    of the /improve-context workflow. The UI will render a results card —
    do NOT write any additional summary text after calling this tool.

    Args:
        results: List of result dicts, each with:
            - id: proposal id (matches the id from present_proposals)
            - kind: one of "new_doc", "update_doc", "fix_description"
            - title: proposal title
            - status: "success" or "error"
            - urn: the URN of the created/updated entity (set on success)
            - error: error message (set on error)

    Example:
        report_proposal_results(results=[
            {"id": "1", "kind": "new_doc", "title": "Revenue Metrics Guide",
             "status": "success", "urn": "urn:li:corpUser:..."},
            {"id": "3", "kind": "fix_description", "title": "orders.status column",
             "status": "error", "error": "Permission denied"},
        ])
    """
    try:
        validated = [ProposalResultItem(**r) for r in results]
    except Exception as e:
        return f"report_proposal_results: invalid results format — {e}"

    result_id = str(uuid.uuid4())
    _pending_results[result_id] = {
        "results": [r.model_dump() for r in validated],
    }

    successes = sum(1 for r in validated if r.status == "success")
    return (
        f"RESULTS_READY:{result_id} "
        f"({successes}/{len(validated)} succeeded)"
    )
