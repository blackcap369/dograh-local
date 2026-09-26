from pydantic import BaseModel


class OrganizationListItem(BaseModel):
    id: int
    provider_id: str


class OrganizationSwitchRequest(BaseModel):
    """Body for selecting the caller's active organization.

    `organization_id` is the local integer primary key, matching the `id` returned by
    GET /organizations/mine -- it is never trusted on its own to imply membership; the
    switch endpoint re-checks the association table before writing.
    """

    organization_id: int
