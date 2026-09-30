"""add organizations.archived

Revision ID: c4e8a17d3b92
Revises: b7e1d4c9a208
Create Date: 2026-09-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a17d3b92"
down_revision: Union[str, None] = "b7e1d4c9a208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOT NULL with a server_default, which is the opposite choice from the `name`
    # backfill in b7e1d4c9a208 and is deliberate. `name` was nullable, so omitting
    # it was a meaningful state ("not yet named") that a default would have
    # destroyed. `archived` is NOT NULL, so existing rows have no value to read and
    # the add would fail outright without one; and an INSERT that omits the column
    # landing as false is the correct meaning, not a lost distinction.
    op.add_column(
        "organizations",
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # The switcher and the Clients page both filter on this, so an unindexed column
    # would be scanned on every read. A plain btree serves both `archived = false`
    # and the count of archived rows, since this fork has a handful of businesses
    # at most -- selectivity is not the concern, correctness is.
    op.create_index(
        "ix_organizations_archived", "organizations", ["archived"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_archived", table_name="organizations")
    op.drop_column("organizations", "archived")
