from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AuthStatusResponse(BaseModel):
    bypass_enabled: bool
    authenticated: bool