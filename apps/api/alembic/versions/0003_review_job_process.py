"""add review job process metadata

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the operating-system process associated with a running job."""

    with op.batch_alter_table("review_jobs") as batch_op:
        batch_op.add_column(sa.Column("process_pid", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "process_pid_positive", "process_pid IS NULL OR process_pid > 0"
        )


def downgrade() -> None:
    """Remove persisted process metadata."""

    with op.batch_alter_table("review_jobs") as batch_op:
        batch_op.drop_constraint(op.f("ck_review_jobs_process_pid_positive"), type_="check")
        batch_op.drop_column("process_pid")
