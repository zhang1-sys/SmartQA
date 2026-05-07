from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from config import (
    MESSAGE_DELIVERY_RETRY_BATCH_SIZE,
    MESSAGE_DELIVERY_RETRY_ENABLED,
    MESSAGE_DELIVERY_RETRY_INTERVAL_SECONDS,
)
from services.message_delivery_service import MessageDeliveryService
from services.repository import get_repository


_started = False
_lock = threading.Lock()


def start_message_delivery_retry_scheduler() -> None:
    global _started
    if not MESSAGE_DELIVERY_RETRY_ENABLED:
        return
    with _lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_retry_loop, name="message-delivery-retry", daemon=True)
        thread.start()


def _retry_loop() -> None:
    interval = max(30, MESSAGE_DELIVERY_RETRY_INTERVAL_SECONDS)
    batch_size = max(1, min(MESSAGE_DELIVERY_RETRY_BATCH_SIZE, 20))
    consecutive_failures = 0
    while True:
        repository = get_repository()
        try:
            result = MessageDeliveryService(repository).retry_failed_deliveries(limit=batch_size)
            consecutive_failures = 0 if result.get("ok") else consecutive_failures + 1
            _record_retry_state(repository, interval, batch_size, consecutive_failures, result=result)
        except Exception as exc:
            consecutive_failures += 1
            print(f"Message delivery retry scheduler failed: {exc}")
            _record_retry_state(repository, interval, batch_size, consecutive_failures, error=str(exc))
        time.sleep(interval)


def _record_retry_state(
    repository,
    interval: int,
    batch_size: int,
    consecutive_failures: int,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if not hasattr(repository, "upsert_wecom_runtime_state"):
        return
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "interval_seconds": interval,
        "batch_size": batch_size,
        "consecutive_failures": consecutive_failures,
        "last_error": error,
    }
    if result is not None:
        results = result.get("results") or []
        metadata.update(
            {
                "last_success_at": now,
                "attempted": result.get("attempted", 0),
                "sent": len([item for item in results if item.get("delivery_status") == "sent"]),
                "failed": len([item for item in results if item.get("delivery_status") == "failed"]),
                "skipped": len([item for item in results if item.get("error")]),
            }
        )
    else:
        metadata["last_failure_at"] = now
    repository.upsert_wecom_runtime_state("message_delivery_retry", "running", metadata)
