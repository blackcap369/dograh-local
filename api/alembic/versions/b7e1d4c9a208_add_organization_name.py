"""add organization name

Gives every organization a human-facing display label. Until now the only
identifier was `provider_id`, an opaque machine string such as
`org_oss_1756200000_ab12cd34`, which the UI sidebar rendered directly -- so an
agency operator saw ids instead of client names.

The column is nullable and backfilled from `provider_id`, so existing orgs
show something immediately instead of a blank row, and the UI can keep
`name ?? provider_id` as its fallback for rows created later without a name.

Revision ID: b7e1d4c9a208
Revises: f3a1c47b9e02
Create Date: 2026-09-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e1d4c9a208"
down_revision: Union[str, None] = "f3a1c47b9e02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("name", sa.String(), nullable=True))

    # Backfill rather than a server_default: a default would be baked into every
    # future INSERT, so an org created without a name would silently get an id
    # string instead of NULL. The UI distinguishes "named" from "not yet named".
    op.execute("UPDATE organizations SET name = provider_id WHERE name IS NULL")


def downgrade() -> None:
    op.drop_column("organizations", "name")
