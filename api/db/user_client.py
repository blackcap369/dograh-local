import uuid
from datetime import datetime, timezone
from typing import List

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    UserConfigurationModel,
    UserModel,
    OrganizationModel,
    organization_users_association,
)
from api.enums import UserConfigurationKey
from api.schemas.ai_model_configuration import EffectiveAIModelConfiguration


class UserClient(BaseDBClient):
    async def get_or_create_user_by_provider_id(
        self, provider_id: str
    ) -> tuple[UserModel, bool]:
        """Return (user, was_created) tuple."""
        async with self.async_session() as session:
            # First try to get existing user
            result = await session.execute(
                select(UserModel).where(UserModel.provider_id == provider_id)
            )
            user = result.scalars().first()

            if user is not None:
                return user, False

            # Use PostgreSQL's INSERT ... ON CONFLICT DO NOTHING
            # This is atomic and handles race conditions at the database level
            stmt = insert(UserModel.__table__).values(
                provider_id=provider_id,
                created_at=datetime.now(timezone.utc),
                selected_organization_id=None,  # Will be set later
                is_superuser=False,  # Default value
            )
            # ON CONFLICT DO NOTHING - if another request already inserted, this becomes a no-op
            stmt = stmt.on_conflict_do_nothing(index_elements=["provider_id"])

            result = await session.execute(stmt)
            await session.commit()
            was_created = result.rowcount > 0

            # Now fetch the user (either the one we just created or the one that existed)
            result = await session.execute(
                select(UserModel).where(UserModel.provider_id == provider_id)
            )
            user = result.scalars().first()

            if user is None:
                # This should never happen, but handle it just in case
                error_msg = (
                    f"Failed to create or fetch user with provider_id {provider_id}"
                )
                raise ValueError(error_msg)
        return user, was_created

    async def get_user_by_id(self, user_id: int) -> UserModel | None:
        """Fetch a user by their internal ID."""
        async with self.async_session() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            return result.scalars().first()

    async def _get_user_configuration_row(
        self, session, user_id: int, key: str
    ) -> UserConfigurationModel | None:
        result = await session.execute(
            select(UserConfigurationModel).where(
                UserConfigurationModel.user_id == user_id,
                UserConfigurationModel.key == key,
            )
        )
        return result.scalars().first()

    async def get_user_configuration_value(self, user_id: int, key: str) -> dict | None:
        """Get the JSON value stored for a user under `key`, or None."""
        async with self.async_session() as session:
            row = await self._get_user_configuration_row(session, user_id, key)
            return row.configuration if row else None

    async def upsert_user_configuration_value(
        self, user_id: int, key: str, value: dict
    ) -> dict:
        """Create or update the JSON value stored for a user under `key`."""
        async with self.async_session() as session:
            stmt = insert(UserConfigurationModel.__table__).values(
                user_id=user_id,
                key=key,
                configuration=value,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="_user_configuration_key_uc",
                set_={"configuration": stmt.excluded.configuration},
            ).returning(UserConfigurationModel.configuration)
            try:
                result = await session.execute(stmt)
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            return result.scalar_one()

    async def get_user_configurations(
        self, user_id: int
    ) -> EffectiveAIModelConfiguration:
        async with self.async_session() as session:
            configuration_obj = await self._get_user_configuration_row(
                session, user_id, UserConfigurationKey.MODEL_CONFIGURATION.value
            )
            if not configuration_obj:
                return EffectiveAIModelConfiguration()

            try:
                return EffectiveAIModelConfiguration.model_validate(
                    {
                        **configuration_obj.configuration,
                        "last_validated_at": configuration_obj.last_validated_at,
                    }
                )
            except ValidationError as e:
                # If configuration contains an unsupported provider,
                # return a default configuration without failing
                logger.warning(
                    f"Failed to validate user configuration for user {user_id}: {e}. "
                    "Returning default configuration."
                )
                return EffectiveAIModelConfiguration()

    async def update_user_configuration(
        self, user_id: int, configuration: EffectiveAIModelConfiguration
    ) -> EffectiveAIModelConfiguration:
        value = await self.upsert_user_configuration_value(
            user_id,
            UserConfigurationKey.MODEL_CONFIGURATION.value,
            configuration.model_dump(),
        )
        return EffectiveAIModelConfiguration.model_validate(value)

    async def update_user_configuration_last_validated_at(self, user_id: int) -> None:
        async with self.async_session() as session:
            configuration_obj = await self._get_user_configuration_row(
                session, user_id, UserConfigurationKey.MODEL_CONFIGURATION.value
            )
            if not configuration_obj:
                raise ValueError(f"User configuration with ID {user_id} not found")
            configuration_obj.last_validated_at = datetime.now()
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(configuration_obj)

    async def update_user_selected_organization(
        self, user_id: int, organization_id: int
    ) -> None:
        """Update the user's selected organization ID."""
        async with self.async_session() as session:
            from sqlalchemy import update

            # Use a direct UPDATE statement to avoid race conditions
            # This is atomic at the database level
            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(selected_organization_id=organization_id)
            )

            result = await session.execute(stmt)

            if result.rowcount == 0:
                raise ValueError(f"User with ID {user_id} not found")

            await session.commit()

    async def update_user_email(self, user_id: int, email: str) -> None:
        """Update the user's email address."""
        async with self.async_session() as session:
            from sqlalchemy import update

            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(email=email.lower())
            )
            await session.execute(stmt)
            await session.commit()

    async def update_user_agency_role(self, user_id: int, agency_role: str) -> None:
        """Set the user's agency-level role ('owner' or 'staff').

        The one-way owner promotion in agency_access.py funnels through here.
        There is deliberately no demotion caller: removing an email from
        OWNER_EMAILS must not silently demote an account that was already
        promoted.
        """
        async with self.async_session() as session:
            from sqlalchemy import update

            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(agency_role=agency_role)
            )
            result = await session.execute(stmt)
            if result.rowcount == 0:
                raise ValueError(f"User with ID {user_id} not found")
            await session.commit()

    async def get_user_agency_role(self, user_id: int) -> str | None:
        """The user's stored agency role, or None if the user does not exist."""
        async with self.async_session() as session:
            result = await session.execute(
                select(UserModel.agency_role).where(UserModel.id == user_id)
            )
            return result.scalar_one_or_none()

    async def list_staff_users(self) -> list[UserModel]:
        """Every staff account, oldest first -- the access page's read.

        With signup open, self-registered accounts land here too: the owner
        sees who exists on the instance and decides what each one may touch.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(UserModel)
                .where(UserModel.agency_role == "staff")
                .order_by(UserModel.id)
            )
            return list(result.scalars().all())

    async def set_user_password(self, user_id: int, password_hash: str) -> None:
        """Overwrite a user's password hash (owner-initiated reset)."""
        async with self.async_session() as session:
            from sqlalchemy import update

            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(password_hash=password_hash)
            )
            result = await session.execute(stmt)
            if result.rowcount == 0:
                raise ValueError(f"User with ID {user_id} not found")
            await session.commit()

    async def set_user_suspended(self, user_id: int, suspended: bool) -> None:
        """Set the user's suspension flag."""
        async with self.async_session() as session:
            from sqlalchemy import update

            stmt = (
                update(UserModel)
                .where(UserModel.id == user_id)
                .values(is_suspended=suspended)
            )
            result = await session.execute(stmt)
            if result.rowcount == 0:
                raise ValueError(f"User with ID {user_id} not found")
            await session.commit()

    async def count_workflows_owned_by_user(self, user_id: int) -> int:
        """How many agents this account built.

        Deleting a user whose user_id is stamped on workflows trips the FK
        (workflows.user_id carries no ondelete), so the staff-delete route
        must know before it tries.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(UserModel.id))
                .select_from(UserModel)
                .join(UserModel.workflows)
                .where(UserModel.id == user_id)
            )
            return int(result.scalar_one())

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user row outright. Returns False if already gone.

        Caller guards apply: owners are undeletable via this path, and a user
        who owns workflows must be suspended instead (the FK would abort the
        delete).
        """
        async with self.async_session() as session:
            from sqlalchemy import delete as sa_delete

            result = await session.execute(
                sa_delete(UserModel).where(UserModel.id == user_id)
            )
            await session.commit()
            return result.rowcount > 0

    async def get_user_by_email(self, email: str) -> UserModel | None:
        """Fetch a user by their email address (case-insensitive).

        Email addresses are case-insensitive in practice, so a user who
        signed up as "User@example.com" must still be found when they later
        log in as "user@example.com". Compare on lower(email) so lookups are
        robust to capitalization differences across sign-in flows.
        """
        normalized_email = email.lower()
        async with self.async_session() as session:
            result = await session.execute(
                select(UserModel).where(func.lower(UserModel.email) == normalized_email)
            )
            return result.scalars().first()

    async def create_user_with_email(
        self,
        email: str,
        password_hash: str,
        name: str | None = None,
        agency_role: str = "staff",
    ) -> UserModel:
        """Create a new user with email and password hash.

        `agency_role` is resolved by the caller (resolve_agency_role against
        OWNER_EMAILS) -- the DB layer stores, it does not decide.
        """
        async with self.async_session() as session:
            user = UserModel(
                provider_id=f"oss_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4()}",
                email=email.lower(),
                password_hash=password_hash,
                agency_role=agency_role,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_organizations_for_user(
        self, user_id: int, include_archived: bool = False
    ) -> List[OrganizationModel]:
        """Return all organizations the user belongs to.

        Archived organizations are excluded at the query unless asked for. The
        switcher is the only caller, and an archived business must not reappear in
        it -- filtering in Python would still pull the name over the wire and leave
        the rule resting on every caller remembering.

        `include_archived=True` exists for a surface that legitimately needs the
        retired businesses too. No caller uses it yet; the default is `False` so
        that a new caller gets the safe behaviour rather than the surprising one.
        """
        from sqlalchemy import select as sa_select

        async with self.async_session() as session:
            query = (
                sa_select(OrganizationModel)
                .join(
                    organization_users_association,
                    OrganizationModel.id
                    == organization_users_association.c.organization_id,
                )
                .where(organization_users_association.c.user_id == user_id)
            )
            # Trashed businesses never appear: the switcher would offer a
            # place to stand that is on its way out.
            query = query.where(OrganizationModel.deleted_at.is_(None))
            if not include_archived:
                query = query.where(OrganizationModel.archived.is_(False))
            result = await session.execute(query.order_by(OrganizationModel.id))
            return list(result.scalars().all())
