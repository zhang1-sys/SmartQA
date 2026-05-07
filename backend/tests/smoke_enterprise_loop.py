from __future__ import annotations

from pathlib import Path
import sys
import os
import uuid
from unittest.mock import patch

os.environ.setdefault("INTERNAL_AUTH_REQUIRED", "false")
os.environ["WECOM_KF_POLL_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auth_service
from unittest.mock import patch
from app import init_app
from services.repository import get_repository
from wecom_kf_gateway import handle_simulated_text


def main():
    auth_service.INTERNAL_AUTH_REQUIRED = False
    with patch("app.start_message_delivery_retry_scheduler"):
        app = init_app()
    client = app.test_client()

    for path in ["/api/system/health", "/api/conversations", "/api/dashboard", "/api/knowledge", "/api/knowledge-gaps"]:
        response = client.get(path)
        print(path, response.status_code)
        assert response.status_code == 200

    response = client.post(
        "/api/chat",
        json={"session_id": "script-smoke", "message": "XPS和岩棉板哪个更适合外墙？"},
    )
    body = response.get_json()
    print("/api/chat", response.status_code, body["decision"]["action"])
    assert response.status_code == 200
    assert body["decision"]["action"] == "send"
    assert body["qa"]["passed"] is True
    conversation_id = body["conversation_id"]

    response = client.get(f"/api/conversations/{conversation_id}")
    detail = response.get_json()
    print(
        "/api/conversations/:id detail",
        response.status_code,
        len(detail.get("messages", [])),
        len(detail.get("ai_runs", [])),
    )
    assert response.status_code == 200
    assert detail.get("messages")
    assert detail.get("ai_runs")
    assistant_messages = [message for message in detail["messages"] if message.get("role") == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1].get("qa")
    assert assistant_messages[-1].get("ai_run")
    assert assistant_messages[-1].get("decision", {}).get("action") == "send"

    response = client.post(
        "/api/customer/register",
        json={"company": "脚本网页客户公司", "name": "网页王经理", "phone": "13800000000"},
    )
    customer = response.get_json()
    print("/api/customer/register", response.status_code, customer.get("session_id"))
    assert response.status_code == 200
    assert customer["session_id"].startswith("web-")
    assert customer["access_token"]

    response = client.get(f"/api/customer/history?session_id={customer['session_id']}")
    print("/api/customer/history unauthorized", response.status_code)
    assert response.status_code == 401

    response = client.post(
        "/api/chat",
        json={
            "session_id": customer["session_id"],
            "channel": "web_customer",
            "source": "customer",
            "customer_name": "网页王经理",
            "customer_type": "脚本网页客户公司",
            "message": "\u51b7\u8865\u6599\u96e8\u5929\u80fd\u65bd\u5de5\u5417\uff1f",
        },
    )
    print("/api/chat web_customer unauthorized", response.status_code)
    assert response.status_code == 401

    response = client.post(
        "/api/chat",
        json={
            "session_id": customer["session_id"],
            "access_token": customer["access_token"],
            "channel": "web_customer",
            "source": "customer",
            "customer_name": "网页王经理",
            "customer_type": "脚本网页客户公司",
            "message": "100mm岩棉板多少钱？",
        },
    )
    customer_chat = response.get_json()
    print("/api/chat web_customer", response.status_code, customer_chat["decision"]["action"])
    assert response.status_code == 200
    assert customer_chat["conversation_id"] == customer["conversation_id"]

    response = client.get(f"/api/conversations/{customer['conversation_id']}")
    customer_detail = response.get_json()
    print("/api/conversations/:id memory", response.status_code, bool(customer_detail.get("customer_memory")))
    assert response.status_code == 200
    assert customer_detail.get("customer_memory")
    memory = customer_detail["customer_memory"]
    assert memory.get("profile", {}).get("id")
    assert any(fact.get("fact_type") == "product_interest" for fact in memory.get("facts", []))
    assert memory.get("summary", {}).get("turn_count", 0) >= 1

    response = client.get(f"/api/customer/history?session_id={customer['session_id']}&access_token={customer['access_token']}")
    history = response.get_json()
    print("/api/customer/history", response.status_code, len(history.get("messages", [])))
    assert response.status_code == 200
    assert len(history["messages"]) >= 1
    if customer_chat["decision"]["action"] == "send":
        assert len(history["messages"]) >= 2

    response = client.post(
        f"/api/conversations/{conversation_id}/human-reply",
        json={"content": "人工已跟进，稍后给您完整方案。"},
    )
    print("/api/conversations/:id/human-reply", response.status_code, response.get_json().get("delivery_status"))
    assert response.status_code == 200

    response = client.patch(f"/api/conversations/{conversation_id}/status", json={"status": "resolved"})
    print("/api/conversations/:id/status", response.status_code)
    assert response.status_code == 200

    xml = Path(__file__).with_name("wecom_plaintext_message.xml").read_text(encoding="utf-8")
    response = client.post("/wecom/callback", data=xml, content_type="application/xml")
    print("/wecom/callback", response.status_code, response.get_data(as_text=True))
    assert response.status_code == 200
    response = client.post("/wecom/callback", data=xml, content_type="application/xml")
    print("/wecom/callback duplicate", response.status_code, response.get_data(as_text=True))
    assert response.status_code == 200

    response = client.get("/api/wecom/status")
    wecom_status = response.get_json()
    print("/api/wecom/status", response.status_code, wecom_status["enabled"])
    assert response.status_code == 200
    assert wecom_status["callback_url"].endswith("/wecom/callback")
    assert wecom_status["readiness"]["callback_path"] == "/wecom/callback"
    assert wecom_status["readiness"]["text_message_supported"] is True

    with patch("app.WECOM_KF_ENABLED", False):
        response = client.post("/api/wecom-kf/sync", json={})
        print("/api/wecom-kf/sync disabled", response.status_code)
        assert response.status_code == 400

    with patch("app.WECOM_KF_ENABLED", True), patch("app.sync_customer_service_messages") as sync_mock:
        sync_mock.return_value = {
            "errcode": 0,
            "errmsg": "ok",
            "msg_list": [],
            "next_cursor": "script-cursor",
            "has_more": False,
        }
        response = client.post("/api/wecom-kf/sync", json={})
        sync_body = response.get_json()
        print("/api/wecom-kf/sync", response.status_code, sync_body.get("msg_count"))
        assert response.status_code == 200
        assert sync_body["ok"] is True
        assert sync_body["msg_count"] == 0
        assert sync_body["next_cursor"] == "script-cursor"
        assert "persisted_cursor" in sync_body
        assert isinstance(sync_body["recent_wecom_kf_conversations"], list)

    response = client.post("/api/messages/not-found/delivery/retry", json={})
    print("/api/messages/:id/delivery/retry missing", response.status_code)
    assert response.status_code == 400

    response = client.post("/api/messages/delivery/retry-failed", json={"limit": 2})
    print("/api/messages/delivery/retry-failed", response.status_code, response.get_json().get("attempted"))
    assert response.status_code == 200

    response = client.post(
        "/api/wecom/simulate",
        json={"from_user": "script-wecom-sim", "content": "冷补料雨天能施工吗？多少钱一袋？"},
    )
    simulated = response.get_json()
    print("/api/wecom/simulate", response.status_code, simulated.get("ok"), (simulated.get("conversation") or {}).get("status"))
    assert response.status_code == 200
    assert simulated["ok"] is True
    assert simulated["conversation"]["channel"] == "wecom"
    wecom_conversation_id = simulated["conversation"]["id"]
    response = client.get(f"/api/conversations/{wecom_conversation_id}")
    wecom_detail = response.get_json()
    wecom_assistant_messages = [m for m in wecom_detail.get("messages", []) if m.get("role") == "assistant"]
    assert wecom_assistant_messages
    assert wecom_assistant_messages[-1].get("delivery_status") in {"stored", "sent", "failed"}

    repo = get_repository()
    kf_user = f"script-kf-welcome-{uuid.uuid4().hex[:8]}"
    first = handle_simulated_text(
        repo,
        open_kfid="script-open-kfid",
        external_userid=kf_user,
        content="你们门店在哪？",
        msgid=f"script-kf-welcome-{uuid.uuid4().hex}",
    )
    assert first["ok"] is True
    kf_conv = repo.find_conversation_by_external_id(f"wecom-kf-script-open-kfid-{kf_user}", channel="wecom_kf")
    assert kf_conv
    kf_detail = repo.get_conversation(str(kf_conv["id"]))
    welcome_messages = [
        message for message in kf_detail.get("messages", [])
        if (message.get("raw_payload") or {}).get("source") == "wecom_kf_welcome"
        or "欢迎咨询鑫源保温防水防火批发" in (message.get("content") or "")
    ]
    print("/wecom-kf welcome", len(welcome_messages))
    assert len(welcome_messages) == 1
    second = handle_simulated_text(
        repo,
        open_kfid="script-open-kfid",
        external_userid=kf_user,
        content="找谁报价？",
        msgid=f"script-kf-welcome-{uuid.uuid4().hex}",
    )
    assert second["ok"] is True
    kf_detail = repo.get_conversation(str(kf_conv["id"]))
    welcome_messages = [
        message for message in kf_detail.get("messages", [])
        if (message.get("raw_payload") or {}).get("source") == "wecom_kf_welcome"
        or "欢迎咨询鑫源保温防水防火批发" in (message.get("content") or "")
    ]
    assert len(welcome_messages) == 1

    response = client.post(
        "/api/chat",
        json={"session_id": "script-handoff", "message": "上次货破损了，你们不处理我就投诉退款"},
    )
    handoff_body = response.get_json()
    print("/api/chat handoff", response.status_code, handoff_body["decision"]["action"])
    assert response.status_code == 200
    assert handoff_body["decision"]["action"] == "handoff"
    assert handoff_body["decision"]["needs_human"] is True

    response = client.post(
        "/api/chat",
        json={"session_id": "script-gap", "message": "有没有特殊定制防火政策？"},
    )
    gap_body = response.get_json()
    print("/api/chat gap", response.status_code, bool(gap_body.get("knowledge_gap")), gap_body["decision"]["action"])
    assert response.status_code == 200
    assert gap_body.get("knowledge_gap")
    assert gap_body["decision"]["action"] in {"handoff", "no_answer"}

    response = client.get("/api/knowledge-gaps")
    assert response.status_code == 200
    gaps = response.get_json()
    target_gap = next((gap for gap in gaps if gap.get("question") == "有没有特殊定制防火政策？"), None)
    assert target_gap
    response = client.post(
        f"/api/knowledge-gaps/{target_gap['id']}/promote",
        json={
            "item_type": "faq",
            "title": "特殊定制防火政策咨询",
            "category": "售前政策",
            "question": target_gap["question"],
            "answer": "特殊定制防火政策需要结合产品类型、项目所在地消防要求、检测报告和供货批次人工核实。可先收集项目类型、面积、耐火等级要求和交付周期，再由技术或商务同事确认。",
            "usage_scenarios": "非标定制、防火等级、政策承诺类咨询",
        },
    )
    promoted = response.get_json()
    print("/api/knowledge-gaps/:id/promote", response.status_code, promoted.get("knowledge_item", {}).get("sync_status"))
    assert response.status_code == 200
    assert promoted["knowledge_item"]["id"]
    assert promoted["gap"].get("status") == "added_to_kb"
    if gaps:
        response = client.patch(f"/api/knowledge-gaps/{gaps[0]['id']}", json={"status": "drafted"})
        print("/api/knowledge-gaps/:id", response.status_code, response.get_json().get("status"))
        assert response.status_code == 200


if __name__ == "__main__":
    main()
