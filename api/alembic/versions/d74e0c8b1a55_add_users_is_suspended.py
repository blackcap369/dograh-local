"""add users.is_suspended

Revision ID: d74e0c8b1a55
Revises: b91d2f7a4e10
Create Date: 2026-10-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d74e0c8b1a55"
down_revision: Union[str, None] = "b91d2f7a4e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Suspension is the offboarding primitive for staff. Deleting a staff
    # account outright is frequently impossible -- workflows.user_id carries
    # no ondelete, so agents a staff member built keep them tied to the
    # instance -- and revoking assignments alone leaves their existing JWT
    # valid until expiry. A suspended flag checked at every auth path closes
    # both: access dies immediately, and the account (and its agent history)
    # stays intact for reactivation.
    op.add_column(
        "users",
        sa.Column(
            "is_suspended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_suspended")
