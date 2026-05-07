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
from services.non_text_service import NonTextService


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

    audio_unconfigured = client.post(
        "/api/non-text/transcribe",
        data={"kind": "audio", "file": (BytesIO(b"not-a-real-wav"), "probe.wav")},
        content_type="multipart/form-data",
    )
    audio_unconfigured_body = audio_unconfigured.get_json()
    print("/api/non-text/transcribe audio", audio_unconfigured.status_code, audio_unconfigured_body.get("error"))
    assert audio_unconfigured.status_code in {400, 500}
    assert audio_unconfigured_body.get("error")

    with patch.object(NonTextService, "transcribe_audio", return_value={"kind": "audio", "text": "客户说需要冷补料报价", "raw": {}}):
        audio_ok = client.post(
            "/api/non-text/transcribe",
            data={"kind": "audio", "file": (BytesIO(b"fake-wav"), "probe.wav")},
            content_type="multipart/form-data",
        )
    audio_ok_body = audio_ok.get_json()
    print("/api/non-text/transcribe audio mocked", audio_ok.status_code, audio_ok_body.get("text"))
    assert audio_ok.status_code == 200
    assert audio_ok_body["kind"] == "audio"
    assert "冷补料" in audio_ok_body["text"]


if __name__ == "__main__":
    main()
