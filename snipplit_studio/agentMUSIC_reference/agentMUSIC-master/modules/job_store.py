"""File-backed persistence for API jobs (ADR-002 style).

Persists jobs and the ``command_id -> job_id`` idempotency map to
``{output_dir}/_jobs/index.json`` so the AF platform can keep polling a job
across a process restart, and repeated commands never double-create work.

Scope: SINGLE PROCESS. The reservation lock and the render queue are
process-local; running several AgentMUSIC replicas breaks both idempotency
and polling (scale vertically / GPU instead).
"""

from __future__ import annotations

import logging
import os
import threading

from modules.config import settings
from modules.job_tracker import Job, tracker
from modules.json_index import load_json_list, save_json_atomic

logger = logging.getLogger(__name__)

# RLock: resolve_or_reserve holds the lock while create_job() runs, and the
# tracker persist hook re-enters persist_job() on the same thread.
_LOCK = threading.RLock()

# Terminal provider statuses eligible for command re-issue after a failure.
REISSUABLE = {"failed", "canceled"}

# Job dataclass fields persisted as-is (everything needed to rehydrate).
_JOB_FIELDS = (
    "job_id", "user_id", "status", "progress", "total", "current_phase",
    "current_message", "scenario", "track_name", "orientation",
    "created_at", "updated_at", "results", "error", "command_id", "params",
)


def _index_path() -> str:
    return os.path.join(settings.output_dir, "_jobs", "index.json")


def _job_to_record(job: Job) -> dict:
    return {name: getattr(job, name) for name in _JOB_FIELDS}


def _record_to_job(record: dict) -> Job:
    fields = {name: record[name] for name in _JOB_FIELDS if name in record}
    return Job(**fields)


def _load_records() -> list[dict]:
    try:
        return load_json_list(_index_path())
    except Exception as e:
        logger.error("job store load failed: %s", e)
        return []


def _save_records(records: list[dict]) -> None:
    save_json_atomic(_index_path(), records)


def persist_job(job: Job) -> None:
    """Upsert a single job record (atomic write-temp-then-rename)."""
    with _LOCK:
        records = _load_records()
        records = [r for r in records if r.get("job_id") != job.job_id]
        records.append(_job_to_record(job))
        # Bound the file like the tracker history.
        if len(records) > 500:
            records.sort(key=lambda r: r.get("created_at", 0))
            records = records[-500:]
        _save_records(records)


def load_jobs() -> list[Job]:
    with _LOCK:
        return [_record_to_job(r) for r in _load_records() if r.get("job_id")]


def resolve_or_reserve(command_id: str, create_job) -> tuple[Job, bool]:
    """Atomically resolve a command_id to an existing job or create a new one.

    ``create_job`` is a zero-arg callable creating (and persisting) the new Job.
    Returns ``(job, created)``. Retry semantics: an existing queued/running/
    succeeded job is returned as-is; a failed/canceled/orphaned one allows a
    re-issue (the command is repointed to the fresh attempt).
    """
    with _LOCK:
        existing_id = None
        for record in _load_records():
            if record.get("command_id") == command_id:
                existing_id = record.get("job_id")
        if existing_id:
            job = tracker.get(existing_id)
            if job is None:
                stored = [r for r in _load_records() if r.get("job_id") == existing_id]
                job = _record_to_job(stored[0]) if stored else None
            if job is not None and job.provider_status not in REISSUABLE:
                return job, False
        job = create_job()
        return job, True
