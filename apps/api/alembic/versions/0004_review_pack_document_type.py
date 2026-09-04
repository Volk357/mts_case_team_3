"""add review pack document type

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add explicit public document type while preserving existing pack rows."""

    with op.batch_alter_table("review_pack_references") as batch_op:
        batch_op.add_column(
            sa.Column(
                "document_type",
                sa.String(length=100),
                nullable=False,
                server_default="technical_specification",
            )
        )


def downgrade() -> None:
    """Remove explicit Review Pack document type."""

    with op.batch_alter_table("review_pack_references") as batch_op:
        batch_op.drop_column("document_type")
