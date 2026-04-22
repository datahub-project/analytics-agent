"""Add quality score columns to conversations

Revision ID: 004
Revises: 003
Create Date: 2026-04-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("quality_score", sa.Integer(), nullable=True))
    op.add_column("conversations", sa.Column("quality_label", sa.String(255), nullable=True))
    op.add_column("conversations", sa.Column("quality_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "quality_reason")
    op.drop_column("conversations", "quality_label")
    op.drop_column("conversations", "quality_score")
