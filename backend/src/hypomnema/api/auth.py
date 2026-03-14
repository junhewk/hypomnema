"""Passphrase authentication middleware and endpoints for server mode."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hypomnema.crypto import hash_passphrase, verify_passphrase
from hypomnema.db.settings_store import get_setting, set_setting

if TYPE_CHECKING:
    pass

COOKIE_NAME = "hypomnema_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
EXEMPT_PREFIXES = ("/api/health", "/api/auth/")

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _sign_timestamp(key: bytes, ts: str) -> str:
    """HMAC-sign a timestamp string."""
    return hmac.new(key, ts.encode(), hashlib.sha256).hexdigest()


def _make_session_value(key: bytes) -> str:
    """Create a signed session cookie value: timestamp:hmac."""
    ts = str(int(time.time()))
    sig = _sign_timestamp(key, ts)
    return f"{ts}:{sig}"


def _validate_session(key: bytes, value: str) -> bool:
    """Validate a session cookie: check HMAC and expiry."""
    try:
        ts_str, sig = value.split(":", 1)
        expected = _sign_timestamp(key, ts_str)
        if not hmac.compare_digest(sig, expected):
            return False
        ts = int(ts_str)
        return (time.time() - ts) < COOKIE_MAX_AGE
    except (ValueError, TypeError):
        return False


class PassphraseAuthMiddleware:
    """ASGI middleware that enforces passphrase auth on all routes except exempted ones."""

    def __init__(self, app: ASGIApp, **_kwargs: object) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        # Exempt CORS preflight and auth/health paths
        if method == "OPTIONS" or any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Read fernet_key from app state (set during lifespan)
        app_state = scope.get("app")
        fernet_key: bytes | None = getattr(getattr(app_state, "state", None), "fernet_key", None)
        if fernet_key is None:
            # Key not yet available (before lifespan) — reject
            response = JSONResponse(
                {"detail": "Server starting up"}, status_code=503
            )
            await response(scope, receive, send)
            return

        # Parse cookies from headers
        cookie_value = None
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                for part in header_value.decode().split(";"):
                    part = part.strip()
                    if part.startswith(f"{COOKIE_NAME}="):
                        cookie_value = part[len(f"{COOKIE_NAME}=") :]
                        break
                break

        if cookie_value and _validate_session(fernet_key, cookie_value):
            await self.app(scope, receive, send)
            return

        # Unauthorized
        response = JSONResponse(
            {"detail": "Authentication required"}, status_code=401
        )
        await response(scope, receive, send)


@auth_router.get("/status")
async def auth_status(request: Request) -> dict:
    """Return auth status: whether auth is required, whether user is authenticated, whether passphrase is set."""
    settings = request.app.state.settings
    auth_required = settings.mode == "server"

    if not auth_required:
        return {
            "auth_required": False,
            "authenticated": True,
            "has_passphrase": False,
        }

    db = request.app.state.db
    fernet_key = request.app.state.fernet_key
    stored_hash = await get_setting(db, "auth_passphrase_hash", fernet_key=fernet_key)
    has_passphrase = stored_hash is not None and stored_hash != ""

    # Check if current request has a valid session cookie
    cookie_value = request.cookies.get(COOKIE_NAME)
    authenticated = bool(
        cookie_value and _validate_session(fernet_key, cookie_value)
    )

    return {
        "auth_required": True,
        "authenticated": authenticated,
        "has_passphrase": has_passphrase,
    }


@auth_router.post("/setup")
async def auth_setup(request: Request) -> JSONResponse:
    """One-time passphrase setup. Rejects if passphrase already exists."""
    db = request.app.state.db
    fernet_key = request.app.state.fernet_key

    existing = await get_setting(db, "auth_passphrase_hash", fernet_key=fernet_key)
    if existing:
        return JSONResponse(
            {"detail": "Passphrase already configured"}, status_code=409
        )

    body = await request.json()
    passphrase = body.get("passphrase", "")
    if len(passphrase) < 8:
        return JSONResponse(
            {"detail": "Passphrase must be at least 8 characters"}, status_code=400
        )

    hashed = await asyncio.to_thread(hash_passphrase, passphrase)
    await set_setting(
        db, "auth_passphrase_hash", hashed, fernet_key=fernet_key, encrypt_value=True
    )

    session_value = _make_session_value(fernet_key)
    response = JSONResponse({"status": "ok"})
    response.set_cookie(
        COOKIE_NAME,
        session_value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@auth_router.post("/login")
async def auth_login(request: Request) -> JSONResponse:
    """Validate passphrase and set session cookie."""
    db = request.app.state.db
    fernet_key = request.app.state.fernet_key

    stored_hash = await get_setting(db, "auth_passphrase_hash", fernet_key=fernet_key)
    if not stored_hash:
        return JSONResponse(
            {"detail": "No passphrase configured"}, status_code=400
        )

    body = await request.json()
    passphrase = body.get("passphrase", "")

    if not await asyncio.to_thread(verify_passphrase, passphrase, stored_hash):
        return JSONResponse({"detail": "Invalid passphrase"}, status_code=401)

    session_value = _make_session_value(fernet_key)
    response = JSONResponse({"status": "ok"})
    response.set_cookie(
        COOKIE_NAME,
        session_value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@auth_router.post("/logout")
async def auth_logout() -> JSONResponse:
    """Clear session cookie."""
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME)
    return response
