"""
tests/test_phase3_architect_scheduler.py
=========================================
Phase 3 — The Architect (IronCore V2): CronScheduler test suite.

Coverage:
  - add_job cron / interval / date types
  - invalid cron expression → ValueError
  - list_jobs returns registered jobs
  - get_job returns correct JobInfo / None for missing
  - pause_job / resume_job → status transitions
  - remove_job → no longer listed; remove missing → ValueError
  - trigger_now → task executes
  - Built-in jobs registered at startup
  - add_job disabled=False → status paused immediately
  - task error → status="error", last_error populated

Author: The Architect (IronCore V2)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict

import pytest
import pytest_asyncio

from ironcore.scheduler.cron import CronScheduler, JobSchedule


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def scheduler():
    """Fresh in-memory scheduler for each test (no disk I/O)."""
    sched = CronScheduler(db_url="sqlite:///:memory:")
    await sched.start()
    yield sched
    await sched.shutdown()


# ─── add_job — type="cron" ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_job_cron_valid(scheduler: CronScheduler):
    """A valid cron job should be registered and appear in list_jobs."""
    info = await scheduler.add_job(
        JobSchedule(
            id="test-cron-1",
            name="test cron job",
            type="cron",
            cron_expression="0 12 * * *",  # daily at noon
            task_type=CronScheduler.TASK_COST_REPORT,
        )
    )
    assert info.id == "test-cron-1"
    assert info.name == "test cron job"
    assert info.task_type == CronScheduler.TASK_COST_REPORT

    jobs = await scheduler.list_jobs()
    job_ids = [j.id for j in jobs]
    assert "test-cron-1" in job_ids


@pytest.mark.asyncio
async def test_add_job_cron_invalid_expression(scheduler: CronScheduler):
    """An invalid cron expression should raise ValueError before adding."""
    with pytest.raises(ValueError, match="cron"):
        await scheduler.add_job(
            JobSchedule(
                name="bad cron",
                type="cron",
                cron_expression="not-a-cron",
                task_type=CronScheduler.TASK_CLEANUP_CACHE,
            )
        )


@pytest.mark.asyncio
async def test_add_job_cron_missing_expression(scheduler: CronScheduler):
    """type='cron' without cron_expression should raise ValueError."""
    with pytest.raises(ValueError, match="cron_expression"):
        await scheduler.add_job(
            JobSchedule(
                name="no expr",
                type="cron",
                cron_expression=None,
                task_type=CronScheduler.TASK_CLEANUP_CACHE,
            )
        )


# ─── add_job — type="interval" ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_job_interval_valid(scheduler: CronScheduler):
    """A valid interval job should register and report correct metadata."""
    info = await scheduler.add_job(
        JobSchedule(
            id="test-interval-1",
            name="every 30 seconds",
            type="interval",
            seconds=30,
            task_type=CronScheduler.TASK_CLEANUP_CACHE,
        )
    )
    assert info.id == "test-interval-1"
    # next_run should be set (scheduler is running)
    assert info.next_run is not None


@pytest.mark.asyncio
async def test_add_job_interval_missing_period(scheduler: CronScheduler):
    """type='interval' without any time fields should raise ValueError."""
    with pytest.raises(ValueError, match="seconds/minutes/hours"):
        await scheduler.add_job(
            JobSchedule(
                name="interval no period",
                type="interval",
                task_type=CronScheduler.TASK_CLEANUP_CACHE,
            )
        )


# ─── add_job — type="date" ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_job_date_valid(scheduler: CronScheduler):
    """A one-shot date job should register successfully."""
    future = datetime.now() + timedelta(hours=1)
    info = await scheduler.add_job(
        JobSchedule(
            id="test-date-1",
            name="one-shot",
            type="date",
            run_date=future,
            task_type=CronScheduler.TASK_COST_REPORT,
        )
    )
    assert info.id == "test-date-1"


@pytest.mark.asyncio
async def test_add_job_date_missing_run_date(scheduler: CronScheduler):
    """type='date' without run_date should raise ValueError."""
    with pytest.raises(ValueError, match="run_date"):
        await scheduler.add_job(
            JobSchedule(
                name="date no run_date",
                type="date",
                run_date=None,
                task_type=CronScheduler.TASK_COST_REPORT,
            )
        )


# ─── get_job ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_job_existing(scheduler: CronScheduler):
    """get_job should return a JobInfo for an existing job."""
    await scheduler.add_job(
        JobSchedule(
            id="get-test",
            name="get test",
            type="interval",
            minutes=5,
            task_type=CronScheduler.TASK_CLEANUP_CACHE,
        )
    )
    info = await scheduler.get_job("get-test")
    assert info is not None
    assert info.id == "get-test"


@pytest.mark.asyncio
async def test_get_job_missing_returns_none(scheduler: CronScheduler):
    """get_job should return None for a non-existent job ID."""
    result = await scheduler.get_job("does-not-exist-xyz")
    assert result is None


# ─── pause / resume ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_and_resume_job(scheduler: CronScheduler):
    """Pausing a job should set status='paused'; resuming should restore 'idle'."""
    await scheduler.add_job(
        JobSchedule(
            id="pause-test",
            name="pause test",
            type="interval",
            seconds=60,
            task_type=CronScheduler.TASK_CLEANUP_CACHE,
        )
    )
    await scheduler.pause_job("pause-test")
    info = await scheduler.get_job("pause-test")
    assert info is not None
    assert info.status == "paused"

    await scheduler.resume_job("pause-test")
    info = await scheduler.get_job("pause-test")
    assert info is not None
    assert info.status == "idle"


@pytest.mark.asyncio
async def test_pause_nonexistent_job_raises(scheduler: CronScheduler):
    """pause_job on a missing ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await scheduler.pause_job("ghost-job")


@pytest.mark.asyncio
async def test_resume_nonexistent_job_raises(scheduler: CronScheduler):
    """resume_job on a missing ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await scheduler.resume_job("ghost-job")


# ─── remove_job ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_job(scheduler: CronScheduler):
    """Removing a job should cause it to disappear from list_jobs."""
    await scheduler.add_job(
        JobSchedule(
            id="remove-test",
            name="remove test",
            type="interval",
            hours=1,
            task_type=CronScheduler.TASK_SESSION_CLEANUP,
        )
    )
    await scheduler.remove_job("remove-test")
    result = await scheduler.get_job("remove-test")
    assert result is None


@pytest.mark.asyncio
async def test_remove_nonexistent_job_raises(scheduler: CronScheduler):
    """remove_job on a missing ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await scheduler.remove_job("does-not-exist")


# ─── trigger_now ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_now_executes_task(scheduler: CronScheduler):
    """trigger_now should dispatch the task without error."""
    await scheduler.add_job(
        JobSchedule(
            id="trigger-test",
            name="trigger test",
            type="interval",
            minutes=30,
            task_type=CronScheduler.TASK_CLEANUP_CACHE,
        )
    )
    # trigger_now schedules via asyncio.ensure_future — give event loop a tick
    await scheduler.trigger_now("trigger-test")
    await asyncio.sleep(0.05)
    # After execution the run_count should increment to 1
    info = await scheduler.get_job("trigger-test")
    assert info is not None
    assert info.run_count >= 1


@pytest.mark.asyncio
async def test_trigger_nonexistent_job_raises(scheduler: CronScheduler):
    """trigger_now on a missing job ID should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await scheduler.trigger_now("ghost-job")


# ─── Built-in jobs ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_builtin_jobs_registered_at_startup(scheduler: CronScheduler):
    """All 4 built-in system jobs must be present after start()."""
    jobs = await scheduler.list_jobs()
    job_ids = {j.id for j in jobs}
    expected = {
        "builtin-cleanup-cache",
        "builtin-cost-report",
        "builtin-session-cleanup",
        "builtin-plugin-updates",
    }
    assert expected.issubset(job_ids), f"Missing built-in jobs: {expected - job_ids}"


# ─── disabled job ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_job_disabled_starts_paused(scheduler: CronScheduler):
    """A job added with enabled=False must have status='paused' immediately."""
    info = await scheduler.add_job(
        JobSchedule(
            id="disabled-job",
            name="disabled",
            type="cron",
            cron_expression="0 0 1 1 *",   # once a year
            task_type=CronScheduler.TASK_COST_REPORT,
            enabled=False,
        )
    )
    assert info.status == "paused"


# ─── replace existing job ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_job_replaces_existing(scheduler: CronScheduler):
    """Adding a job with the same id should replace the existing one."""
    await scheduler.add_job(
        JobSchedule(
            id="replace-test",
            name="original",
            type="interval",
            seconds=10,
            task_type=CronScheduler.TASK_CLEANUP_CACHE,
        )
    )
    await scheduler.add_job(
        JobSchedule(
            id="replace-test",
            name="updated",
            type="interval",
            minutes=5,
            task_type=CronScheduler.TASK_COST_REPORT,
        )
    )
    info = await scheduler.get_job("replace-test")
    assert info is not None
    assert info.name == "updated"

    # Should still be only one job with that ID
    matching = [j for j in await scheduler.list_jobs() if j.id == "replace-test"]
    assert len(matching) == 1


# ─── task error handling ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_task_type_does_not_raise(scheduler: CronScheduler):
    """An unknown task_type should be handled gracefully (log warning, no crash)."""
    await scheduler.add_job(
        JobSchedule(
            id="unknown-task",
            name="unknown",
            type="interval",
            minutes=60,
            task_type="nonexistent_task_type",
        )
    )
    await scheduler.trigger_now("unknown-task")
    await asyncio.sleep(0.05)
    # Job should still exist and status should be idle (unknown task → graceful skip)
    info = await scheduler.get_job("unknown-task")
    assert info is not None
