from pydantic import BaseModel, Field

from app.models.config import UiLanguage


class AuthLoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AuthStatusResponse(BaseModel):
    bypass_enabled: bool
    authenticated: bool
    ui_language: UiLanguage