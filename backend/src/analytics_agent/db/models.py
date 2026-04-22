from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from analytics_agent.db.types import EncryptedJSON


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    """Key-value store for app-level settings (prompt, display, tool toggles)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Integration(Base):
    """A named data-source connection (Snowflake, MySQL, PostgreSQL, …)."""

    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # engine_name
    type: Mapped[str] = mapped_column(String, nullable=False)  # snowflake | mysql | sqlalchemy
    label: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON connection params
    source: Mapped[str] = mapped_column(String, nullable=False)  # yaml | ui
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    credential: Mapped[IntegrationCredential | None] = relationship(
        "IntegrationCredential",
        back_populates="integration",
        cascade="all, delete-orphan",
        uselist=False,
    )


class IntegrationCredential(Base):
    """Auth credential for a single integration (SSO token, OAuth token, PAT, …)."""

    __tablename__ = "integration_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    integration_name: Mapped[str] = mapped_column(
        String, ForeignKey("integrations.name", ondelete="CASCADE"), nullable=False, unique=True
    )
    auth_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # sso_externalbrowser | oauth | pat
    username: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # display name of authed user
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted token/secret
    metadata_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # encrypted JSON (refresh token, etc.)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    integration: Mapped[Integration] = relationship("Integration", back_populates="credential")


class ContextPlatform(Base):
    """A named context platform connection (DataHub, …)."""

    __tablename__ = "context_platforms"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # datahub
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # default | staging
    label: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[str] = mapped_column(EncryptedJSON, nullable=False)  # JSON: {url, token}
    source: Mapped[str] = mapped_column(String, nullable=False)  # yaml | ui
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New Conversation")
    engine_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Context quality — computed once after each turn, stored for instant reads
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_label: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.sequence",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # 'user' | 'assistant'
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
