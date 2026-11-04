"""add deletion_requests

Revision ID: e83b9f2c6d47
Revises: d74e0c8b1a55
Create Date: 2026-10-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e83b9f2c6d47"
down_revision: Union[str, None] = "d74e0c8b1a55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Staff deletes are requests, not deletions: the row is the whole flow.
    # A staff member asks, the owner sees it in the access page, and only an
    # approval reaches the (still impact-guarded) delete. See
    # DeletionRequestModel for the FK-ondelete choices.
    op.create_table(
        "deletion_requests",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_deletion_requests_org", "deletion_requests", ["organization_id"]
    )
    op.create_index(
        "ix_deletion_requests_status", "deletion_requests", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_deletion_requests_status", table_name="deletion_requests")
    op.drop_index("ix_deletion_requests_org", table_name="deletion_requests")
    op.drop_table("deletion_requests")
