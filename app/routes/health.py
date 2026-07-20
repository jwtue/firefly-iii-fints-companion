"""Unauthenticated liveness endpoint. Returns nothing but liveness — no config
names, no run data — so it is safe to expose to a site monitor."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
