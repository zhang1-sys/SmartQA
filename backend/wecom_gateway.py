from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from config import WECOM_CORP_ID, WECOM_TOKEN
from services.ai_orchestration_service import AIOrchestrationService
from supabase_client import SupabaseError
from wecom_client import wecom_client
from wecom_crypto import decrypt_message, verify_signature
from wecom_kf_gateway import handle_plaintext_callback_payload as handle_wecom_kf_event


def verify_url(args) -> tuple[str, int]:
    msg_signature = args.get("msg_signature") or args.get("signature", "")
    timestamp = args.get("timestamp", "")
    nonce = args.get("nonce", "")
    echostr = args.get("echostr", "")
    encrypted = echostr if msg_signature else ""
    verification = verify_signature(WECOM_TOKEN, msg_signature, timestamp, nonce, encrypted)
    if not verification.ok:
        return verification.reason, 403
    if msg_signature and echostr:
        try:
            return decrypt_message(echostr, corp_id=WECOM_CORP_ID), 200
        except Exception as exc:
            return f"decrypt echostr failed: {exc}", 403
    return echostr, 200


def handle_callback(args, body: str, repository) -> tuple[str, int]:
    msg_signature = args.get("msg_signature") or args.get("signature", "")
    timestamp = args.get("timestamp", "")
    nonce = args.get("nonce", "")
    encrypted = _extract_encrypt(body)

    if msg_signature:
        verification = verify_signature(WECOM_TOKEN, msg_signature, timestamp, nonce, encrypted)
        if not verification.ok:
            return verification.reason, 403

    if encrypted:
        try:
            body = decrypt_message(encrypted, corp_id=WECOM_CORP_ID)
        except Exception as exc:
            return f"decrypt message failed: {exc}", 400

    payload = parse_plaintext_xml(body)
    if payload.get("event") == "kf_msg_or_event":
        handle_wecom_kf_event(payload, repository)
        return "success", 200

    if not payload.get("content"):
        return "unsupported message", 200

    external_user_id = payload.get("from_user") or payload.get("user_id") or "unknown-wecom-user"
    contact = _upsert_contact_if_supported(repository, external_user_id, payload)
    conversation_external_id = f"wecom-{external_user_id}"

    existing = repository.find_conversation_by_external_id(conversation_external_id, channel="wecom")
    if not existing:
        existing = repository.create_conversation(
            conversation_external_id,
            customer_name=payload.get("from_user") or "企业微信客户",
            customer_type="未知",
            channel="wecom",
            customer_id=contact.get("id") if contact else None,
        )

    try:
        msg_id = repository.add_message(
            existing["id"],
            "customer",
            payload["content"],
            direction="inbound",
            channel="wecom",
            raw_payload=payload,
            wecom_msg_id=payload.get("msg_id"),
        )
    except SupabaseError as exc:
        if payload.get("msg_id") and "duplicate key value" in str(exc):
            return "success", 200
        raise

    result = AIOrchestrationService(repository).handle_customer_message(
        conversation_id=existing["id"],
        trigger_message_id=msg_id,
        message=payload["content"],
        channel="wecom",
        customer_profile={
            "name": existing.get("customer_name") or "企业微信客户",
            "type": existing.get("customer_type") or "未知",
            "source": "wecom",
        },
    )

    assistant_message_id = result.get("assistant_message_id")
    if result["decision"]["action"] == "send" and wecom_client.enabled():
        delivery_status = "stored"
        delivery_error = None
        try:
            wecom_client.send_text(external_user_id, result["answer"])
            delivery_status = "sent"
        except Exception as exc:
            delivery_status = "failed"
            delivery_error = str(exc)
        if assistant_message_id and hasattr(repository, "update_message_delivery_status"):
            repository.update_message_delivery_status(assistant_message_id, delivery_status, delivery_error)
        if hasattr(repository, "add_audit_log"):
            repository.add_audit_log(
                actor_type="wecom",
                action="wecom.auto_reply_delivery",
                target_type="message",
                target_id=str(assistant_message_id) if assistant_message_id else None,
                metadata={
                    "conversation_id": str(existing["id"]),
                    "external_user_id": external_user_id,
                    "delivery_status": delivery_status,
                    "delivery_error": delivery_error,
                    "decision": result.get("decision"),
                },
            )
        if delivery_status == "failed":
            repository.update_conversation_status(existing["id"], "needs_human")

    return "success" if result else "success", 200


def parse_plaintext_xml(body: str) -> dict[str, Any]:
    root = ET.fromstring(body)

    def text(name: str) -> str:
        node = root.find(name)
        return node.text if node is not None and node.text is not None else ""

    return {
        "to_user": text("ToUserName"),
        "from_user": text("FromUserName"),
        "create_time": text("CreateTime"),
        "msg_type": text("MsgType"),
        "event": text("Event"),
        "token": text("Token"),
        "open_kfid": text("OpenKfId") or text("OpenKfID"),
        "content": text("Content").strip(),
        "msg_id": text("MsgId") or text("MsgID"),
        "agent_id": text("AgentID"),
    }


def _extract_encrypt(body: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    node = root.find("Encrypt")
    return node.text if node is not None and node.text else ""


def _upsert_contact_if_supported(repository, external_user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if hasattr(repository, "upsert_wecom_contact"):
        return repository.upsert_wecom_contact(external_user_id, display_name=external_user_id, raw_profile=payload)
    return None
