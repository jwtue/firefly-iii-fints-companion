"""Schedule management: per-config cron + catch-up settings."""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Form, HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

from .. import schedules
from ..models import validate_filename
from .deps import ctx, render

router = APIRouter()


@router.get("/schedules")
async def list_schedules(request: Request):
    app_ctx = ctx(request)
    existing = {s.config_name: s for s in schedules.list_all(app_ctx.conn)}
    next_runs = app_ctx.scheduler.next_run_times() if app_ctx.scheduler else {}
    rows = []
    for name in app_ctx.store.list_names():
        rows.append({
            "name": name,
            "schedule": existing.get(name),
            "next_run": next_runs.get(name),
        })
    return render(request, "schedule_list.html", rows=rows)


@router.get("/schedules/{name}")
async def edit_schedule(request: Request, name: str):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)
    return render(
        request,
        "schedule_form.html",
        name=name,
        schedule=schedules.get(app_ctx.conn, name),
        error=None,
    )


@router.post("/schedules/{name}")
async def save_schedule(
    request: Request,
    name: str,
    enabled: str = Form(""),
    cron: str = Form(...),
    timezone: str = Form("Europe/Berlin"),
    catchup_enabled: str = Form(""),
    catchup_max_days: int = Form(60),
):
    app_ctx = ctx(request)
    _require_config(app_ctx, name)

    cron = cron.strip()
    try:
        CronTrigger.from_crontab(cron, timezone=timezone)
    except (ValueError, TypeError) as exc:
        return render(
            request,
            "schedule_form.html",
            name=name,
            schedule=schedules.get(app_ctx.conn, name),
            error=f"Invalid cron expression: {exc}",
        )
    if not 1 <= catchup_max_days <= 89:
        return render(
            request,
            "schedule_form.html",
            name=name,
            schedule=schedules.get(app_ctx.conn, name),
            error="Catch-up max days must be between 1 and 89 (PSD2 90-day ceiling).",
        )

    schedules.upsert(
        app_ctx.conn,
        name,
        enabled=bool(enabled),
        cron=cron,
        timezone=timezone,
        catchup_enabled=bool(catchup_enabled),
        catchup_max_days=catchup_max_days,
    )
    _audit(app_ctx, request, "schedule.save", name, f"enabled={bool(enabled)} cron={cron}")
    # Reflect the change into the live scheduler immediately.
    if app_ctx.scheduler is not None:
        app_ctx.scheduler.reconcile(app_ctx.conn)
    return RedirectResponse("/schedules", status_code=303)


def _require_config(app_ctx, name: str) -> None:
    try:
        validate_filename(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not app_ctx.store.exists(name):
        raise HTTPException(status_code=404, detail="Config not found")


def _audit(app_ctx, request: Request, action: str, target: str, detail: str) -> None:
    from datetime import UTC, datetime

    actor = "trusted-net" if getattr(request.state, "bypassed", False) else "user"
    app_ctx.conn.execute(
        "INSERT INTO audit (at, actor, action, target, detail) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(UTC).isoformat(), actor, action, target, detail),
    )
