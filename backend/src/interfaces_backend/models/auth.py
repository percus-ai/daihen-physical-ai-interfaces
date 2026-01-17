"""Authentication models."""

from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    """Supabase login request."""

    email: str = Field(..., description="Login email")
    password: str = Field(..., description="Login password")


class AuthLoginResponse(BaseModel):
    """Supabase login response."""

    success: bool = Field(..., description="Login success")
    user_id: str = Field(..., description="Supabase user id")
    expires_at: int | None = Field(None, description="Access token expiry (unix time)")


class AuthStatusResponse(BaseModel):
    """Supabase auth status response."""

    authenticated: bool = Field(..., description="Whether session is available")
    user_id: str | None = Field(None, description="Supabase user id")
    expires_at: int | None = Field(None, description="Access token expiry (unix time)")
