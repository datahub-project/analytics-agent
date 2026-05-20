import pathlib
import re
from datetime import date

_DEFAULT_PROMPT_PATH = pathlib.Path(__file__).parent / "system_prompt.md"


# Matches `<!-- if:<flag> -->\n...\n<!-- endif -->` blocks (newline-tolerant
# on both ends). Used to gate prompt sections on runtime feature flags
# (e.g. the sandbox `execute` tool only being available when
# `ENABLE_PYTHON_SANDBOX=1`).
_CONDITIONAL_BLOCK_RE = re.compile(
    r"[ \t]*<!--\s*if:(?P<flag>[a-zA-Z0-9_-]+)\s*-->\n?"
    r"(?P<body>.*?)"
    r"\n?[ \t]*<!--\s*endif\s*-->\n?",
    re.DOTALL,
)


def get_prompt_template() -> str:
    return _DEFAULT_PROMPT_PATH.read_text()


def _apply_conditional_blocks(template: str, flags: dict[str, bool]) -> str:
    """Strip or keep `<!-- if:<flag> -->...<!-- endif -->` blocks.

    Keep the body when `flags[flag]` is truthy; drop the entire block
    (markers + body) otherwise. Unknown flags default to False so an
    unhandled `if:` block disappears rather than silently leaking into
    the prompt.
    """
    def _sub(match: re.Match[str]) -> str:
        flag = match.group("flag")
        if flags.get(flag, False):
            return match.group("body")
        return ""

    return _CONDITIONAL_BLOCK_RE.sub(_sub, template)


def build_system_prompt(
    engine_name: str,
    enabled_skills: set[str] | None = None,  # accepted for caller compat; unused
) -> str:
    """Render the base system prompt.

    Conditional `<!-- if:<flag> -->...<!-- endif -->` blocks in the
    template are stripped based on runtime feature flags. Currently
    supported flags:
      - `sandbox` — set when `settings.enable_python_sandbox` is true.
        Gates the `execute` tool / scripting guidance.

    Skill bodies are no longer injected here — `SkillsMiddleware` handles
    progressive disclosure. The `enabled_skills` parameter is kept so callers
    don't break, but is not consumed.
    """
    from analytics_agent.config import settings

    today = date.today().strftime("%B %d, %Y")
    flags = {"sandbox": bool(settings.enable_python_sandbox)}
    template = _apply_conditional_blocks(get_prompt_template(), flags)
    # str.replace, not str.format — the shipped prompt embeds jq / json
    # snippets like `{has_owner: ...}` that look like format placeholders
    # and would raise KeyError. Replace is dumber but safe.
    return template.replace("{engine_name}", engine_name).replace("{today}", today)
