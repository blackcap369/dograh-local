"""add run_failure_alerts

Revision ID: d93b7a2e5f18
Revises: c8a42e6f9b13
Create Date: 2026-10-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d93b7a2e5f18"
down_revision: Union[str, None] = "c8a42e6f9b13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Failed-run alerts (V2.6): one OPEN alert per (organization, workflow).
    # The partial unique index is the debounce -- a second failed run bumps
    # the existing row instead of creating another, so a dead phone number
    # cannot spam the owner's dashboard. A successful run resolves the alert
    # (resolved_at set), which also frees the slot for a future alert.
    op.create_table(
        "run_failure_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_failed_run_id", sa.Integer(), nullable=True),
        sa.Column("last_failed_run_id", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_run_failure_alerts_org",
        "run_failure_alerts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_run_failure_alerts_open",
        "run_failure_alerts",
        ["organization_id", "workflow_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL AND acknowledged_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_run_failure_alerts_open", table_name="run_failure_alerts")
    op.drop_index("ix_run_failure_alerts_org", table_name="run_failure_alerts")
    op.drop_table("run_failure_alerts")
