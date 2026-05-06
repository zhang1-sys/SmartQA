from __future__ import annotations

from typing import Any

from config import WECOM_KF_OPEN_KFID
from wecom_client import wecom_client


class MessageDeliveryService:
    def __init__(self, repository):
        self.repository = repository

    def retry_failed_delivery(self, message_id: str) -> dict[str, Any]:
        if not hasattr(self.repository, "get_message"):
            return {"ok": False, "error": "repository_does_not_support_message_lookup"}
        message = self.repository.get_message(message_id)
        if not message:
            return {"ok": False, "error": "message_not_found"}
        if message.get("direction") != "outbound":
            return {"ok": False, "error": "message_is_not_outbound"}
        if message.get("delivery_status") != "failed":
            return {"ok": False, "error": "message_delivery_is_not_failed", "delivery_status": message.get("delivery_status")}

        conversation = self.repository.get_conversation(str(message.get("conversation_id")))
        if not conversation:
            return {"ok": False, "error": "conversation_not_found"}

        channel = conversation.get("channel") or message.get("channel")
        content = message.get("content") or ""
        if not content.strip():
            return {"ok": False, "error": "message_content_empty"}

        try:
            target = self._send(channel, conversation, content)
        except Exception as exc:
            error = str(exc)
            self.repository.update_message_delivery_status(str(message_id), "failed", error)
            self._audit(message_id, conversation, channel, "failed", error)
            return {"ok": False, "delivery_status": "failed", "delivery_error": error, "channel": channel}

        self.repository.update_message_delivery_status(str(message_id), "sent", None)
        self._audit(message_id, conversation, channel, "sent", None)
        return {"ok": True, "delivery_status": "sent", "channel": channel, "target": target}

    def retry_failed_deliveries(self, limit: int = 10) -> dict[str, Any]:
        if not hasattr(self.repository, "list_failed_deliveries"):
            return {"ok": False, "error": "repository_does_not_support_failed_delivery_list", "results": []}
        messages = self.repository.list_failed_deliveries(limit=limit)
        results = [self.retry_failed_delivery(str(message["id"])) for message in messages if message.get("id")]
        return {"ok": True, "attempted": len(results), "results": results}

    def _send(self, channel: str, conversation: dict[str, Any], content: str) -> dict[str, str]:
        contact = self.repository.get_wecom_contact_for_conversation(str(conversation["id"])) if hasattr(self.repository, "get_wecom_contact_for_conversation") else None
        if channel == "wecom":
            external_user_id = (contact or {}).get("external_user_id")
            if not external_user_id:
                raise RuntimeError("missing_wecom_external_user_id")
            wecom_client.send_text(external_user_id, content)
            return {"external_user_id": external_user_id}

        if channel == "wecom_kf":
            external_userid = (contact or {}).get("external_user_id")
            open_kfid = _contact_open_kfid(contact) or _conversation_open_kfid(conversation) or WECOM_KF_OPEN_KFID
            if not external_userid:
                raise RuntimeError("missing_wecom_kf_external_userid")
            if not open_kfid:
                raise RuntimeError("missing_wecom_kf_open_kfid")
            wecom_client.send_customer_service_text(
                open_kfid=open_kfid,
                external_userid=external_userid,
                content=content,
            )
            return {"external_userid": external_userid, "open_kfid": open_kfid}

        raise RuntimeError(f"unsupported_delivery_channel:{channel}")

    def _audit(
        self,
        message_id: str,
        conversation: dict[str, Any],
        channel: str,
        delivery_status: str,
        delivery_error: str | None,
    ) -> None:
        if not hasattr(self.repository, "add_audit_log"):
            return
        self.repository.add_audit_log(
            actor_type="admin",
            action="message.delivery_retry",
            target_type="message",
            target_id=str(message_id),
            metadata={
                "conversation_id": str(conversation.get("id")),
                "channel": channel,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
            },
        )


def _conversation_open_kfid(conv: dict[str, Any]) -> str:
    external_id = conv.get("external_conversation_id") or ""
    if external_id.startswith("wecom-kf-"):
        return external_id.removeprefix("wecom-kf-").rsplit("-", 1)[0]
    return ""


def _contact_open_kfid(contact: dict[str, Any] | None) -> str:
    if not contact:
        return ""
    raw_profile = contact.get("raw_profile") or {}
    if isinstance(raw_profile, dict):
        return raw_profile.get("open_kfid") or ""
    return ""
