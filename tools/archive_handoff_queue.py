from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.repository import get_repository


REAL_WECHAT_EXTERNAL = "wecom-kf-wkssvDGgAAZwjNxScTrXpfmFZpmrccaA-wmssvDGgAAc1GAUec-MvklQQuA_V7e3w"


def main() -> None:
    repo = get_repository()
    archived = 0
    for conv in repo.list_conversations():
        status = conv.get("status") or conv.get("status_code")
        external = conv.get("external_conversation_id") or conv.get("session_id") or ""
        if status not in {"needs_human", "resolved"}:
            continue
        if not _looks_like_cleanup_target(conv):
            continue
        conv_id = str(conv["id"])
        detail = repo.get_conversation(conv_id) or {}
        messages = detail.get("messages", [])
        last = messages[-1] if messages else {}
        reason = _reason(conv, last)
        _upsert_archive_message(repo, conv_id, reason)
        repo.update_conversation_status(conv_id, "resolved")
        _upsert_audit(repo, conv, last, reason)
        archived += 1
    print(f"handoff archived or repaired: {archived}")


def _looks_like_cleanup_target(conv: dict) -> bool:
    external = conv.get("external_conversation_id") or conv.get("session_id") or ""
    customer = conv.get("customer_name") or ""
    channel = conv.get("channel") or ""
    if external == REAL_WECHAT_EXTERNAL:
        return True
    return any(
        token in external or token in customer
        for token in ["script-", "local-", "codex-", "unknown-wecom-kf-user", "web-a63917c5692f", "web-0ef2c126211c"]
    ) or channel == "internal"


def _reason(conv: dict, last: dict) -> str:
    external = conv.get("external_conversation_id") or conv.get("session_id") or ""
    if external == REAL_WECHAT_EXTERNAL:
        return "真实微信客服历史会话已有 AI 正式回复，本次仅关闭内部待人工告警，不额外触达客户。"
    if last.get("role") == "customer":
        return "历史测试会话停留在客户消息，本次仅关闭内部待人工告警，不额外触达客户。"
    return "历史联调/测试待人工队列已运营归档，不向客户额外发送消息。"


def _upsert_archive_message(repo, conversation_id: str, reason: str) -> None:
    content = f"运营归档：{reason}"
    rows = []
    if hasattr(repo, "client"):
        rows = repo.client.select(
            "messages",
            {
                "conversation_id": f"eq.{conversation_id}",
                "role": "eq.system",
                "select": "id,raw_payload,created_at",
                "order": "created_at.desc",
                "limit": "20",
            },
        )
    existing = None
    for row in rows:
        raw = row.get("raw_payload") or {}
        if isinstance(raw, dict) and raw.get("source") == "operations_handoff_cleanup":
            existing = row
            break
    payload = {
        "content": content,
        "raw_payload": {
            "source": "operations_handoff_cleanup",
            "previous_status": "needs_human",
            "reason": reason,
            "customer_notified": False,
        },
        "delivery_status": "stored",
    }
    if existing and hasattr(repo, "client"):
        repo.client.update("messages", {"id": f"eq.{existing['id']}"}, payload)
        return
    repo.add_message(
        conversation_id,
        "system",
        content,
        direction="outbound",
        channel="internal",
        raw_payload=payload["raw_payload"],
        delivery_status="stored",
    )


def _upsert_audit(repo, conv: dict, last: dict, reason: str) -> None:
    conv_id = str(conv["id"])
    metadata = {
        "channel": conv.get("channel"),
        "external_conversation_id": conv.get("external_conversation_id") or conv.get("session_id") or "",
        "customer_name": conv.get("customer_name"),
        "last_role": last.get("role"),
        "last_content_preview": _clean_preview(last.get("content") or "", reason),
        "reason": reason,
        "customer_notified": False,
    }
    if hasattr(repo, "client"):
        rows = repo.client.select(
            "audit_logs",
            {
                "action": "eq.conversation.handoff_archived",
                "target_id": f"eq.{conv_id}",
                "select": "id,created_at",
                "order": "created_at.desc",
                "limit": "5",
            },
        )
        if rows:
            repo.client.update("audit_logs", {"id": f"eq.{rows[0]['id']}"}, {"metadata": metadata})
            return
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="conversation.handoff_archived",
            target_type="conversation",
            target_id=conv_id,
            metadata=metadata,
        )


def _clean_preview(content: str, fallback: str) -> str:
    text = (content or "").strip()
    if not text or "??" in text or text.startswith("运营归档："):
        return fallback[:120]
    return text[:120]


if __name__ == "__main__":
    main()
