import pathlib
from datetime import date

_DEFAULT_PROMPT_PATH = pathlib.Path(__file__).parent / "system_prompt.md"


def get_prompt_template() -> str:
    return _DEFAULT_PROMPT_PATH.read_text()


def build_system_prompt(
    engine_name: str,
    enabled_skills: set[str] | None = None,  # accepted for caller compat; unused
) -> str:
    """Render the base system prompt.

    Skill bodies are no longer injected here — `SkillsMiddleware` handles
    progressive disclosure. The `enabled_skills` parameter is kept so callers
    don't break, but is not consumed.
    """
    today = date.today().strftime("%B %d, %Y")
    # str.replace, not str.format — the shipped prompt embeds jq / json
    # snippets like `{has_owner: ...}` that look like format placeholders
    # and would raise KeyError. Replace is dumber but safe.
    return (
        get_prompt_template()
        .replace("{engine_name}", engine_name)
        .replace("{today}", today)
    )
