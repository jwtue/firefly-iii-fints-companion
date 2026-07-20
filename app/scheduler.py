"""APScheduler wiring — one cron job per enabled schedule.

Design choices that matter:

* **No run at container start.** Jobs are added from stored schedules only; none is
  ever given ``next_run_time=now``. ``reconcile()`` mirrors the DB into the
  scheduler and nothing more. A redeploy must not trigger a bank login.
* **Sequencing lives in the runner**, not here. The scheduler may fire two jobs
  close together; both funnel through the runner's global lock, so they serialise.
  ``max_instances=1`` and ``coalesce=True`` additionally collapse a backlog of the
  *same* job into one run.
* **misfire_grace_time** is generous (1 h) so a schedule that was due while the
  container was briefly down still runs once on return.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import schedules

logger = logging.getLogger("sidecar.scheduler")

# Signature of the callback the scheduler invokes to run a config.
RunCallback = Callable[[str, str], Awaitable[object]]

JOB_PREFIX = "run:"
DEADMAN_JOB_ID = "deadman-switch"


def _job_id(config_name: str) -> str:
    return f"{JOB_PREFIX}{config_name}"


class SchedulerService:
    def __init__(self, run_callback: RunCallback):
        self._run = run_callback
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            }
        )
        self._deadman_callback: Callable[[], Awaitable[None]] | None = None

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # --- job management ------------------------------------------------------

    def reconcile(self, conn) -> None:
        """Make the scheduler's jobs match the enabled schedules in the DB.

        Adds/updates jobs for enabled schedules and removes jobs whose schedule was
        disabled or deleted. Never assigns an immediate next-run time.
        """
        enabled = {s.config_name: s for s in schedules.list_enabled(conn)}

        # Remove jobs that should no longer exist.
        for job in self._scheduler.get_jobs():
            if not job.id.startswith(JOB_PREFIX):
                continue
            config_name = job.id[len(JOB_PREFIX):]
            if config_name not in enabled:
                self._scheduler.remove_job(job.id)
                logger.info("removed schedule job for %s", config_name)

        # Add or update jobs for enabled schedules.
        for name, sched in enabled.items():
            try:
                trigger = CronTrigger.from_crontab(sched.cron, timezone=sched.timezone)
            except ValueError:
                logger.error("invalid cron %r for %s — skipping", sched.cron, name)
                continue
            self._scheduler.add_job(
                self._run_job,
                trigger=trigger,
                id=_job_id(name),
                args=[name],
                replace_existing=True,  # never sets next_run_time=now
            )
            logger.info("scheduled %s: %s (%s)", name, sched.cron, sched.timezone)

    async def _run_job(self, config_name: str) -> None:
        # 'schedule' trigger label; the runner enforces sequencing via its lock.
        await self._run(config_name, "schedule")

    def next_run_times(self) -> dict[str, str]:
        """Map config_name → ISO next-run time for the dashboard."""
        out: dict[str, str] = {}
        for job in self._scheduler.get_jobs():
            if job.id.startswith(JOB_PREFIX) and job.next_run_time is not None:
                out[job.id[len(JOB_PREFIX):]] = job.next_run_time.isoformat()
        return out

    # --- dead-man's switch (M3 uses this) ------------------------------------

    def install_deadman(
        self, callback: Callable[[], Awaitable[None]], *, minutes: int = 60
    ) -> None:
        """Run a periodic check (default hourly) that looks for overdue configs."""
        self._deadman_callback = callback
        self._scheduler.add_job(
            self._run_deadman,
            trigger="interval",
            minutes=minutes,
            id=DEADMAN_JOB_ID,
            replace_existing=True,
        )

    async def _run_deadman(self) -> None:
        if self._deadman_callback is not None:
            await self._deadman_callback()
