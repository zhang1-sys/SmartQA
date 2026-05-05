from __future__ import annotations

import threading
import time

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
    cursor = ""
    interval = max(10, WECOM_KF_POLL_INTERVAL_SECONDS)
    while True:
        try:
            result = sync_customer_service_messages(get_repository(), cursor=cursor)
            next_cursor = result.get("next_cursor") or cursor
            if next_cursor:
                cursor = next_cursor
            interval = max(10, WECOM_KF_POLL_INTERVAL_SECONDS)
        except Exception as exc:
            print(f"WeCom KF poll failed: {exc}")
            if "45009" in str(exc) or "freq out of limit" in str(exc):
                interval = min(max(interval * 2, 30), 300)
        time.sleep(interval)
