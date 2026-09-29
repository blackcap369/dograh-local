from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    OrganizationModel,
    UserModel,
    organization_users_association,
)


class OrganizationClient(BaseDBClient):
    async def get_organization_by_id(
        self, organization_id: int
    ) -> Optional[OrganizationModel]:
        """Get an organization by its ID."""
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel).where(OrganizationModel.id == organization_id)
            )
            return result.scalars().first()

    async def get_organization_users(self, organization_id: int) -> list[UserModel]:
        """Get all users linked to an organization (many-to-many)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(UserModel)
                .join(
                    organization_users_association,
                    organization_users_association.c.user_id == UserModel.id,
                )
                .where(
                    organization_users_association.c.organization_id == organization_id
                )
                .order_by(UserModel.id)
            )
            return list(result.scalars().all())

    async def get_or_create_organization_by_provider_id(
        self, org_provider_id: str, user_id: int, name: str | None = None
    ) -> tuple[OrganizationModel, bool]:
        """Get an existing organization by provider_id or create a new one.

        `name` is the human-facing client label. It is only applied when this call
        actually inserts the row: the ON CONFLICT path returns the pre-existing org
        untouched, so a later login never silently renames a client. Callers that
        pass no name leave the column NULL and the UI falls back to provider_id.

        Returns:
            A tuple of (organization, was_created) where was_created is True if the organization
            was created in this call, False if it already existed.
        """
        async with self.async_session() as session:
            # First try to get existing organization
            result = await session.execute(
                select(OrganizationModel).where(
                    OrganizationModel.provider_id == org_provider_id
                )
            )
            organization = result.scalars().first()

            if organization is None:
                # Use PostgreSQL's INSERT ... ON CONFLICT DO NOTHING
                # This is atomic and handles race conditions at the database level

                stmt = insert(OrganizationModel.__table__).values(
                    provider_id=org_provider_id,
                    name=name,
                    created_at=datetime.now(timezone.utc),
                )
                # ON CONFLICT DO NOTHING - if another request already inserted, this becomes a no-op
                stmt = stmt.on_conflict_do_nothing(index_elements=["provider_id"])

                result = await session.execute(stmt)
                await session.commit()

                # Check if we actually inserted (rowcount > 0) or if there was a conflict (rowcount == 0)
                was_created = result.rowcount > 0

                # Now fetch the organization (either the one we just created or the one that existed)
                result = await session.execute(
                    select(OrganizationModel).where(
                        OrganizationModel.provider_id == org_provider_id
                    )
                )
                organization = result.scalars().first()

                if organization is None:
                    # This should never happen, but handle it just in case
                    error_msg = f"Failed to create or fetch organization with provider_id {org_provider_id}"
                    raise ValueError(error_msg)

                await session.refresh(organization)
                return organization, was_created
            return organization, False

    async def create_organization(
        self, name: str, provider_id: str
    ) -> OrganizationModel:
        """Insert a brand-new organization row and return it.

        Distinct from `get_or_create_organization_by_provider_id`, which is a
        login-time idempotent lookup keyed on a provider id this system does not own.
        Here the caller supplies a freshly minted `provider_id` and the intent is
        unconditionally a new row -- there is no "or get" to fall back to, so a
        collision raises instead of silently returning somebody else's org.

        `provider_id` must be unique. Signup's `org_{user.provider_id}` is 1:1 with a
        user and cannot express "this user runs several businesses", so ids minted for
        this path carry the user id for traceability but are made unique by a random
        suffix.

        Membership is not implied here: the caller pairs this with
        `add_user_to_organization`, which is already race-safe and is the one place
        the association table is written.

        No API key is created. An org used to get a "Default API Key" whose raw value
        is stored only as a hash and is therefore shown to nobody -- an unrecoverable
        secret that merely *looks* like a credential on the Developers page. Keys are
        created explicitly, and the raw value is returned to the caller exactly once,
        at that moment.
        """
        async with self.async_session() as session:
            organization = OrganizationModel(
                provider_id=provider_id,
                name=name,
                created_at=datetime.now(timezone.utc),
            )
            session.add(organization)
            await session.commit()
            await session.refresh(organization)
            return organization

    async def is_user_member_of_organization(
        self, user_id: int, organization_id: int
    ) -> bool:
        """Return True if the user belongs to the given organization."""
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    exists().where(
                        (organization_users_association.c.user_id == user_id)
                        & (
                            organization_users_association.c.organization_id
                            == organization_id
                        )
                    )
                )
            )
            return bool(result.scalar())

    async def add_user_to_organization(
        self, user_id: int, organization_id: int
    ) -> None:
        """Ensure that a user is linked to an organization (many-to-many).

        The association is created only if it does not already exist.
        Uses INSERT ... ON CONFLICT DO NOTHING to handle race conditions.
        """
        async with self.async_session() as session:
            # Use PostgreSQL's INSERT ... ON CONFLICT DO NOTHING
            # This handles race conditions at the database level

            stmt = insert(organization_users_association).values(
                user_id=user_id, organization_id=organization_id
            )
            # ON CONFLICT DO NOTHING - if another request already inserted, this becomes a no-op
            # The primary key constraint on (user_id, organization_id) will trigger the conflict
            stmt = stmt.on_conflict_do_nothing()

            await session.execute(stmt)
            await session.commit()
