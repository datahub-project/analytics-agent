"""SKILL.md → tool wrappers + skill source paths for SkillsMiddleware.

Skills live under `library/<skill-name>/SKILL.md`. The agent discovers them
through `deepagents.middleware.SkillsMiddleware` (progressive disclosure: the
descriptions appear in the system prompt, bodies are loaded on demand). A
subset of skills also have Python implementations that we expose as
LangChain tools — see `build_skill_tools` below.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent
SKILLS_LIBRARY_DIR = _SKILLS_DIR / "library"


def _parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    """Split SKILL.md into (frontmatter_dict, body_markdown)."""
    if not text.startswith("---"):
        return {}, text

    end = text.index("---", 3)
    fm_text = text[3:end].strip()
    body = text[end + 3 :].strip()

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse SKILL.md frontmatter: %s", e)
        fm = {}

    return fm, body


def _load_skill_md(skill_dir_name: str) -> tuple[dict[str, Any], str] | None:
    """Read and parse a skill's SKILL.md from library/<skill_dir_name>/SKILL.md."""
    skill_file = SKILLS_LIBRARY_DIR / skill_dir_name / "SKILL.md"
    if not skill_file.exists():
        logger.warning("Skill '%s' has no SKILL.md at %s", skill_dir_name, skill_file)
        return None
    return _parse_skill_md(skill_file.read_text())


def _build_tool(skill_dir_name: str, impl_fn: Any, *, tool_name: str) -> BaseTool | None:
    """Wrap a Python impl as a StructuredTool with description from SKILL.md."""
    parsed = _load_skill_md(skill_dir_name)
    if parsed is None:
        return None
    fm, _body = parsed
    description = str(fm.get("description", "")).strip().replace("\n", " ")
    tool = StructuredTool.from_function(func=impl_fn, name=tool_name, description=description)
    logger.info("Loaded skill tool '%s' from %s/SKILL.md", tool_name, skill_dir_name)
    return tool


def build_always_on_skill_tools() -> list[BaseTool]:
    """Tools backed by skills that are always active (read-only)."""
    from analytics_agent.skills import datahub_skills as _impl

    tools: list[BaseTool] = []
    tool = _build_tool(
        "search-business-context",
        _impl._search_business_context_impl,
        tool_name="search_business_context",
    )
    if tool is not None:
        tools.append(tool)
    return tools


# Map opt-in skill IDs (as stored in `enabled_mutation_tools` setting) to
# (skill_dir_name, impl_attribute, tool_name) triples. Tool names use snake_case
# to match prior agent-facing identifiers; skill dir names are hyphenated to
# satisfy the Agent Skills specification.
_OPT_IN_TOOL_SPECS: dict[str, tuple[str, str, str]] = {
    "publish_analysis": ("publish-analysis", "_publish_analysis_impl", "publish_analysis"),
    "save_correction": ("save-correction", "_save_correction_impl", "save_correction"),
}


def build_skill_tools(enabled_skills: set[str]) -> list[BaseTool]:
    """For each enabled opt-in skill, expose its Python impl as a LangChain tool."""
    from analytics_agent.skills import datahub_skills as _impl

    tools: list[BaseTool] = []
    for skill_id in enabled_skills:
        spec = _OPT_IN_TOOL_SPECS.get(skill_id)
        if spec is None:
            logger.warning("No tool wrapping defined for skill '%s'", skill_id)
            continue
        skill_dir, impl_attr, tool_name = spec
        impl = getattr(_impl, impl_attr, None)
        if impl is None:
            logger.warning("Missing impl '%s' for skill '%s'", impl_attr, skill_id)
            continue
        tool = _build_tool(skill_dir, impl, tool_name=tool_name)
        if tool is not None:
            tools.append(tool)
    return tools


def build_skill_sources(enabled_mutations: set[str] | None = None) -> list[str]:
    """Return source paths for SkillsMiddleware.

    Always includes the full library so descriptions are discoverable. Body
    contents are loaded on demand by the middleware (progressive disclosure),
    so unused skills cost only their description in the system prompt.

    The `enabled_mutations` argument is accepted for parity with the tool
    builders but does not currently filter sources — mutation skills become
    actually executable only because their corresponding tools are absent
    when the user has not enabled them.
    """
    return [str(SKILLS_LIBRARY_DIR)]
