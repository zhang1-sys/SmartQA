from __future__ import annotations

import os
import sys
from io import BytesIO
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
    response = client.post(
        "/api/non-text/transcribe",
        data={"kind": "image", "file": (BytesIO(b"not-a-real-image"), "probe.png")},
        content_type="multipart/form-data",
    )
    body = response.get_json()
    print("/api/non-text/transcribe image", response.status_code, body.get("error"))
    assert response.status_code in {400, 500}
    assert body.get("error")

    missing = client.post("/api/non-text/transcribe", data={}, content_type="multipart/form-data")
    print("/api/non-text/transcribe missing", missing.status_code)
    assert missing.status_code == 400


if __name__ == "__main__":
    main()
