"""The background clock that drives automatic rotation.

Deliberately simple: one asyncio task, one sleep, one guarded call. It reads the
configuration on every tick rather than caching it, so switching rotation off in
the dashboard takes effect at the next tick without a restart.

The task must never die. A rotation that raises is logged and the loop carries
on, because a scheduler that silently stopped hours ago is worse than one that
occasionally fails loudly.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from app.core.logging import get_logger
from app.core.time_utils import utcnow

logger = get_logger(__name__)

#: How often the loop wakes to re-read the configuration. Kept short so a
#: changed interval or an "off" switch is picked up quickly.
TICK_SECONDS = 60.0


class RotationScheduler:
    """Runs :func:`rotation_service.run_rotation` on the configured interval."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_run_at = None
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="rotation-scheduler")
        logger.info("Rotation scheduler started")

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            # Shutdown is best effort: whatever the cancelled task raises, the
            # application still has to finish stopping.
            with contextlib.suppress(Exception):
                await task
        logger.info("Rotation scheduler stopped")

    async def _loop(self) -> None:
        from app.database.session import SessionLocal
        from app.services import rotation_service

        while self._running:
            try:
                await asyncio.sleep(TICK_SECONDS)
                if not self._running:
                    break

                with SessionLocal() as db:
                    config = rotation_service.get_config(db)
                    if not config.enabled:
                        continue
                    if not self._is_due(config.interval_minutes):
                        continue
                    logger.info(
                        "Rotation due",
                        extra={"interval_minutes": config.interval_minutes},
                    )
                    await rotation_service.run_rotation(self.context, db, triggered_by="schedule")
                    self.last_run_at = utcnow()
                    self.last_error = None
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = str(exc)[:300]
                logger.exception("Rotation tick failed")

    def _is_due(self, interval_minutes: int) -> bool:
        if self.last_run_at is None:
            return True
        elapsed = (utcnow() - self.last_run_at).total_seconds()
        return elapsed >= interval_minutes * 60

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "tick_seconds": TICK_SECONDS,
        }
