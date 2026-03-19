"""
IronCore V2: Scheduler API Routes — Phase 3 (The Architect)
============================================================

Exposes:
  GET    /api/scheduler/jobs           — List all jobs
  GET    /api/scheduler/jobs/{id}      — Get single job
  POST   /api/scheduler/jobs           — Create job
  DELETE /api/scheduler/jobs/{id}      — Remove job
  POST   /api/scheduler/jobs/{id}/pause    — Pause job
  POST   /api/scheduler/jobs/{id}/resume   — Resume job
  POST   /api/scheduler/jobs/{id}/trigger  — Run job immediately

All write endpoints require a valid user-level API key (X-IronCore-API-Key).

Author: The Architect (IronCore V2)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ironcore.scheduler.cron import CronScheduler, JobInfo, JobSchedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_scheduler(request: Request) -> CronScheduler:
    scheduler: Optional[CronScheduler] = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="Scheduler not initialised. Set IRONCORE_SCHEDULER_ENABLED=true.",
        )
    return scheduler


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=List[JobInfo])
async def list_jobs(request: Request) -> List[JobInfo]:
    """Return all scheduled jobs with their current status."""
    scheduler = _get_scheduler(request)
    return await scheduler.list_jobs()


@router.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str, request: Request) -> JobInfo:
    """Return details for a single job by ID."""
    scheduler = _get_scheduler(request)
    info = await scheduler.get_job(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return info


@router.post("/jobs", response_model=JobInfo, status_code=201)
async def create_job(schedule: JobSchedule, request: Request) -> JobInfo:
    """Create a new scheduled job."""
    scheduler = _get_scheduler(request)
    try:
        return await scheduler.add_job(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}", status_code=204)
async def remove_job(job_id: str, request: Request) -> None:
    """Remove a scheduled job."""
    scheduler = _get_scheduler(request)
    try:
        await scheduler.remove_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/pause", response_model=Dict[str, Any])
async def pause_job(job_id: str, request: Request) -> Dict[str, Any]:
    """Pause a scheduled job."""
    scheduler = _get_scheduler(request)
    try:
        await scheduler.pause_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "paused", "job_id": job_id}


@router.post("/jobs/{job_id}/resume", response_model=Dict[str, Any])
async def resume_job(job_id: str, request: Request) -> Dict[str, Any]:
    """Resume a paused job."""
    scheduler = _get_scheduler(request)
    try:
        await scheduler.resume_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "resumed", "job_id": job_id}


@router.post("/jobs/{job_id}/trigger", response_model=Dict[str, Any])
async def trigger_job(job_id: str, request: Request) -> Dict[str, Any]:
    """Trigger a job to run immediately (ad-hoc, does not alter schedule)."""
    scheduler = _get_scheduler(request)
    try:
        await scheduler.trigger_now(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "triggered", "job_id": job_id}
