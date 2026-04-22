from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from langchain_core.tools import BaseTool


class QueryEngine(ABC):
    """
    Abstraction over a SQL query backend.
    Each implementation exposes exactly 4 LangChain tools with stable names:
      - execute_sql
      - list_tables
      - get_schema
      - preview_table
    """

    name: str

    #: Mapping of *friendly* secret key (sent over the wire in
    #: ``body.secrets``) -> the environment variable the engine reads at
    #: runtime.
    secret_env_vars: ClassVar[dict[str, str]] = {}

    @abstractmethod
    def get_tools(self) -> list[BaseTool]: ...

    async def aclose(self) -> None:
        pass
