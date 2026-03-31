from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Request, Response


class PasswordGateService:
    cookie_name = "iris_session"

    def __init__(self, *, password: str, bypass_enabled: bool) -> None:
        self.bypass_enabled = bypass_enabled
        self._hasher = PasswordHasher()
        self._password_hash = self._hasher.hash(password) if password else ""
        self._sessions: set[str] = set()

    def verify_password(self, password: str) -> bool:
        if self.bypass_enabled:
            return True
        if not self._password_hash:
            return False
        try:
            return self._hasher.verify(self._password_hash, password)
        except VerifyMismatchError:
            return False

    def is_request_authenticated(self, request: Request) -> bool:
        if self.bypass_enabled:
            return True
        token = request.cookies.get(self.cookie_name)
        return bool(token and token in self._sessions)

    def attach_session_cookie(self, response: Response) -> None:
        token = secrets.token_urlsafe(32)
        self._sessions.add(token)
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )

    def clear_session_cookie(self, request: Request, response: Response) -> None:
        token = request.cookies.get(self.cookie_name)
        if token:
            self._sessions.discard(token)
        response.delete_cookie(self.cookie_name, path="/")