"""add review job idempotency key

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist one opaque idempotency key per company and review request."""

    with op.batch_alter_table("review_jobs") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint(
            "uq_review_jobs_company_idempotency", ["company_id", "idempotency_key"]
        )


def downgrade() -> None:
    """Remove persisted review request idempotency."""

    with op.batch_alter_table("review_jobs") as batch_op:
        batch_op.drop_constraint("uq_review_jobs_company_idempotency", type_="unique")
        batch_op.drop_column("idempotency_key")
