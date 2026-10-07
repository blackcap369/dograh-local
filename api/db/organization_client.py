from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import exists, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    OrganizationModel,
    StaffClientAssignmentModel,
    TelephonyPhoneNumberModel,
    UserModel,
    WorkflowModel,
    WorkflowRunModel,
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

    # =========================================================================
    # Staff client assignments (agency surface access, NOT org membership)
    # =========================================================================

    async def is_user_assigned_to_organization(
        self, user_id: int, organization_id: int
    ) -> bool:
        """Whether the staff user has an assignment row for this business."""
        async with self.async_session() as session:
            result = await session.execute(
                select(StaffClientAssignmentModel.id).where(
                    StaffClientAssignmentModel.user_id == user_id,
                    StaffClientAssignmentModel.organization_id == organization_id,
                )
            )
            return result.scalar_one_or_none() is not None

    async def list_organizations_for_staff(
        self, user_id: int
    ) -> list[OrganizationModel]:
        """Every business the staff user is assigned to, oldest first.

        The staff Clients page's only read. Deliberately a join against the
        assignment table -- not a filter applied after listing everything --
        so an unassigned business's name never leaves the database for a staff
        caller.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel)
                .join(
                    StaffClientAssignmentModel,
                    StaffClientAssignmentModel.organization_id
                    == OrganizationModel.id,
                )
                .where(StaffClientAssignmentModel.user_id == user_id)
                .order_by(OrganizationModel.id)
            )
            return list(result.scalars().all())

    async def assign_staff_to_organization(
        self, user_id: int, organization_id: int
    ) -> None:
        """Grant a staff user access to a business. Idempotent."""
        async with self.async_session() as session:
            stmt = (
                insert(StaffClientAssignmentModel)
                .values(user_id=user_id, organization_id=organization_id)
                .on_conflict_do_nothing(
                    constraint="uq_staff_client_assignments_user_org"
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def unassign_staff_from_organization(
        self, user_id: int, organization_id: int
    ) -> None:
        """Revoke a staff user's access to a business."""
        async with self.async_session() as session:
            await session.execute(
                sa_delete(StaffClientAssignmentModel).where(
                    StaffClientAssignmentModel.user_id == user_id,
                    StaffClientAssignmentModel.organization_id == organization_id,
                )
            )
            await session.commit()

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

    # =======================================================================
    # Agency (cross-organization) operations
    #
    # Every method below is deliberately unscoped by user. They are reached only
    # from the Creative Mode router, which is gated on the agency operator. That
    # is the one place in this fork where a broad read is correct, and it is a
    # deliberate inversion of the rule every other client here follows -- hence the
    # banner rather than a passing comment. If roles are ever added, the gate
    # changes in one place (`require_agency_operator`) and these stay as they are.
    # =======================================================================

    async def list_all_organizations(
        self, include_archived: bool = False
    ) -> list[OrganizationModel]:
        """Every organization on the instance, oldest first.

        The archived filter lives in the query, not in the caller. Filtering
        client-side would still ship an archived business's name over the wire and
        would depend on every caller remembering -- which is precisely how a
        retired client reappears in the switcher six months later.
        """
        async with self.async_session() as session:
            query = select(OrganizationModel)
            if not include_archived:
                query = query.where(OrganizationModel.archived.is_(False))
            result = await session.execute(query.order_by(OrganizationModel.id))
            return list(result.scalars().all())

    async def get_organization_resource_counts(
        self, organization_ids: list[int]
    ) -> dict[int, dict[str, int]]:
        """Per-organization counts of the rows that make a delete destructive.

        One grouped query per table rather than a per-organization lookup: the
        Clients page renders a count for every business at once, and N+1 here is N
        round-trips on the screen the operator uses most.

        Returns a COMPLETE four-key dict for every requested organization --
        keys are pre-zero-filled, then overwritten by whatever the grouped
        queries find. A business can have members but no workflows, or runs but
        no phone numbers, and a sparse dict there became a KeyError deep in the
        delete guard: the shape of the result is part of the contract, not a
        courtesy.

        `member_count` is reported but is deliberately not a delete blocker. The
        creator is always a member, so a business with nothing else in it still
        has one; blocking on it would make every freshly-created business
        undeletable and the guard useless.
        """
        if not organization_ids:
            # Four queries against an empty IN () is wasted work, and some drivers
            # reject the empty case outright.
            return {}

        zeroed = {
            "workflow_count": 0,
            "run_count": 0,
            "phone_number_count": 0,
            "member_count": 0,
        }
        counts: dict[int, dict[str, int]] = {
            organization_id: dict(zeroed) for organization_id in organization_ids
        }

        async with self.async_session() as session:
            for key, model in (
                ("workflow_count", WorkflowModel),
                ("phone_number_count", TelephonyPhoneNumberModel),
            ):
                result = await session.execute(
                    select(model.organization_id, func.count(model.id))
                    .where(model.organization_id.in_(organization_ids))
                    .group_by(model.organization_id)
                )
                for org_id, count in result.all():
                    counts[org_id][key] = int(count)

            # `workflow_runs` carries no `organization_id` of its own -- a run is
            # scoped to the org of the workflow it executed, the same join the
            # isolation guards on the run routes rely on. Counting per org means
            # joining through `workflows`, not reaching for a column that would
            # raise at query-build time.
            result = await session.execute(
                select(WorkflowModel.organization_id, func.count(WorkflowRunModel.id))
                .select_from(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(WorkflowModel.organization_id.in_(organization_ids))
                .group_by(WorkflowModel.organization_id)
            )
            for org_id, count in result.all():
                counts[org_id]["run_count"] = int(count)

            result = await session.execute(
                select(
                    organization_users_association.c.organization_id,
                    func.count(organization_users_association.c.user_id),
                )
                .where(
                    organization_users_association.c.organization_id.in_(
                        organization_ids
                    )
                )
                .group_by(organization_users_association.c.organization_id)
            )
            for org_id, count in result.all():
                counts[org_id]["member_count"] = int(count)

        return counts

    async def rename_organization(
        self, organization_id: int, *, name: str
    ) -> Optional[OrganizationModel]:
        """Set an organization's display label. Never touches `provider_id`.

        `provider_id` is the sole key organizations are looked up by and is stamped
        onto every workflow, call record, and member selection pointing at this
        business. Renaming it would break all of them, so it is not a parameter.

        Returns the updated row, or None if the id does not exist.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel).where(OrganizationModel.id == organization_id)
            )
            organization = result.scalars().first()
            if organization is None:
                return None

            organization.name = name
            await session.commit()
            await session.refresh(organization)
            return organization

    async def set_organization_archived(
        self, organization_id: int, archived: bool
    ) -> Optional[OrganizationModel]:
        """Hide a business from the switcher, or bring it back. Data is untouched.

        Returns the updated row, or None if the id does not exist.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(OrganizationModel).where(OrganizationModel.id == organization_id)
            )
            organization = result.scalars().first()
            if organization is None:
                return None

            organization.archived = archived
            await session.commit()
            await session.refresh(organization)
            return organization

    async def clear_selected_organization_references(
        self, organization_id: int
    ) -> None:
        """Null `users.selected_organization_id` for anyone pointing at this org.

        `selected_organization_id` has no `ondelete`, so a member still standing in
        this business would abort the delete on a foreign-key violation -- or be left
        pointing at a row that no longer exists, which turns every subsequent
        request into a 500. Called before the delete, never after.

        The membership rows in `organization_users` are left alone here: they carry
        no ondelete either, so they survive as orphans rather than blocking. The
        delete route cleans them up explicitly with `clear_organization_users`
        before `delete_organization` runs.
        """
        async with self.async_session() as session:
            await session.execute(
                update(UserModel)
                .where(UserModel.selected_organization_id == organization_id)
                .values(selected_organization_id=None)
            )
            await session.commit()

    async def clear_organization_users(
        self, organization_id: int
    ) -> None:
        """Remove all user-organization associations for an organization.

        This is used when an organization is deleted and we want to clean up
        the membership table, since it has no `ondelete` constraint.
        """
        async with self.async_session() as session:
            await session.execute(
                sa_delete(organization_users_association).where(
                    organization_users_association.c.organization_id == organization_id
                )
            )
            await session.commit()

    async def delete_organization(self, organization_id: int) -> bool:
        """Delete an organization row. Returns False if it was already gone.

        Callers are responsible for the guard. The foreign keys into
        `organizations.id` are inconsistent -- API keys, model configurations,
        telephony configurations, phone numbers, and call records CASCADE and are
        destroyed silently, while workflows, folders, campaigns, and the membership
        table carry no `ondelete` and will raise -- so a delete issued without the
        history check can take a client's recordings with it. `agency.py` refuses
        with a 409 before this is ever reached, and
        `clear_selected_organization_references` must be called first.
        """
        async with self.async_session() as session:
            result = await session.execute(
                sa_delete(OrganizationModel).where(
                    OrganizationModel.id == organization_id
                )
            )
            await session.commit()
            return result.rowcount > 0

