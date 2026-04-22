"""
SKILL.md loader for Analytics Agent skills.

Each skill lives in skills/<skill-name>/SKILL.md following the Agent Skills
Specification: YAML frontmatter (name, description, allowed-tools, …) +
markdown body with step-by-step instructions.

At graph-build time:
  - Frontmatter description  →  LangChain tool .description (routing)
  - Markdown body            →  injected into system prompt (instructions)
  - Python impl in datahub_skills.py  →  tool execution layer
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent


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


def _load_skill_md(skill_name: str) -> tuple[dict[str, Any], str] | None:
    """Read and parse a skill's SKILL.md. Returns None if not found."""
    skill_dir = _SKILLS_DIR / skill_name
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        logger.warning("Skill '%s' has no SKILL.md at %s", skill_name, skill_file)
        return None
    return _parse_skill_md(skill_file.read_text())


def _build_tool_from_skill(folder_name: str, impl_fn: Any) -> BaseTool | None:
    """Load a SKILL.md and wrap its impl as a StructuredTool. Returns None on failure."""
    parsed = _load_skill_md(folder_name)
    if parsed is None:
        return None
    fm, _body = parsed
    tool_name = fm.get("name", folder_name)
    description = str(fm.get("description", "")).strip().replace("\n", " ")
    tool = StructuredTool.from_function(
        func=impl_fn,
        name=tool_name,
        description=description,
    )
    logger.info("Loaded skill tool '%s' from SKILL.md", tool_name)
    return tool


def build_always_on_skill_tools() -> list[BaseTool]:
    """Return skills that are always active, regardless of user-enabled mutations."""
    from analytics_agent.skills import datahub_skills as _impl

    tools: list[BaseTool] = []
    tool = _build_tool_from_skill("search-business-context", _impl._search_business_context_impl)
    if tool is not None:
        tools.append(tool)
    return tools


def build_skill_tools(enabled_skills: set[str]) -> list[BaseTool]:
    """
    For each enabled skill, load its SKILL.md and return a LangChain tool
    whose description comes from the frontmatter and whose implementation
    comes from datahub_skills.py.
    """
    from analytics_agent.skills import datahub_skills as _impl

    _implementations: dict[str, Any] = {
        "publish-analysis": _impl._publish_analysis_impl,
        "save-correction": _impl._save_correction_impl,
    }
    _name_map: dict[str, str] = {
        "publish_analysis": "publish-analysis",
        "save_correction": "save-correction",
    }

    tools: list[BaseTool] = []
    for skill_id in enabled_skills:
        folder_name = _name_map.get(skill_id, skill_id)
        impl = _implementations.get(folder_name)
        if impl is None:
            logger.warning("No implementation found for skill '%s'", skill_id)
            continue
        tool = _build_tool_from_skill(folder_name, impl)
        if tool is not None:
            tools.append(tool)

    return tools


def get_improve_context_prompt_section() -> str:
    """Return the always-on /improve-context meta-skill section for the system prompt."""
    parsed = _load_skill_md("improve-context")
    if parsed is None:
        return ""
    _fm, body = parsed
    return f"\n\n## Meta-Skill: /improve-context\n\n{body}"


def get_search_business_context_section() -> str:
    """Return the always-on search-business-context skill section for the system prompt."""
    parsed = _load_skill_md("search-business-context")
    if parsed is None:
        return ""
    _fm, body = parsed
    return f"\n\n## Skill: search_business_context\n\n{body}"


def get_skill_system_prompt_section(enabled_skills: set[str]) -> str:
    """
    Return a markdown section to inject into the system prompt containing
    the full SKILL.md body for each enabled skill.

    Empty string if no skills are enabled.
    """
    _name_map: dict[str, str] = {
        "publish_analysis": "publish-analysis",
        "save_correction": "save-correction",
    }

    sections: list[str] = []
    for skill_id in sorted(enabled_skills):
        folder_name = _name_map.get(skill_id, skill_id)
        parsed = _load_skill_md(folder_name)
        if parsed is None:
            continue
        fm, body = parsed
        tool_name = fm.get("name", skill_id)
        sections.append(f"### Skill: {tool_name}\n\n{body}")

    if not sections:
        return ""

    return (
        "\n\n## Write-Back Skills\n\n"
        "The following skills are enabled. Follow their instructions exactly "
        "when the relevant situation arises.\n\n" + "\n\n---\n\n".join(sections)
    )
