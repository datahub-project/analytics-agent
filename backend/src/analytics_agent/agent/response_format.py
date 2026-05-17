"""Typed final-response schema for the parent agent.

deepagents lets us pass a `response_format` to `create_deep_agent`. When
set, the model emits its final answer through a structured-output tool
call whose args conform to this schema, and the graph state's
`structured_response` field holds the parsed object.

We keep the schema narrow on purpose:

- `summary`: a short prose answer the chat already streams. Storing it
  here too lets the frontend render exactly what the model committed
  to without re-parsing the streamed buffer.
- `follow_ups`: zero or more next-question suggestions. The agent
  understands the analysis context better than any pre-canned chip
  list, so letting it propose the next step is the highest-value
  structured field for an analytics UX.

Everything else (SQL, charts, tool results) already flows through
dedicated SSE events — adding more fields here would either duplicate
that data or constrain the agent to a rigid shape that hurts
free-form replies.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalystResponse(BaseModel):
    """Final response from the analytics agent."""

    summary: str = Field(
        description=(
            "The short prose answer to the user's question. Same content "
            "you would have written in plain text — keep it concise. "
            "Don't restate the data; the chat already shows it."
        ),
    )
    # default_factory=list keeps the JSON schema as a plain `array` rather
    # than `anyOf [array, null]`. Bedrock has a cap on union-typed
    # parameters across the tool surface (16) and every Optional[T] burns
    # one slot. Empty list is the natural "no suggestions" state.
    follow_ups: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 3 short questions the user might naturally ask next, "
            "phrased as they would type them. Examples: 'Break this down "
            "by region', 'Show the same metric for last quarter', "
            "'Which tables feed this number?'. Leave empty when there's "
            "no obvious next step or the user's question was definitively "
            "answered with no natural follow-up."
        ),
    )
