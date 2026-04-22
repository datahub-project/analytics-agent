from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import orjson

logger = logging.getLogger(__name__)

CONTEXT_TOOLS: frozenset[str] = frozenset(
    {"search_documents", "grep_documents", "search", "get_entities", "search_business_context"}
)
_CONTEXT_TOOLS = CONTEXT_TOOLS  # backward compat alias

_SCORE_LABELS = {1: "Poor", 2: "Poor", 3: "Fair", 4: "Good", 5: "Excellent"}

_ASSESSMENT_PROMPT = """\
You are assessing the **context quality** of a data assistant conversation.

Context quality measures how well the DataHub knowledge base (documentation, \
definitions, dataset descriptions) supported the agent's work.

Score 1–5:
5 Excellent — DataHub had rich, accurate documentation that fully covered the \
question. Agent applied the definition directly with no improvisation.
4 Good — Useful docs found; definition was mostly complete; agent made one minor \
stated assumption that didn't change the answer meaningfully.
3 Fair — Definition found but incomplete or ambiguous; agent had to fill gaps, \
deviate from the definition, or ask the user for clarification about what the \
context should have made clear.
2 Poor — Docs mostly missing or returned empty results; agent improvised \
substantially and the answer depended heavily on undocumented choices.
1 Very Poor — No useful context; agent expressed significant uncertainty, made \
conflicting assumptions, or produced an answer that contradicts available definitions.

Key signals that push the score DOWN:
- Agent says "the definition doesn't cover this" or "I'll interpret this as…"
- Agent switches columns, tables, or date anchors not mentioned in the definition
- Agent produces a result that varies based on an undocumented assumption
- Agent asks the user to clarify something the glossary/docs should have defined

--- CONTEXT TOOL CALLS AND RESULTS ---
{context_calls}
--- END CONTEXT ---

--- AGENT REASONING (what the agent said and concluded) ---
{agent_reasoning}
--- END REASONING ---

Respond with ONLY valid JSON, no explanation outside it:
{{"score": <1-5>, "label": "<Excellent|Good|Fair|Poor>", "reason": "<one sentence that names the specific gap or strength>"}}"""


async def compute_context_quality(messages: list) -> QualityScore:
    """
    LLM-assessed context quality score (1–5).

    Extracts DataHub context tool calls + results and the agent's own reasoning
    text, then asks a cheap model to judge whether the returned context was
    actually useful and complete — penalising cases where the agent had to
    improvise or deviate from the definition.
    Returns Neutral (3) immediately when no context tool calls have occurred yet.
    """
    context_calls: list[dict] = []
    agent_text_chunks: list[str] = []

    for msg in messages:
        try:
            payload = (
                orjson.loads(msg.payload) if isinstance(msg.payload, (str, bytes)) else msg.payload
            )
        except Exception:
            continue

        if msg.event_type == "TOOL_RESULT":
            tool_name = payload.get("tool_name", "")
            if tool_name not in _CONTEXT_TOOLS:
                continue
            result_raw = payload.get("result", "")
            result_str = str(result_raw)[:800] + ("…" if len(str(result_raw)) > 800 else "")
            context_calls.append(
                {
                    "tool": tool_name,
                    "is_error": bool(payload.get("is_error", False)),
                    "result": result_str,
                }
            )
        elif msg.event_type in ("TEXT", "COMPLETE"):
            text = payload.get("text", "")
            if text:
                agent_text_chunks.append(text[:400])

    if not context_calls:
        return QualityScore(
            score=3, label="Neutral", breakdown={"reason": "No context lookups yet"}
        )

    calls_text = "\n\n".join(
        f"Tool: {c['tool']}\nError: {c['is_error']}\nResult: {c['result']}" for c in context_calls
    )
    # Deduplicate and cap agent reasoning (TEXT events stream token-by-token)
    reasoning = " ".join(dict.fromkeys(agent_text_chunks))[:1200]

    prompt = _ASSESSMENT_PROMPT.format(context_calls=calls_text, agent_reasoning=reasoning)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from analytics_agent.agent.llm import get_quality_llm

        llm = get_quality_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content="You assess data assistant context quality. Reply only with the requested JSON."
                ),
                HumanMessage(content=prompt),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = next(
                (b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text"),
                "",
            )
        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        score = max(1, min(5, int(data.get("score", 3))))
        label = data.get("label", _SCORE_LABELS[score])
        reason = data.get("reason", "")
        return QualityScore(score=score, label=label, breakdown={"reason": reason})
    except Exception as exc:
        logger.warning("Context quality LLM assessment failed: %s", exc)
        return QualityScore(
            score=3, label="Neutral", breakdown={"reason": "Assessment unavailable"}
        )


@dataclass
class QualityScore:
    score: int  # 1–5
    label: str
    breakdown: dict
