"""In-memory job store for async URL uploads."""
import secrets
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

logger = logging.getLogger("immich_drop.job_manager")

JOB_TTL_SECONDS = 600  # 10 minutes
_CLEANUP_INTERVAL = 60  # seconds between cleanup sweeps
_last_cleanup: float = 0.0


@dataclass
class Job:
    id: str
    url: str
    album_name: Optional[str] = None
    status: str = "pending"  # pending, downloading, uploading, completed, failed
    created_at: float = field(default_factory=time.time)
    result: Optional[Any] = None
    error: Optional[str] = None


_jobs: dict[str, Job] = {}


def create_job(url: str, album_name: Optional[str] = None) -> Job:
    job_id = secrets.token_hex(4)
    job = Job(id=job_id, url=url, album_name=album_name)
    _jobs[job_id] = job
    logger.info("Created job %s for URL %s", job_id, url)
    return job


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


def update_job(
    job_id: str,
    status: Optional[str] = None,
    result: Optional[Any] = None,
    error: Optional[str] = None,
) -> None:
    job = _jobs.get(job_id)
    if not job:
        return
    if status:
        job.status = status
    if result is not None:
        job.result = result
    if error is not None:
        job.error = error


def cleanup_expired() -> int:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return 0
    _last_cleanup = now
    expired = [jid for jid, j in _jobs.items() if now - j.created_at > JOB_TTL_SECONDS]
    for jid in expired:
        del _jobs[jid]
    if expired:
        logger.debug("Cleaned up %d expired jobs", len(expired))
    return len(expired)
