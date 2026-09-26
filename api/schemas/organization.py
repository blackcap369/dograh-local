from pydantic import BaseModel


class OrganizationListItem(BaseModel):
    id: int
    provider_id: str
    # Display label, e.g. "Acme Corp". Defaults to None so an org row that predates
    # the column -- or a caller that supplied no name -- still serializes, with the
    # UI falling back to provider_id.
    name: str | None = None


class OrganizationSwitchRequest(BaseModel):
    """Body for selecting the caller's active organization.

    `organization_id` is the local integer primary key, matching the `id` returned by
    GET /organizations/mine -- it is never trusted on its own to imply membership; the
    switch endpoint re-checks the association table before writing.
    """

    organization_id: int
