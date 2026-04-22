from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from analytics_agent.db.models import (
    ContextPlatform,
    Conversation,
    Integration,
    IntegrationCredential,
    Message,
    Setting,
)


class ConversationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, conversation_id: str) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def create(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.commit()
        await self._session.refresh(conversation)
        return conversation

    async def update_title(self, conversation_id: str, title: str) -> None:
        conv = await self.get(conversation_id)
        if conv:
            conv.title = title
            await self._session.commit()

    async def delete(self, conversation_id: str) -> bool:
        conv = await self._session.get(Conversation, conversation_id)
        if not conv:
            return False
        await self._session.delete(conv)
        await self._session.commit()
        return True

    async def update_quality(
        self, conversation_id: str, score: int, label: str, reason: str
    ) -> None:
        conv = await self._session.get(Conversation, conversation_id)
        if conv:
            conv.quality_score = score
            conv.quality_label = label
            conv.quality_reason = reason
            await self._session.commit()

    async def touch(self, conversation_id: str) -> None:
        conv = await self._session.get(Conversation, conversation_id)
        if conv:
            from datetime import datetime

            conv.updated_at = datetime.now(UTC)
            await self._session.commit()


class MessageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_sequence(self, conversation_id: str) -> int:
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count()).where(Message.conversation_id == conversation_id)
        )
        return result.scalar() or 0

    async def create(self, message: Message) -> Message:
        self._session.add(message)
        await self._session.commit()
        return message

    async def list_for_conversation(self, conversation_id: str) -> list[Message]:
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence)
        )
        return list(result.scalars().all())


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        result = await self._session.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def set(self, key: str, value: str | None) -> None:
        row = await self._session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value, updated_at=datetime.now(UTC))
            self._session.add(row)
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def delete(self, key: str) -> None:
        row = await self._session.get(Setting, key)
        if row:
            await self._session.delete(row)
            await self._session.commit()


class IntegrationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Integration]:
        result = await self._session.execute(
            select(Integration)
            .options(selectinload(Integration.credential))
            .order_by(Integration.created_at)
        )
        return list(result.scalars().all())

    async def get(self, name: str) -> Integration | None:
        result = await self._session.execute(
            select(Integration)
            .where(Integration.name == name)
            .options(selectinload(Integration.credential))
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, id: str, name: str, type: str, label: str, config: str, source: str
    ) -> Integration:
        row = await self._session.get(Integration, id)
        if row is None:
            # Also check by name
            existing = await self.get(name)
            if existing:
                existing.label = label
                existing.config = config
                existing.updated_at = datetime.now(UTC)
                await self._session.commit()
                return existing
            row = Integration(
                id=id,
                name=name,
                type=type,
                label=label,
                config=config,
                source=source,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._session.add(row)
        else:
            row.label = label
            row.config = config
            row.updated_at = datetime.now(UTC)
        await self._session.commit()
        return row

    async def delete(self, name: str) -> bool:
        row = await self.get(name)
        if not row:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True


class ContextPlatformRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[ContextPlatform]:
        result = await self._session.execute(
            select(ContextPlatform).order_by(ContextPlatform.created_at)
        )
        return list(result.scalars().all())

    async def get(self, name: str) -> ContextPlatform | None:
        result = await self._session.execute(
            select(ContextPlatform).where(ContextPlatform.name == name)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, id: str, type: str, name: str, label: str, config: str, source: str
    ) -> ContextPlatform:
        row = await self._session.get(ContextPlatform, id)
        if row is None:
            existing = await self.get(name)
            if existing:
                existing.label = label
                existing.config = config
                existing.updated_at = datetime.now(UTC)
                await self._session.commit()
                return existing
            row = ContextPlatform(
                id=id,
                type=type,
                name=name,
                label=label,
                config=config,
                source=source,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._session.add(row)
        else:
            row.label = label
            row.config = config
            row.updated_at = datetime.now(UTC)
        await self._session.commit()
        return row

    async def delete(self, name: str) -> bool:
        row = await self.get(name)
        if not row:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True


class CredentialRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, integration_name: str) -> IntegrationCredential | None:
        result = await self._session.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_name == integration_name
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        id: str,
        integration_name: str,
        auth_type: str,
        username: str | None = None,
        secret_enc: str | None = None,
        metadata_enc: str | None = None,
        expires_at: datetime | None = None,
    ) -> IntegrationCredential:
        row = await self.get(integration_name)
        now = datetime.now(UTC)
        if row is None:
            row = IntegrationCredential(
                id=id,
                integration_name=integration_name,
                auth_type=auth_type,
                username=username,
                secret_enc=secret_enc,
                metadata_enc=metadata_enc,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.auth_type = auth_type
            row.username = username
            row.secret_enc = secret_enc
            row.metadata_enc = metadata_enc
            row.expires_at = expires_at
            row.updated_at = now
        await self._session.commit()
        return row

    async def delete(self, integration_name: str) -> None:
        row = await self.get(integration_name)
        if row:
            await self._session.delete(row)
            await self._session.commit()
