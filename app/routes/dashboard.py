"""Dashboard: each config with its last run status."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request

from .deps import ctx, render

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    app_ctx = ctx(request)
    entries = app_ctx.store.list()
    next_runs = app_ctx.scheduler.next_run_times() if app_ctx.scheduler else {}
    rows = []
    for entry in entries:
        last = app_ctx.conn.execute(
            "SELECT id, status, started_at, transactions_sent, trigger "
            "FROM run WHERE config_name = ? ORDER BY started_at DESC LIMIT 1",
            (entry.name,),
        ).fetchone()
        rows.append({
            "config": entry,
            "last_run": last,
            "next_run": next_runs.get(entry.name),
        })
    return render(request, "dashboard.html", rows=rows)
