"""Notification test endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from .deps import ctx

router = APIRouter()


@router.post("/notify/test")
async def notify_test(request: Request):
    app_ctx = ctx(request)
    if app_ctx.notifier is not None:
        await app_ctx.notifier.send_test()
    return RedirectResponse("/schedules", status_code=303)
