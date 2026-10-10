"""add organizations.deleted_at (recovery trash)

Revision ID: a6f31c9d8e21
Revises: e83b9f2c6d47
Create Date: 2026-10-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6f31c9d8e21"
down_revision: Union[str, None] = "e83b9f2c6d47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Soft delete: a timestamp, not a removal. Delete becomes reversible --
    # every list, the switcher, and all default lookups exclude rows where
    # this is set, while the row (and everything pointing at it) stays intact
    # for the owner's restore window. The nightly purge hard-deletes expired
    # rows that pass the impact guard; businesses with work history simply
    # stay trashed forever rather than being destroyed on a timer.
    #
    # Indexed because the purge job scans for expired rows and every hot list
    # filters on NULL.
    op.add_column(
        "organizations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organizations_deleted_at", "organizations", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_deleted_at", table_name="organizations")
    op.drop_column("organizations", "deleted_at")
