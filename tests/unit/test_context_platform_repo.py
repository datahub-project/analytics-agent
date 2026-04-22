import uuid

import pytest
import pytest_asyncio
from analytics_agent.db.models import Base
from analytics_agent.db.repository import ContextPlatformRepo
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


def _make_id() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_upsert_and_get(session):
    repo = ContextPlatformRepo(session)
    row = await repo.upsert(
        id=_make_id(),
        type="datahub",
        name="default",
        label="DataHub",
        config='{"url": "http://localhost:8080", "token": "tok"}',
        source="yaml",
    )
    assert row.name == "default"
    fetched = await repo.get("default")
    assert fetched is not None
    assert fetched.type == "datahub"
    assert fetched.label == "DataHub"


@pytest.mark.asyncio
async def test_list_all(session):
    repo = ContextPlatformRepo(session)
    await repo.upsert(
        id=_make_id(),
        type="datahub",
        name="default",
        label="DataHub",
        config="{}",
        source="yaml",
    )
    await repo.upsert(
        id=_make_id(),
        type="datahub",
        name="staging",
        label="DataHub Staging",
        config="{}",
        source="ui",
    )
    rows = await repo.list_all()
    assert len(rows) == 2
    names = {r.name for r in rows}
    assert names == {"default", "staging"}


@pytest.mark.asyncio
async def test_delete(session):
    repo = ContextPlatformRepo(session)
    await repo.upsert(
        id=_make_id(),
        type="datahub",
        name="default",
        label="DataHub",
        config="{}",
        source="yaml",
    )
    deleted = await repo.delete("default")
    assert deleted is True
    assert await repo.get("default") is None


@pytest.mark.asyncio
async def test_delete_nonexistent(session):
    repo = ContextPlatformRepo(session)
    deleted = await repo.delete("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_upsert_idempotent(session):
    repo = ContextPlatformRepo(session)
    id1 = _make_id()
    await repo.upsert(
        id=id1,
        type="datahub",
        name="default",
        label="Old Label",
        config='{"url": "http://old"}',
        source="yaml",
    )
    await repo.upsert(
        id=id1,
        type="datahub",
        name="default",
        label="New Label",
        config='{"url": "http://new"}',
        source="yaml",
    )
    rows = await repo.list_all()
    assert len(rows) == 1
    assert rows[0].label == "New Label"
    assert "new" in rows[0].config
