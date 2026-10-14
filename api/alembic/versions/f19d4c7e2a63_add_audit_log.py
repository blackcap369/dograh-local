"""add audit_log

Revision ID: f19d4c7e2a63
Revises: e57c3d9a8b26
Create Date: 2026-10-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f19d4c7e2a63"
down_revision: Union[str, None] = "e57c3d9a8b26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The agency audit log: one append-only row per destructive or
    # management action on the Creative surface (who did what, to which
    # business, when). Append-only by design -- no update or delete paths
    # exist in the application.
    #
    # actor_user_id and organization_id are SET NULL, not CASCADE: deleting
    # an account or purging a business must not destroy the history of what
    # happened. actor_email and the business label ride in `detail` so every
    # row stays readable even after the referenced rows are gone.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created", table_name="audit_log")
    op.drop_table("audit_log")
