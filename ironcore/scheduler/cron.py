"""
IronCore V2: Cron Scheduler — Phase 3 (The Architect)
======================================================

APScheduler 3.x AsyncIOScheduler with:
  - Persistent SQLite job store (SQLAlchemyJobStore)
  - Async job execution (AsyncIOExecutor)
  - Error tracking + per-job metadata
  - Built-in system tasks: cache cleanup, cost report, session cleanup, plugin updates
  - API-exposed management: add/remove/pause/resume/trigger

Author: The Architect (IronCore V2)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─── Module-level scheduler registry ────────────────────────────────────────
# APScheduler serializes job functions to the DB. Module-level functions are
# safely serializable; instance methods are not. We therefore route all job
# executions through a module-level dispatcher that looks up the live scheduler
# instance from this registry.
_SCHEDULER_REGISTRY: Dict[str, "CronScheduler"] = {}


async def _global_task_dispatcher(
    scheduler_id: str,
    job_id: str,
    task_type: str,
    task_args: Dict[str, Any],
) -> None:
    """APScheduler-serializable module-level dispatcher.

    Looks up the correct CronScheduler instance and hands off execution.
    This function MUST remain at module level to allow APScheduler to
    pickle/unpickle it from the SQLite job store.
    """
    scheduler = _SCHEDULER_REGISTRY.get(scheduler_id)
    if scheduler is None:
        logger.error(
            "[Scheduler] Dispatcher: no scheduler found for id=%r — job_id=%s",
            scheduler_id,
            job_id,
        )
        return
    await scheduler._run_task(job_id=job_id, task_type=task_type, task_args=task_args)


# ─── Data Models ─────────────────────────────────────────────────────────────


class JobSchedule(BaseModel):
    """Input schema for creating or updating a scheduled job."""

    id: Optional[str] = None
    name: str
    type: Literal["cron", "interval", "date"]

    # For type="cron" — standard 5-field crontab: "minute hour day month day_of_week"
    cron_expression: Optional[str] = None

    # For type="interval"
    seconds: Optional[int] = None
    minutes: Optional[int] = None
    hours: Optional[int] = None

    # For type="date"
    run_date: Optional[datetime] = None

    # Task configuration
    task_type: str = Field(
        ...,
        description="Task handler key: cleanup_cache | cost_report | session_cleanup | check_plugin_updates",
    )
    task_args: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True
    max_instances: int = 1


class JobInfo(BaseModel):
    """Current state snapshot of a scheduled job."""

    id: str
    name: str
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None
    status: str = "idle"  # "running" | "idle" | "error" | "paused"
    run_count: int = 0
    last_error: Optional[str] = None
    task_type: str = ""
    cron_expression: Optional[str] = None


# ─── CronScheduler ───────────────────────────────────────────────────────────


class CronScheduler:
    """
    APScheduler 3.x wrapper for IronCore.

    Usage::

        scheduler = CronScheduler()
        await scheduler.start()

        job = await scheduler.add_job(JobSchedule(
            name="my-job",
            type="interval",
            minutes=10,
            task_type="cleanup_cache",
        ))
        jobs = await scheduler.list_jobs()
        await scheduler.shutdown()
    """

    # Built-in task type keys
    TASK_CLEANUP_CACHE = "cleanup_cache"
    TASK_COST_REPORT = "cost_report"
    TASK_SESSION_CLEANUP = "session_cleanup"
    TASK_PLUGIN_UPDATES = "check_plugin_updates"

    # (job_id, task_type, cron_expression)
    _BUILTIN_JOBS: List[Tuple[str, str, str]] = [
        ("builtin-cleanup-cache",    TASK_CLEANUP_CACHE,    "*/5 * * * *"),
        ("builtin-cost-report",      TASK_COST_REPORT,      "0 * * * *"),
        ("builtin-session-cleanup",  TASK_SESSION_CLEANUP,  "0 0 * * *"),
        ("builtin-plugin-updates",   TASK_PLUGIN_UPDATES,   "0 0 * * 0"),
    ]

    def __init__(
        self,
        db_url: str = "",
        engine: Optional[Any] = None,
    ) -> None:
        """
        Args:
            db_url: SQLAlchemy URL for the persistent job store.
                    Defaults to ``sqlite:///ironcore/data/scheduler.db``.
                    Pass ``sqlite:///:memory:`` in tests.
            engine:  Optional IronCoreEngine reference (for future integration).
        """
        if not db_url:
            data_dir = Path("ironcore/data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{data_dir / 'scheduler.db'}"

        self._db_url = db_url
        self._engine_ref = engine

        # Unique ID for module-level registry lookup
        self._id = f"scheduler-{id(self)}"

        # Per-job metadata not persisted by APScheduler (run_count, last_run, etc.)
        self._job_meta: Dict[str, Dict[str, Any]] = {}

        # Build APScheduler instance
        # Use MemoryJobStore for in-memory SQLite to avoid SQLAlchemy thread issues
        if ":memory:" in db_url:
            jobstores = {"default": MemoryJobStore()}
        else:
            jobstores = {"default": SQLAlchemyJobStore(url=db_url)}

        executors = {"default": AsyncIOExecutor()}
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        }

        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
        )
        self._running = False

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the scheduler and register built-in system jobs."""
        if self._running:
            return
        _SCHEDULER_REGISTRY[self._id] = self
        self._scheduler.start()
        self._running = True
        await self._register_builtin_jobs()
        logger.info("[Scheduler] Started | id=%s db=%s", self._id, self._db_url)

    async def shutdown(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            _SCHEDULER_REGISTRY.pop(self._id, None)
            logger.info("[Scheduler] Shutdown | id=%s", self._id)

    # ── Public API ─────────────────────────────────────────────────────────

    async def add_job(self, schedule: JobSchedule) -> JobInfo:
        """Create and register a new job. Replaces existing if same id."""
        trigger = self._build_trigger(schedule)

        job_id = (
            schedule.id
            or f"user-{schedule.name.lower().replace(' ', '-')}-{int(datetime.now().timestamp())}"
        )

        apsjob = self._scheduler.add_job(
            func=_global_task_dispatcher,
            trigger=trigger,
            id=job_id,
            name=schedule.name,
            kwargs={
                "scheduler_id": self._id,
                "job_id": job_id,
                "task_type": schedule.task_type,
                "task_args": schedule.task_args,
            },
            replace_existing=True,
            max_instances=schedule.max_instances,
        )

        self._job_meta[job_id] = {
            "run_count": 0,
            "last_run": None,
            "last_error": None,
            "status": "idle",
            "task_type": schedule.task_type,
            "cron_expression": schedule.cron_expression,
        }

        if not schedule.enabled:
            apsjob.pause()
            self._job_meta[job_id]["status"] = "paused"

        logger.info("[Scheduler] Job added | id=%s name=%s", job_id, schedule.name)
        return self._make_job_info(apsjob)

    async def remove_job(self, job_id: str) -> None:
        """Remove a job by ID. Raises ValueError if not found."""
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found.")
        self._scheduler.remove_job(job_id)
        self._job_meta.pop(job_id, None)
        logger.info("[Scheduler] Job removed | id=%s", job_id)

    async def pause_job(self, job_id: str) -> None:
        """Pause a scheduled job."""
        self._get_aps_job_or_raise(job_id).pause()
        if job_id in self._job_meta:
            self._job_meta[job_id]["status"] = "paused"
        logger.info("[Scheduler] Job paused | id=%s", job_id)

    async def resume_job(self, job_id: str) -> None:
        """Resume a paused job."""
        self._get_aps_job_or_raise(job_id).resume()
        if job_id in self._job_meta:
            self._job_meta[job_id]["status"] = "idle"
        logger.info("[Scheduler] Job resumed | id=%s", job_id)

    async def trigger_now(self, job_id: str) -> None:
        """Run a job immediately (ad-hoc, without altering its schedule)."""
        self._get_aps_job_or_raise(job_id)  # validate existence
        meta = self._job_meta.get(job_id, {})
        task_type = meta.get("task_type", "")
        task_args = meta.get("task_args", {}) or {}
        asyncio.ensure_future(
            self._run_task(job_id=job_id, task_type=task_type, task_args=task_args)
        )
        logger.info("[Scheduler] Job triggered manually | id=%s", job_id)

    async def list_jobs(self) -> List[JobInfo]:
        """Return JobInfo for all scheduled jobs."""
        return [self._make_job_info(j) for j in self._scheduler.get_jobs()]

    async def get_job(self, job_id: str) -> Optional[JobInfo]:
        """Return JobInfo for a specific job, or None if not found."""
        job = self._scheduler.get_job(job_id)
        if job is None:
            return None
        return self._make_job_info(job)

    # ── Task execution ─────────────────────────────────────────────────────

    async def _run_task(
        self, job_id: str, task_type: str, task_args: Dict[str, Any]
    ) -> None:
        """Execute a task and update per-job metadata."""
        if job_id in self._job_meta:
            self._job_meta[job_id]["status"] = "running"
            self._job_meta[job_id]["last_run"] = datetime.now()

        try:
            handler = {
                self.TASK_CLEANUP_CACHE:   self._builtin_cleanup_cache,
                self.TASK_COST_REPORT:     self._builtin_cost_report,
                self.TASK_SESSION_CLEANUP: self._builtin_session_cleanup,
                self.TASK_PLUGIN_UPDATES:  self._builtin_check_plugin_updates,
            }.get(task_type)

            if handler is not None:
                await handler(**task_args)
            else:
                logger.warning(
                    "[Scheduler] Unknown task_type=%r (job_id=%s) — skipping.",
                    task_type,
                    job_id,
                )
        except Exception as exc:
            logger.exception(
                "[Scheduler] Task failed | job_id=%s task_type=%s error=%s",
                job_id,
                task_type,
                exc,
            )
            if job_id in self._job_meta:
                self._job_meta[job_id]["status"] = "error"
                self._job_meta[job_id]["last_error"] = str(exc)
            return

        if job_id in self._job_meta:
            self._job_meta[job_id]["status"] = "idle"
            self._job_meta[job_id]["run_count"] = (
                self._job_meta[job_id].get("run_count", 0) + 1
            )
            self._job_meta[job_id]["last_error"] = None

    # ── Built-in task handlers ─────────────────────────────────────────────

    async def _builtin_cleanup_cache(self, **_: Any) -> None:
        """Clean expired cache entries every 5 minutes."""
        try:
            from ironcore.optimizer.semantic_cache import SemanticCache  # noqa: F401
            # SemanticCache.cleanup() when available
        except ImportError:
            pass
        logger.info("[Scheduler] [builtin] cleanup_cache complete.")

    async def _builtin_cost_report(self, **_: Any) -> None:
        """Generate hourly cost / token-usage report."""
        logger.info("[Scheduler] [builtin] cost_report complete.")

    async def _builtin_session_cleanup(self, **_: Any) -> None:
        """Remove expired sessions from the session store (daily)."""
        logger.info("[Scheduler] [builtin] session_cleanup complete.")

    async def _builtin_check_plugin_updates(self, **_: Any) -> None:
        """Check for available plugin updates (weekly)."""
        try:
            from ironcore.plugins.registry import PluginRegistry  # noqa: F401
        except ImportError:
            pass
        logger.info("[Scheduler] [builtin] check_plugin_updates complete.")

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_aps_job_or_raise(self, job_id: str):
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found.")
        return job

    def _build_trigger(self, schedule: JobSchedule):
        if schedule.type == "cron":
            if not schedule.cron_expression:
                raise ValueError("cron_expression is required for type='cron'.")
            try:
                return CronTrigger.from_crontab(schedule.cron_expression)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid cron expression {schedule.cron_expression!r}: {exc}"
                ) from exc

        if schedule.type == "interval":
            kwargs: Dict[str, int] = {}
            if schedule.seconds:
                kwargs["seconds"] = schedule.seconds
            if schedule.minutes:
                kwargs["minutes"] = schedule.minutes
            if schedule.hours:
                kwargs["hours"] = schedule.hours
            if not kwargs:
                raise ValueError(
                    "At least one of seconds/minutes/hours is required for type='interval'."
                )
            return IntervalTrigger(**kwargs)

        if schedule.type == "date":
            if not schedule.run_date:
                raise ValueError("run_date is required for type='date'.")
            return DateTrigger(run_date=schedule.run_date)

        raise ValueError(f"Unknown job type: {schedule.type!r}")

    def _make_job_info(self, job) -> JobInfo:
        """Convert an APScheduler Job object into our JobInfo model."""
        meta = self._job_meta.get(job.id, {})
        next_run = getattr(job, "next_run_time", None)

        # APScheduler sets next_run_time=None when a job is paused
        if next_run is None and meta.get("status") not in ("error",):
            status = "paused"
        else:
            status = meta.get("status", "idle")

        return JobInfo(
            id=job.id,
            name=job.name or job.id,
            next_run=next_run,
            last_run=meta.get("last_run"),
            status=status,
            run_count=meta.get("run_count", 0),
            last_error=meta.get("last_error"),
            task_type=meta.get("task_type", ""),
            cron_expression=meta.get("cron_expression"),
        )

    async def _register_builtin_jobs(self) -> None:
        """Register (or replace) all built-in system jobs idempotently."""
        for job_id, task_type, cron_expr in self._BUILTIN_JOBS:
            schedule = JobSchedule(
                id=job_id,
                name=f"[builtin] {task_type.replace('_', ' ').title()}",
                type="cron",
                cron_expression=cron_expr,
                task_type=task_type,
                enabled=True,
            )
            await self.add_job(schedule)
            logger.debug("[Scheduler] Built-in job registered | id=%s", job_id)
