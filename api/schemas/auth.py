from pydantic import BaseModel, EmailStr, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str | None
    name: str | None = None
    organization_id: int | None = None
    provider_id: str | None = None
    # Agency-level role: 'owner' (full cross-organization access) or 'staff'
    # (sees only businesses assigned to them on the agency surface). Default
    # 'staff' so an older client that ignores the field stays correct.
    agency_role: str = "staff"


class AuthResponse(BaseModel):
    token: str
    user: UserResponse
