"""DB access for the provider key vault.

The DB layer stores `encrypted_key` as opaque ciphertext; encryption,
masking, and reference resolution live in api/services/provider_key_vault.py.
"""

from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.db.base_client import BaseDBClient
from api.db.models import ProviderKeyVaultModel


class ProviderKeyVaultClient(BaseDBClient):
    async def create_vault_key(
        self,
        organization_id: int,
        service: str,
        provider: str,
        alias: str,
        encrypted_key: str,
    ) -> ProviderKeyVaultModel:
        """Insert one saved key. Raises ValueError on a duplicate alias for
        the same organization+service+provider (the unique constraint)."""
        async with self.async_session() as session:
            row = ProviderKeyVaultModel(
                organization_id=organization_id,
                service=service,
                provider=provider,
                alias=alias,
                encrypted_key=encrypted_key,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(
                    "A saved key with that alias already exists for this "
                    "provider"
                ) from exc
            await session.refresh(row)
            return row

    async def list_vault_keys(
        self, organization_id: int, service: str | None = None
    ) -> list[ProviderKeyVaultModel]:
        """The organization's saved keys, newest first. Never another org's."""
        async with self.async_session() as session:
            query = select(ProviderKeyVaultModel).where(
                ProviderKeyVaultModel.organization_id == organization_id
            )
            if service is not None:
                query = query.where(ProviderKeyVaultModel.service == service)
            result = await session.execute(
                query.order_by(ProviderKeyVaultModel.id.desc())
            )
            return list(result.scalars().all())

    async def get_vault_key(
        self, key_id: int, organization_id: int
    ) -> Optional[ProviderKeyVaultModel]:
        """One saved key, ONLY within the caller's organization.

        The organization predicate is the isolation boundary: reference
        resolution looks keys up with the caller's org id, so a cross-tenant
        `vault:{id}` resolves to None and fails closed.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(ProviderKeyVaultModel).where(
                    ProviderKeyVaultModel.id == key_id,
                    ProviderKeyVaultModel.organization_id == organization_id,
                )
            )
            return result.scalars().first()

    async def delete_vault_key(self, key_id: int, organization_id: int) -> bool:
        """Remove one saved key. Returns False when the id does not exist in
        this organization."""
        async with self.async_session() as session:
            result = await session.execute(
                sa_delete(ProviderKeyVaultModel).where(
                    ProviderKeyVaultModel.id == key_id,
                    ProviderKeyVaultModel.organization_id == organization_id,
                )
            )
            await session.commit()
            return result.rowcount > 0
