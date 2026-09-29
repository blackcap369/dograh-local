from pydantic import BaseModel, Field, field_validator


class OrganizationListItem(BaseModel):
    id: int
    provider_id: str
    # Display label, e.g. "Acme Corp". Defaults to None so an org row that predates
    # the column -- or a caller that supplied no name -- still serializes, with the
    # UI falling back to provider_id.
    name: str | None = None


class OrganizationCreateRequest(BaseModel):
    """Body for creating a new business.

    Name only, deliberately. `provider_id` is the sole key organizations are looked up
    by, so accepting one from a caller would let a tenant collide with or impersonate
    another -- it is minted server-side instead.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-facing client label, e.g. 'Acme Corp'.",
    )

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # `min_length` counts the raw string, so "   " satisfies it. A dropdown row
        # of spaces is indistinguishable between clients, and it round-trips into the
        # organization_bootstrap prompts, so reject it before it is ever stored.
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class OrganizationSwitchRequest(BaseModel):
    """Body for selecting the caller's active organization.

    `organization_id` is the local integer primary key, matching the `id` returned by
    GET /organizations/mine -- it is never trusted on its own to imply membership; the
    switch endpoint re-checks the association table before writing.
    """

    organization_id: int
