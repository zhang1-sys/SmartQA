from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ["INTERNAL_AUTH_REQUIRED"] = "true"
os.environ["WECOM_KF_POLL_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import init_app


def main():
    app = init_app()
    client = app.test_client()

    public_response = client.get("/api/system/health")
    print("/api/system/health", public_response.status_code)
    assert public_response.status_code == 200

    session_response = client.get("/api/auth/session")
    print("/api/auth/session", session_response.status_code)
    assert session_response.status_code == 401

    protected_response = client.get("/api/conversations")
    print("/api/conversations protected", protected_response.status_code)
    assert protected_response.status_code == 401

    internal_chat_response = client.post("/api/chat", json={"session_id": "auth-smoke", "message": "内部消息"})
    print("/api/chat internal protected", internal_chat_response.status_code)
    assert internal_chat_response.status_code == 401

    customer_register_response = client.post(
        "/api/customer/register",
        json={"company": "鉴权客户公司", "name": "客户张"},
    )
    print("/api/customer/register public", customer_register_response.status_code)
    assert customer_register_response.status_code == 200
    customer = customer_register_response.get_json()
    session_id = customer["session_id"]

    customer_chat_without_token = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "channel": "web_customer",
            "source": "customer",
            "message": "100mm岩棉板多少钱？",
        },
    )
    print("/api/chat customer no token", customer_chat_without_token.status_code)
    assert customer_chat_without_token.status_code == 401

    customer_chat_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "access_token": customer["access_token"],
            "channel": "web_customer",
            "source": "customer",
            "message": "100mm岩棉板多少钱？",
        },
    )
    print("/api/chat customer public", customer_chat_response.status_code)
    assert customer_chat_response.status_code == 200

    customer_history_response = client.get(f"/api/customer/history?session_id={session_id}&access_token={customer['access_token']}")
    print("/api/customer/history public", customer_history_response.status_code)
    assert customer_history_response.status_code == 200

    wecom_status_response = client.get("/api/wecom/status")
    print("/api/wecom/status protected", wecom_status_response.status_code)
    assert wecom_status_response.status_code == 401

    callback_response = client.get("/wecom/callback")
    print("/wecom/callback public", callback_response.status_code)
    assert callback_response.status_code in {200, 403}


if __name__ == "__main__":
    main()
