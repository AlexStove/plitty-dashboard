"""
Трекер генерационных задач для API atome-studio.

Хранит in-memory состояние всех текущих и завершённых задач.
Используется как ботом (при запуске генерации), так и API (для отдачи статуса).
"""

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Job:
    job_id: str
    user_id: int
    status: str = "running"          # running | done | error | stopped
    progress: int = 0
    total: int = 1
    current_phase: str = "queued"    # queued | transcribing | searching_footage | rendering | uploading | done | error
    current_message: str = ""
    scenario: str = ""               # karaoke | streamer
    track_name: str = ""
    orientation: str = "portrait"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    results: list = field(default_factory=list)
    error: str = ""
    command_id: str = ""                 # платформенный идемпотентный ключ (af-адаптер)
    params: dict = field(default_factory=dict)  # параметры очереди для reconcile при рестарте

    @property
    def provider_status(self) -> str:
        """Статус для контракта внешнего провайдера (AF video-generator adapter)."""
        if self.status == "running":
            return "queued" if self.current_phase == "queued" else "running"
        return {"done": "succeeded", "error": "failed", "stopped": "canceled"}.get(
            self.status, self.status
        )

    @property
    def percent(self) -> int:
        if self.status == "done":
            return 100
        if self.status == "error":
            return 0
        if self.total <= 0:
            return 0

        # Плавный прогресс на основе времени с easing
        # Формула: pct = 95 * (1 - e^(-t/tau))
        # tau подобрано так чтобы к ~150сек было ~90%
        import math
        elapsed = time.time() - self.created_at
        tau = 60.0 * self.total  # ~60 сек на видео для кривой

        # Экспоненциальный easing — быстро растёт в начале, замедляется к концу
        smooth_pct = 95.0 * (1.0 - math.exp(-elapsed / tau))

        # Прогресс по завершённым видео (скачки при реальном прогрессе)
        done_pct = self.progress / self.total * 100

        # Берём максимум из плавного и реального
        return max(int(done_pct), min(95, int(smooth_pct)))

    def to_dict(self) -> dict:
        from datetime import datetime, timezone
        d = asdict(self)
        d["percent"] = self.percent
        d["provider_status"] = self.provider_status
        d["duration_sec"] = int(time.time() - self.created_at)
        # ISO format для совместимости с atome-studio normalizeJob
        d["created_at"] = datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat()
        d["updated_at"] = datetime.fromtimestamp(self.updated_at, tz=timezone.utc).isoformat()
        d["started_at"] = d["created_at"]
        # Добавляем download URL для каждого видео в результатах
        if self.status == "done" and self.results:
            for r in d["results"]:
                if isinstance(r, dict) and r.get("video_id"):
                    r["download_url"] = f"/api/videos/{r['video_id']}/file"
        return d


class JobTracker:
    """Потокобезопасный in-memory трекер задач."""

    def __init__(self, max_history: int = 200):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_history = max_history
        # Опциональный хук персистентности (modules.job_store): вызывается на
        # создании и терминальных переходах, чтобы job переживал рестарт.
        self._persist_hook = None

    def set_persist_hook(self, hook) -> None:
        self._persist_hook = hook

    def _persist(self, job: "Job | None") -> None:
        if job is None or self._persist_hook is None:
            return
        try:
            self._persist_hook(job)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("job persist hook failed")

    def create(
        self,
        user_id: int,
        scenario: str = "",
        track_name: str = "",
        orientation: str = "portrait",
        total: int = 1,
        command_id: str = "",
        params: dict | None = None,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex[:16],
            user_id=user_id,
            scenario=scenario,
            track_name=track_name,
            orientation=orientation,
            total=total,
            command_id=command_id,
            params=params or {},
            current_message=f"Генерация {scenario} запущена",
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._trim()
        self._persist(job)
        return job

    def restore(self, job: Job) -> Job:
        """Вставляет job, восстановленный из персистентного стора (reconcile)."""
        with self._lock:
            self._jobs[job.job_id] = job
            self._trim()
        return job

    def update(
        self,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        total: Optional[int] = None,
        current_phase: Optional[str] = None,
        current_message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if total is not None:
                job.total = total
            if current_phase is not None:
                job.current_phase = current_phase
            if current_message is not None:
                job.current_message = current_message
            if error is not None:
                job.error = error
            job.updated_at = time.time()
            return job

    def complete(self, job_id: str, results: list = None) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.status = "done"
            job.current_phase = "done"
            job.current_message = "Генерация завершена"
            job.progress = job.total
            job.results = results or []
            job.updated_at = time.time()
        self._persist(job)
        return job

    def fail(self, job_id: str, error: str = "") -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.status = "error"
            job.current_phase = "error"
            job.current_message = error or "Ошибка генерации"
            job.error = error
            job.updated_at = time.time()
        self._persist(job)
        return job

    def stop(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "running":
                return None
            job.status = "stopped"
            job.current_phase = "stopped"
            job.current_message = "Остановлено"
            job.updated_at = time.time()
        self._persist(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_all(self) -> list[Job]:
        with self._lock:
            return sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True,
            )

    def list_active(self) -> list[Job]:
        return [j for j in self.list_all() if j.status == "running"]

    def _trim(self):
        if len(self._jobs) <= self._max_history:
            return
        finished = [
            (jid, j) for jid, j in self._jobs.items()
            if j.status in ("done", "error", "stopped")
        ]
        finished.sort(key=lambda x: x[1].created_at)
        to_remove = len(self._jobs) - self._max_history
        for jid, _ in finished[:to_remove]:
            del self._jobs[jid]


# Глобальный синглтон
tracker = JobTracker()
