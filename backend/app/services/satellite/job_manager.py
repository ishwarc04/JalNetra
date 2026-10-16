import asyncio
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Any
import uuid

from app.schemas.satellite_observation import (
    VisualAcquisitionJobResponse,
    SatelliteObservationRead,
)

logger = logging.getLogger("jalnetra.satellite.job_manager")


class VisualAcquisitionJobManager:
    """
    In-process, asynchronous job manager for tracking satellite visual data
    acquisition progress in real time without external brokers (Redis/Celery).
    """

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self, water_body_id: str, total: int, initial_message: str = "Acquisition queued"
    ) -> VisualAcquisitionJobResponse:
        async with self._lock:
            job_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            record = {
                "job_id": job_id,
                "water_body_id": water_body_id,
                "status": "queued",
                "total": total,
                "completed": 0,
                "reused": 0,
                "failed": 0,
                "current_index": 0,
                "current_scene_id": None,
                "current_stage": "QUEUED",
                "percent": 0,
                "details": "Queued for processing",
                "message": initial_message,
                "results": [],
                "errors": [],
                "created_at": now,
                "updated_at": now,
            }
            self._jobs[job_id] = record
            return VisualAcquisitionJobResponse(**record)

    async def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        completed: Optional[int] = None,
        reused: Optional[int] = None,
        failed: Optional[int] = None,
        current_index: Optional[int] = None,
        current_scene_id: Optional[str] = None,
        current_stage: Optional[str] = None,
        percent: Optional[int] = None,
        details: Optional[str] = None,
        message: Optional[str] = None,
        add_result: Optional[SatelliteObservationRead] = None,
        add_error: Optional[Dict[str, str]] = None,
    ) -> Optional[VisualAcquisitionJobResponse]:
        async with self._lock:
            record = self._jobs.get(job_id)
            if not record:
                return None

            now = datetime.now(timezone.utc)
            record["updated_at"] = now

            if status is not None:
                record["status"] = status
            if completed is not None:
                record["completed"] = completed
            if reused is not None:
                record["reused"] = reused
            if failed is not None:
                record["failed"] = failed
            if current_index is not None:
                record["current_index"] = current_index
            if current_scene_id is not None:
                record["current_scene_id"] = current_scene_id
            if current_stage is not None:
                record["current_stage"] = current_stage
            if percent is not None:
                record["percent"] = max(0, min(100, percent))
            if details is not None:
                record["details"] = details
            if message is not None:
                record["message"] = message

            if add_result is not None:
                record["results"].append(add_result)
            if add_error is not None:
                record["errors"].append(add_error)

            return VisualAcquisitionJobResponse(**record)

    async def get_job(self, job_id: str) -> Optional[VisualAcquisitionJobResponse]:
        async with self._lock:
            record = self._jobs.get(job_id)
            if not record:
                return None
            return VisualAcquisitionJobResponse(**record)

    async def cleanup_old_jobs(self, max_age_seconds: int = 3600) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc)
            to_remove = []
            for jid, rec in self._jobs.items():
                age = (now - rec["updated_at"]).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(jid)
            for jid in to_remove:
                del self._jobs[jid]


# Global singleton instance
job_manager = VisualAcquisitionJobManager()
