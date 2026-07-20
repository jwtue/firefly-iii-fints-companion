"""Login / logout for the password-auth path. Skipped entirely on trusted networks."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ..auth import verify_password
from .deps import ctx, render

logger = logging.getLogger("sidecar.auth")
router = APIRouter()


@router.get("/login")
async def login_form(request: Request):
    if getattr(request.state, "authenticated", False):
        return RedirectResponse("/", status_code=302)
    return render(request, "login.html", error=None)


@router.post("/login")
async def login_submit(request: Request, password: str = Form("")):
    app_ctx = ctx(request)
    settings = app_ctx.settings
    if not settings.password_auth_enabled:
        # No password configured — login is meaningless; only bypass grants access.
        return render(request, "login.html", error="Password authentication is disabled.")

    if not verify_password(settings.password_hash, password):
        # Uniform message; do not reveal which part failed.
        logger.warning("failed login attempt from %s", request.client.host if request.client else "?")
        return render(request, "login.html", error="Invalid password.")

    cookie, _csrf = app_ctx.auth.issue_session()
    response = RedirectResponse("/", status_code=302)
    app_ctx.auth.set_session_cookie(response, cookie)
    return response


@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=302)
    ctx(request).auth.clear_session_cookie(response)
    return response
