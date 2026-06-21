from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from analytics_agent.config import settings

_engine = None
_AsyncSessionFactory = None


def _get_engine():
    global _engine, _AsyncSessionFactory
    if _engine is None:
        url = settings.database_url
        is_sqlite = "sqlite" in url
        is_asyncpg = "asyncpg" in url
        connect_args: dict = {}
        if is_sqlite:
            connect_args = {"check_same_thread": False}
        elif is_asyncpg and settings.db_command_timeout > 0:
            # Bound every statement (including pool_pre_ping's SELECT 1) so a
            # connection wedged by task cancellation fails fast instead of
            # hanging the next checkout forever.
            connect_args = {"command_timeout": settings.db_command_timeout}
        kwargs: dict = {
            "echo": settings.log_level == "DEBUG",
            "connect_args": connect_args,
        }
        if not is_sqlite:
            kwargs.update(
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_recycle=settings.db_pool_recycle,
                pool_pre_ping=settings.db_pool_pre_ping,
                pool_timeout=settings.db_pool_timeout,
            )
        _engine = create_async_engine(url, **kwargs)
        _AsyncSessionFactory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _get_session_factory():
    _get_engine()
    return _AsyncSessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        yield session
