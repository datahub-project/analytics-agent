from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


class ContextPlatform(ABC):
    """
    Abstraction over a context/metadata platform.

    Each platform instance owns its enabled/disabled tool state.
    Callers just call get_tools() — no external filtering needed.

    Tool state is loaded from the DB at construction time via build_platform()
    and stored on the instance, keeping the OO boundary clean.
    """

    name: str
    disabled_tools: set[str]
    include_mutations: bool

    @abstractmethod
    async def get_tools(self) -> list[BaseTool]: ...
