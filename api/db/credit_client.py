"""DB access for credit billing: 1 credit = 1 minute of successful run time.

Enforcement model: new runs are blocked when the balance is at or below
zero (checked at run creation); the per-run deduction happens at completion
and may take the balance to exactly zero or slightly negative from
in-flight usage after the block. Every movement writes a transaction row.
"""

from typing import Optional

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    CreditBalanceModel,
    CreditTransactionModel,
    OrganizationModel,
)

DEFAULT_STARTUP_CREDITS = 60


class CreditClient(BaseDBClient):
    async def get_or_create_balance(self, organization_id: int) -> CreditBalanceModel:
        """The organization's balance row, created with a startup grant on
        first touch so a new business can test immediately."""
        async with self.async_session() as session:
            result = await session.execute(
                select(CreditBalanceModel).where(
                    CreditBalanceModel.organization_id == organization_id
                )
            )
            balance = result.scalars().first()
            if balance is not None:
                return balance

            balance = CreditBalanceModel(
                organization_id=organization_id,
                balance_minutes=DEFAULT_STARTUP_CREDITS,
            )
            session.add(balance)
            try:
                await session.commit()
            except Exception:
                # Raced another creator; re-read the winner's row.
                await session.rollback()
                result = await session.execute(
                    select(CreditBalanceModel).where(
                        CreditBalanceModel.organization_id == organization_id
                    )
                )
                return result.scalars().first()
            await session.refresh(balance)

            session.add(
                CreditTransactionModel(
                    organization_id=organization_id,
                    delta_minutes=DEFAULT_STARTUP_CREDITS,
                    balance_after=balance.balance_minutes,
                    reason="startup_grant",
                )
            )
            await session.commit()
            return balance

    async def get_balance_minutes(self, organization_id: int) -> int:
        balance = await self.get_or_create_balance(organization_id)
        return balance.balance_minutes

    async def top_up(
        self, organization_id: int, minutes: int, created_by: int | None
    ) -> CreditBalanceModel:
        """Add credits (owner top-up). Minutes must be positive."""
        if minutes <= 0:
            raise ValueError("top-up minutes must be positive")
        async with self.async_session() as session:
            result = await session.execute(
                select(CreditBalanceModel).where(
                    CreditBalanceModel.organization_id == organization_id
                )
            )
            balance = result.scalars().first()
            if balance is None:
                balance = CreditBalanceModel(
                    organization_id=organization_id, balance_minutes=0
                )
                session.add(balance)
                await session.flush()
            balance.balance_minutes += minutes
            balance.updated_at = func.now()
            new_total = balance.balance_minutes
            session.add(
                CreditTransactionModel(
                    organization_id=organization_id,
                    delta_minutes=minutes,
                    balance_after=new_total,
                    reason="top_up",
                    created_by=created_by,
                )
            )
            await session.commit()
            await session.refresh(balance)
            return balance

    async def deduct_for_run(
        self, organization_id: int, minutes: int, run_id: int
    ) -> int:
        """Deduct credits for a completed successful run. Unconditional at
        completion (the zero-balance block happens at run creation); may take
        the balance slightly negative from in-flight usage. Returns the
        balance after."""
        async with self.async_session() as session:
            result = await session.execute(
                select(CreditBalanceModel).where(
                    CreditBalanceModel.organization_id == organization_id
                )
            )
            balance = result.scalars().first()
            if balance is None:
                balance = CreditBalanceModel(
                    organization_id=organization_id, balance_minutes=0
                )
                session.add(balance)
                await session.flush()
            balance.balance_minutes -= minutes
            balance.updated_at = func.now()
            new_total = balance.balance_minutes
            session.add(
                CreditTransactionModel(
                    organization_id=organization_id,
                    delta_minutes=-minutes,
                    balance_after=new_total,
                    reason="run_deduction",
                    run_id=run_id,
                )
            )
            await session.commit()
            await session.refresh(balance)
            return new_total

    async def has_credits(self, organization_id: int) -> bool:
        """Whether new runs may start: balance above zero."""
        balance = await self.get_or_create_balance(organization_id)
        return balance.balance_minutes > 0

    async def get_balances_for_orgs(
        self, organization_ids: list[int]
    ) -> dict[int, int]:
        """Balances for a set of organizations. Empty list -> empty dict."""
        if not organization_ids:
            return {}
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    CreditBalanceModel.organization_id,
                    CreditBalanceModel.balance_minutes,
                ).where(CreditBalanceModel.organization_id.in_(organization_ids))
            )
            found = {org_id: minutes for org_id, minutes in result.all()}
            # Organizations with no row yet read as the startup grant, not
            # zero -- a brand-new client can test before their first balance
            # write.
            return {
                org_id: found.get(org_id, DEFAULT_STARTUP_CREDITS)
                for org_id in organization_ids
            }

    async def list_transactions(
        self, organization_id: int, limit: int = 20
    ) -> list[CreditTransactionModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CreditTransactionModel)
                .where(CreditTransactionModel.organization_id == organization_id)
                .order_by(CreditTransactionModel.id.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
