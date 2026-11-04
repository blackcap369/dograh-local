"""add provider_key_vault

Revision ID: c8a42e6f9b13
Revises: a6f31c9d8e21
Create Date: 2026-10-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8a42e6f9b13"
down_revision: Union[str, None] = "a6f31c9d8e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The saved-API-key vault: one row per (organization, service, provider,
    # alias). Keys are stored encrypted by the service layer -- the DB layer
    # only sees ciphertext. Additive and org-scoped like every other table in
    # this fork; nothing existing changes.
    op.create_table(
        "provider_key_vault",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "service",
            "provider",
            "alias",
            name="uq_provider_key_vault_org_service_provider_alias",
        ),
    )
    op.create_index(
        "ix_provider_key_vault_org",
        "provider_key_vault",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_key_vault_org", table_name="provider_key_vault")
    op.drop_table("provider_key_vault")
