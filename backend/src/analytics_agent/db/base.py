from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from analytics_agent.config import settings

_engine = None
_AsyncSessionFactory = None


def _get_engine():
    global _engine, _AsyncSessionFactory
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.log_level == "DEBUG",
            connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        )
        _AsyncSessionFactory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _get_session_factory():
    _get_engine()
    return _AsyncSessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        yield session
