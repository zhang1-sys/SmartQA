from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from config import WECOM_KF_ENABLED, WECOM_KF_OPEN_KFID, WECOM_KF_POLL_ENABLED, WECOM_KF_POLL_INTERVAL_SECONDS
from services.repository import get_repository
from wecom_kf_gateway import sync_customer_service_messages


_started = False
_lock = threading.Lock()


def start_wecom_kf_poller() -> None:
    global _started
    if not (WECOM_KF_ENABLED and WECOM_KF_OPEN_KFID and WECOM_KF_POLL_ENABLED):
        return
    with _lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_poll_loop, name="wecom-kf-poller", daemon=True)
        thread.start()


def _poll_loop() -> None:
    cursor = _load_cursor(get_repository())
    interval = max(10, WECOM_KF_POLL_INTERVAL_SECONDS)
    consecutive_failures = 0
    while True:
        repository = get_repository()
        try:
            result = sync_customer_service_messages(repository, cursor=cursor)
            next_cursor = result.get("next_cursor") or cursor
            if next_cursor:
                cursor = next_cursor
            interval = max(10, WECOM_KF_POLL_INTERVAL_SECONDS)
            consecutive_failures = 0
            _record_poller_state(repository, cursor, interval, consecutive_failures, result=result)
        except Exception as exc:
            consecutive_failures += 1
            print(f"WeCom KF poll failed: {exc}")
            if "45009" in str(exc) or "freq out of limit" in str(exc):
                interval = min(max(interval * 2, 30), 300)
            else:
                interval = min(max(interval, 30), 300)
            _record_poller_state(repository, cursor, interval, consecutive_failures, error=str(exc))
        time.sleep(interval)


def _load_cursor(repository) -> str:
    if not hasattr(repository, "get_wecom_runtime_state"):
        return ""
    state = repository.get_wecom_runtime_state("kf_sync_cursor") or {}
    return str(state.get("state_value") or "")


def _record_poller_state(
    repository,
    cursor: str,
    interval: int,
    consecutive_failures: int,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if not hasattr(repository, "upsert_wecom_runtime_state"):
        return
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "cursor_present": bool(cursor),
        "interval_seconds": interval,
        "consecutive_failures": consecutive_failures,
        "last_error": error,
    }
    if result is not None:
        metadata.update({
            "last_success_at": now,
            "msg_count": len(result.get("msg_list", [])),
            "has_more": bool(result.get("has_more")),
        })
    else:
        metadata["last_failure_at"] = now
    repository.upsert_wecom_runtime_state("kf_poller", "running", metadata)
