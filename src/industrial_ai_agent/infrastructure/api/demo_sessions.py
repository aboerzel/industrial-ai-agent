"""Explicit local browser demo identities; service credentials never enter this adapter."""

from __future__ import annotations

import hmac
import secrets
import time
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from industrial_ai_agent.domain.security import DataClassification, SecurityContext

COOKIE_NAME = "industrial_demo_session"
DEFAULT_USERS_PATH = Path(__file__).resolve().parents[4] / "config/demo-users.toml"


class DemoLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128, repr=False)


class DemoSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class DemoUser:
    username: str
    password: str = field(repr=False)
    clearance: DataClassification = DataClassification.PUBLIC
    roles: tuple[str, ...] = ()

    def metadata(self) -> dict[str, object]:
        return {
            "username": self.username,
            "clearance": self.clearance.name,
            "roles": list(self.roles),
        }

    def security_context(self) -> SecurityContext:
        return SecurityContext(
            subject_id=self.username,
            clearance=self.clearance,
            roles=("demo-user",)
            + tuple("model-admin" for role in self.roles if role == "MODEL_ADMIN"),
            authenticated=True,
        )


class DemoSessions:
    """One bounded server-owned session registry per API process; no background workers."""

    def __init__(
        self,
        users_path: Path = DEFAULT_USERS_PATH,
        *,
        ttl_seconds: float = 28_800,
        capacity: int = 4096,
    ) -> None:
        if ttl_seconds <= 0 or capacity <= 0:
            raise ValueError("Demo session bounds must be positive")
        data = tomllib.loads(users_path.read_text(encoding="utf-8"))
        self.users: dict[str, DemoUser] = {}
        for row in data["users"]:
            username = row["username"]
            if username in self.users or not username.startswith("demo-"):
                raise ValueError("Invalid demo identity configuration")
            roles = tuple(row["roles"])
            if set(roles) - {"MODEL_ADMIN"} or row["password"] != username:
                raise ValueError("Only predefined demo credentials are supported")
            self.users[username] = DemoUser(
                username, row["password"], DataClassification[row["clearance"]], roles
            )
        if "demo-public" not in self.users:
            raise ValueError("Default demo identity is missing")
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._sessions: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    def resolve(self, token: str | None) -> DemoUser | None:
        with self._lock:
            self._expire()
            record = self._sessions.get(token or "")
            return self.users[record[0]] if record else None

    def establish(self, username: str, previous: str | None) -> str:
        if username not in self.users:
            raise HTTPException(401, "Demo login failed.")
        with self._lock:
            self._expire()
            self._sessions.pop(previous or "", None)
            if len(self._sessions) >= self.capacity:
                raise HTTPException(429, "Demo session capacity reached.")
            token = secrets.token_urlsafe(32)
            self._sessions[token] = (username, time.monotonic() + self.ttl_seconds)
            return token

    def revoke(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)

    def _expire(self) -> None:
        now = time.monotonic()
        for token, (_, deadline) in tuple(self._sessions.items()):
            if deadline <= now:
                del self._sessions[token]


def require_same_origin(request: Request) -> None:
    """Cookie mutations require an explicit same-origin request, never ambient authority."""
    origin = request.headers.get("origin")
    if (
        request.headers.get("x-demo-session") != "1"
        or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
        or (
            origin and origin != f"{request.url.scheme}://{request.headers.get('host')}"
        )
    ):
        raise HTTPException(403, "Same-origin demo session request required.")


def install_demo_sessions(app: FastAPI, sessions: DemoSessions | None) -> None:
    @app.get("/api/v1/auth/config")
    async def configuration(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        return {
            "demo_mode": sessions is not None,
            "users": [user.metadata() for user in sessions.users.values()]
            if sessions
            else [],
        }

    if sessions is None:
        return

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> Response:
        if request.url.path.startswith("/api/v1/auth/"):
            return JSONResponse(
                {"detail": "Invalid demo authentication request."}, status_code=422
            )
        return await request_validation_exception_handler(request, error)

    @app.middleware("http")
    async def session_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = request.cookies.get(COOKIE_NAME)
        request.state.demo_cookie_present = token is not None
        user = sessions.resolve(token)
        request.state.demo_security_context = user.security_context() if user else None
        if token and request.method not in {"GET", "HEAD", "OPTIONS"}:
            try:
                require_same_origin(request)
            except HTTPException as error:
                return JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code
                )
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current(request: Request) -> DemoUser:
        user = sessions.resolve(request.cookies.get(COOKIE_NAME))
        if user is None:
            raise HTTPException(401, "Demo session required.")
        return user

    def login_response(
        request: Request, response: Response, username: str
    ) -> dict[str, object]:
        require_same_origin(request)
        token = sessions.establish(username, request.cookies.get(COOKIE_NAME))
        response.set_cookie(
            COOKIE_NAME, token, httponly=True, samesite="strict", path="/api/"
        )
        response.headers["Cache-Control"] = "no-store"
        return sessions.users[username].metadata()

    @app.get("/api/v1/auth/me")
    async def me(request: Request) -> dict[str, object]:
        return current(request).metadata()

    @app.post("/api/v1/auth/bootstrap")
    async def bootstrap(request: Request, response: Response) -> dict[str, object]:
        require_same_origin(request)
        if request.cookies.get(COOKIE_NAME) == "logged-out":
            raise HTTPException(401, "Explicit demo login required.")
        user = sessions.resolve(request.cookies.get(COOKIE_NAME))
        if user:
            return user.metadata()
        return login_response(request, response, "demo-public")

    @app.post("/api/v1/auth/switch")
    async def switch(
        payload: DemoSwitch, request: Request, response: Response
    ) -> dict[str, object]:
        return login_response(request, response, payload.username)

    @app.post("/api/v1/auth/login")
    async def login(
        payload: DemoLogin, request: Request, response: Response
    ) -> dict[str, object]:
        require_same_origin(request)
        user = sessions.users.get(payload.username)
        if user is None or not hmac.compare_digest(
            user.password.encode(), payload.password.encode()
        ):
            raise HTTPException(401, "Demo login failed.")
        return login_response(request, response, user.username)

    @app.post("/api/v1/auth/logout")
    async def logout(request: Request, response: Response) -> dict[str, object]:
        require_same_origin(request)
        sessions.revoke(request.cookies.get(COOKIE_NAME))
        response.set_cookie(
            COOKIE_NAME, "logged-out", httponly=True, samesite="strict", path="/api/"
        )
        return {"logged_out": True}
