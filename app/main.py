"""Application factory and lifespan wiring.

Startup order: validate auth (fail-closed) → install the redaction logging filter
→ open the DB and migrate → build the config store and prime the redactor → create
the importer client and runner → attach routes and the auth middleware.

The scheduler (M2) will be started in the lifespan after ``reconcile()``; for M1
there is no scheduler and, importantly, nothing runs at container start.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import schedules
from .auth import AuthManager, AuthMiddleware
from .configstore import ConfigStore
from .importer.client import ImporterClient
from .redact import install_logging_filter
from .runner import Runner
from .scheduler import SchedulerService
from .settings import Settings, get_settings

logger = logging.getLogger("sidecar")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


class AppState:
    """Container for shared singletons, attached to ``app.state.ctx``."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = ConfigStore(settings.config_dir)
        self.client = ImporterClient(
            settings.importer_base_url,
            settings.importer_timeout_seconds,
            supports_json=settings.importer_supports_json,
        )
        self.auth = AuthManager(settings)
        self.conn = None  # set in lifespan
        self.runner: Runner | None = None
        self.scheduler: SchedulerService | None = None
        self.notifier = None  # set in lifespan (M3)
        self.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_auth()  # fail-closed: raises here if the config is unsafe
    install_logging_filter()

    ctx = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from .db import init_db

        from .runner import repair_crashed_runs

        from .notify.dispatcher import Notifier
        from .notify.registry import build_backends

        ctx.conn = init_db(Path(settings.state_dir) / "sidecar.sqlite")
        ctx.store.refresh_redactor()  # prime redactor from existing configs

        # M3: notifier (may have zero backends — then it just logs).
        ctx.notifier = Notifier(ctx.conn, build_backends(settings.notify_urls))
        ctx.runner = Runner(ctx.conn, ctx.store, ctx.client, notifier=ctx.notifier)

        # M5: repair runs left in 'running' from a crash/restart before wiring the
        # scheduler, so a half-finished catch-up window is restored.
        repair_crashed_runs(ctx.conn, ctx.store)

        # M2: scheduler. reconcile() only mirrors stored schedules into jobs — it
        # never schedules an immediate run, so startup performs no bank login.
        schedules.prune_orphans(ctx.conn, set(ctx.store.list_names()))
        ctx.scheduler = SchedulerService(ctx.runner.execute)
        ctx.scheduler.reconcile(ctx.conn)
        # M3: dead-man's switch — hourly check for configs that stopped succeeding.
        ctx.scheduler.install_deadman(ctx.notifier.check_deadman, minutes=60)
        ctx.scheduler.start()

        logger.info("sidecar started (no run performed at startup by design)")
        try:
            yield
        finally:
            if ctx.scheduler is not None:
                ctx.scheduler.shutdown()
            if ctx.conn is not None:
                ctx.conn.close()

    app = FastAPI(title="Firefly FinTS Sidecar", lifespan=lifespan)
    app.state.ctx = ctx

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from .routes import configs, dashboard, health, lang, notify, runs
    from .routes import schedules as schedule_routes
    from .routes import auth as auth_routes

    app.include_router(health.router)
    app.include_router(auth_routes.router)
    app.include_router(lang.router)
    app.include_router(dashboard.router)
    app.include_router(configs.router)
    app.include_router(runs.router)
    app.include_router(schedule_routes.router)
    app.include_router(notify.router)

    app.add_middleware(AuthMiddleware, auth=ctx.auth)
    return app
