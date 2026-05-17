"""`ask_user` — a tool that pauses the agent to ask the user a structured question.

Mechanics:
  - The agent calls `ask_user(question, options?)`. The HITL middleware
    intercepts, the frontend renders an inline card with the question
    plus optional choice buttons + a free-text input.
  - The user submits an answer. The frontend POSTs an "edit" decision
    whose `edited_action.args` includes the submitted `answer` key.
  - The tool body then runs with the answer baked in and returns it
    verbatim — the agent reads its next turn's `task` ToolMessage as
    the user's reply.
  - On reject ("Skip"), the harness returns the reject message to the
    agent; it should pivot rather than re-asking.

Use this for SHORT, STRUCTURED questions where a button or one-line
text reply is sufficient. For anything open-ended or multi-paragraph,
the agent should respond with plain text and stop — the user will reply
in the next turn naturally.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def ask_user(question: str, options: list[str] = [], answer: str = "") -> str:  # noqa: B006
    """Ask the user a structured question and return their answer as the tool result.

    Use for short, structured prompts — pick one of N choices, yes/no, or
    a one-line free-form reply. The harness pauses execution and shows
    the user an approval card; their submitted text becomes this tool's
    return value, which you'll see in the next turn.

    Do NOT use for open-ended or multi-paragraph questions — for those,
    just write the question in plain text and stop. The user replies
    in the next turn naturally.

    Args:
        question: The question to put to the user. Be concise and direct.
        options: Optional list of suggested replies, rendered as buttons
            in the UI alongside a free-text input. Two to five works best.
            Pass [] when you want a free-text answer only.
        answer: Filled in by the harness when the user submits — do NOT
            populate this yourself. Default empty so a reject lands as
            "User declined to answer."
    """
    # Note: options=[] (not None) intentionally — keeping the JSON schema
    # as a plain `array` rather than `anyOf [array, null]`. Bedrock has a
    # cap on union-typed parameters across the tool surface (16) and
    # every Optional[T] burns one slot.
    if not answer:
        return "User declined to answer."
    return answer
