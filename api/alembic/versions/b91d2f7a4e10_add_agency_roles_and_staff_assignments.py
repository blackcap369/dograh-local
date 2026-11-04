"""add users.agency_role and staff_client_assignments

Revision ID: b91d2f7a4e10
Revises: c4e8a17d3b92
Create Date: 2026-10-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b91d2f7a4e10"
down_revision: Union[str, None] = "c4e8a17d3b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agency-level role on the USER, not on the membership: it says what the
    # account is allowed to do across the whole agency (owner sees and enters
    # every business; staff only what they are assigned). It is deliberately
    # NOT a per-organization role -- per-org roles are the member management
    # design that was deferred, and conflating the two would make "owner of
    # the agency" mean something different on every row.
    #
    # Existing rows land as 'staff'. The owner is promoted at auth time by
    # OWNER_EMAILS (see api/services/agency_access.py), not here: a migration
    # cannot read the environment, and role checks read this column rather
    # than the env so that rotating OWNER_EMAILS later cannot silently demote
    # anyone who was already promoted.
    op.add_column(
        "users",
        sa.Column(
            "agency_role",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'staff'"),
        ),
    )

    # The assignment table is agency-wide and many-to-many: one staff member
    # may cover several clients, and a client may be covered by several staff.
    # Both FKs CASCADE -- a deleted user or business must not leave assignment
    # rows behind pointing at nothing, unlike organizations_users whose missing
    # ondelete is documented as a trap elsewhere in this fork.
    op.create_table(
        "staff_client_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_staff_client_assignments_user_org",
        ),
    )
    op.create_index(
        "ix_staff_client_assignments_user",
        "staff_client_assignments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_staff_client_assignments_org",
        "staff_client_assignments",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_staff_client_assignments_org", table_name="staff_client_assignments"
    )
    op.drop_index(
        "ix_staff_client_assignments_user", table_name="staff_client_assignments"
    )
    op.drop_table("staff_client_assignments")
    op.drop_column("users", "agency_role")
