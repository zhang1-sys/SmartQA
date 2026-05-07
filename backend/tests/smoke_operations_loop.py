from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("INTERNAL_AUTH_REQUIRED", "false")
os.environ["WECOM_KF_POLL_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth_service
from app import init_app
from services.repository import get_repository


def main():
    auth_service.INTERNAL_AUTH_REQUIRED = False
    with patch("app.start_message_delivery_retry_scheduler"), patch("app.start_wecom_kf_poller"):
        app = init_app()
    repo = get_repository()
    conversation = repo.create_conversation(
        external_id=f"ops-loop-{uuid.uuid4().hex}",
        customer_name="ops-loop-smoke",
        customer_type="test",
        channel="internal",
    )
    client = app.test_client()
    response = client.patch(
        f"/api/conversations/{conversation['id']}/operations",
        json={
            "lead_status": "quoted",
            "quotation_status": "sent",
            "quotation_amount": 12800,
            "conversion_stage": "quoted",
            "next_follow_up_at": "2026-05-08T09:00:00+08:00",
        },
    )
    body = response.get_json()
    print("/api/conversations/:id/operations", response.status_code, body.get("lead_status"))
    assert response.status_code == 200
    assert body["lead_status"] == "quoted"
    assert body["quotation_status"] == "sent"
    assert body["conversion_stage"] == "quoted"

    bad = client.patch(f"/api/conversations/{conversation['id']}/operations", json={"lead_status": "bad"})
    print("/api/conversations/:id/operations invalid", bad.status_code)
    assert bad.status_code == 400


if __name__ == "__main__":
    main()
