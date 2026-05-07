from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("INTERNAL_AUTH_REQUIRED", "false")
os.environ["WECOM_KF_POLL_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth_service
from app import init_app


def main():
    auth_service.INTERNAL_AUTH_REQUIRED = False
    with patch("app.start_message_delivery_retry_scheduler"), patch("app.start_wecom_kf_poller"):
        app = init_app()
    client = app.test_client()
    response = client.post("/api/knowledge/sync-pending", json={"limit": 2})
    body = response.get_json()
    print("/api/knowledge/sync-pending", response.status_code, body.get("attempted"))
    assert response.status_code == 200
    assert "available" in body
    assert "attempted" in body
    assert isinstance(body.get("results"), list)


if __name__ == "__main__":
    main()
