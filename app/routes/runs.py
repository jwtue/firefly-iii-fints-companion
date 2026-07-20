"""Run history and detail. The detail view shows the redacted response body — the
observability the user previously never had."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from .deps import ctx, render

router = APIRouter()


@router.get("/runs")
async def list_runs(request: Request):
    app_ctx = ctx(request)
    rows = app_ctx.conn.execute(
        "SELECT id, config_name, trigger, started_at, finished_at, duration_ms, "
        "status, transactions_sent FROM run ORDER BY started_at DESC LIMIT 200"
    ).fetchall()
    return render(request, "run_list.html", runs=rows)


@router.get("/runs/{run_id}")
async def run_detail(request: Request, run_id: int):
    app_ctx = ctx(request)
    row = app_ctx.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return render(request, "run_detail.html", run=row)
