"""Language switcher: set the `lang` cookie and redirect back."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ..i18n import SUPPORTED

router = APIRouter()

# One year; a language preference is not sensitive.
_MAX_AGE = 365 * 24 * 3600


@router.get("/lang/{code}")
async def set_language(request: Request, code: str, next: str = "/"):
    # Only redirect to same-site absolute paths — never an external URL.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    if code in SUPPORTED:
        response.set_cookie(
            "lang", code, max_age=_MAX_AGE, samesite="lax", path="/",
            secure=request.app.state.ctx.settings.behind_tls,
        )
    return response
