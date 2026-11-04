"""add credit balances and transactions

Revision ID: e57c3d9a8b26
Revises: d93b7a2e5f18
Create Date: 2026-10-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e57c3d9a8b26"
down_revision: Union[str, None] = "d93b7a2e5f18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Credit billing (owner request): 1 credit = 1 minute of successful run
    # time. Plans are credit grants; top-ups add more; failed runs never
    # deduct. One balance row per organization; every movement writes a
    # transaction row so the history is reconstructible from day one.
    op.create_table(
        "credit_balances",
        sa.Column("organization_id", sa.Integer(), primary_key=True),
        sa.Column(
            "balance_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta_minutes", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_credit_transactions_org",
        "credit_transactions",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_credit_transactions_org", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_table("credit_balances")
