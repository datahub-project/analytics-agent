import pathlib
from datetime import date

_DEFAULT_PROMPT_PATH = pathlib.Path(__file__).parent / "system_prompt.md"


def get_prompt_template() -> str:
    return _DEFAULT_PROMPT_PATH.read_text()


def build_system_prompt(
    engine_name: str,
    enabled_skills: set[str] | None = None,
) -> str:
    from analytics_agent.skills.loader import (
        get_improve_context_prompt_section,
        get_search_business_context_section,
        get_skill_system_prompt_section,
    )

    today = date.today().strftime("%B %d, %Y")
    base = get_prompt_template().format(engine_name=engine_name, today=today)

    # Always inject always-on meta-skills
    base = base + get_search_business_context_section()
    base = base + get_improve_context_prompt_section()

    if enabled_skills:
        skills_section = get_skill_system_prompt_section(enabled_skills)
        if skills_section:
            base = base + skills_section

    return base
