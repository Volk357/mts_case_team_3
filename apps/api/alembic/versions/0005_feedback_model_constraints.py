"""constrain finding feedback model

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enforce the closed decision vocabulary and bounded optional fields."""

    with op.batch_alter_table("finding_feedback") as batch_op:
        batch_op.create_check_constraint(
            "decision_valid",
            "decision IN ('accepted', 'false_positive', 'allowed_exception', "
            "'already_described', 'not_relevant')",
        )
        batch_op.create_check_constraint(
            "actor_key_length",
            "length(actor_key) >= 1 AND length(actor_key) <= 255",
        )
        batch_op.create_check_constraint(
            "comment_length",
            "comment IS NULL OR length(comment) <= 4000",
        )


def downgrade() -> None:
    """Remove finding feedback value constraints."""

    with op.batch_alter_table("finding_feedback") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_finding_feedback_comment_length"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_finding_feedback_actor_key_length"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_finding_feedback_decision_valid"),
            type_="check",
        )
