from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from message_delivery_retry_scheduler import _record_retry_state
from services.message_delivery_service import MessageDeliveryService


class FakeRepository:
    def __init__(self):
        self.states = []

    def list_failed_deliveries(self, limit=20):
        return []

    def upsert_wecom_runtime_state(self, state_key, state_value="", metadata=None):
        self.states.append({"state_key": state_key, "state_value": state_value, "metadata": metadata or {}})
        return self.states[-1]


def main():
    repo = FakeRepository()
    result = MessageDeliveryService(repo).retry_failed_deliveries(limit=5)
    assert result == {"ok": True, "attempted": 0, "results": []}

    _record_retry_state(repo, interval=120, batch_size=5, consecutive_failures=0, result=result)
    assert repo.states
    state = repo.states[-1]
    assert state["state_key"] == "message_delivery_retry"
    assert state["state_value"] == "running"
    assert state["metadata"]["attempted"] == 0
    assert state["metadata"]["interval_seconds"] == 120
    assert state["metadata"]["batch_size"] == 5
    print("message delivery retry scheduler smoke passed")


if __name__ == "__main__":
    main()
