from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from config import (
    WECOM_CORP_ID,
    WECOM_KF_IMMEDIATE_ACK_ENABLED,
    WECOM_KF_IMMEDIATE_ACK_TEXT,
    WECOM_KF_OPEN_KFID,
    WECOM_KF_WELCOME_ENABLED,
    WECOM_KF_WELCOME_TEXT,
    WECOM_TOKEN,
)
from services.ai_orchestration_service import AIOrchestrationService
from supabase_client import SupabaseError
from wecom_client import wecom_client
from wecom_crypto import decrypt_message, verify_signature


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
    try:
        payload = _parse_callback_payload(args, body)
        handle_plaintext_callback_payload(payload, repository)
    except Exception as exc:
        _log_sync(repository, {}, {}, error=str(exc))
    return "success", 200


def handle_plaintext_callback_payload(payload: dict[str, Any], repository) -> None:
    if payload.get("event") != "kf_msg_or_event":
        return
    sync_customer_service_messages(repository, token=payload.get("token", ""))


def sync_customer_service_messages(repository, *, token: str = "", cursor: str = "") -> dict[str, Any]:
    sync_result = wecom_client.sync_customer_service_messages(
        cursor=cursor,
        token=token,
        open_kfid=WECOM_KF_OPEN_KFID,
    )
    _log_sync(repository, {"token": bool(token), "cursor": cursor}, sync_result, error=None)
    _process_synced_messages(sync_result.get("msg_list", []), repository)
    return sync_result


def handle_simulated_text(repository, *, open_kfid: str, external_userid: str, content: str, msgid: str) -> dict[str, Any]:
    message = {
        "msgid": msgid,
        "open_kfid": open_kfid,
        "external_userid": external_userid,
        "msgtype": "text",
        "text": {"content": content},
        "origin": 3,
    }
    return _process_customer_text(message, repository)


def _parse_callback_payload(args, body: str) -> dict[str, str]:
    msg_signature = args.get("msg_signature") or args.get("signature", "")
    timestamp = args.get("timestamp", "")
    nonce = args.get("nonce", "")
    encrypted = _extract_encrypt(body)

    if msg_signature:
        verification = verify_signature(WECOM_TOKEN, msg_signature, timestamp, nonce, encrypted)
        if not verification.ok:
            raise ValueError(verification.reason)

    if encrypted:
        body = decrypt_message(encrypted, corp_id=WECOM_CORP_ID)

    root = ET.fromstring(body)

    def text(name: str) -> str:
        node = root.find(name)
        return node.text if node is not None and node.text is not None else ""

    return {
        "to_user": text("ToUserName"),
        "create_time": text("CreateTime"),
        "msg_type": text("MsgType"),
        "event": text("Event"),
        "token": text("Token"),
        "open_kfid": text("OpenKfId") or text("OpenKfID"),
    }


def _process_synced_messages(messages: list[dict[str, Any]], repository) -> None:
    for message in messages:
        if not _is_customer_message(message):
            continue
        if message.get("msgtype") != "text":
            _process_customer_non_text(message, repository)
            continue
        content = ((message.get("text") or {}).get("content") or "").strip()
        if not content:
            continue
        _process_customer_text(message, repository)


def _process_customer_non_text(message: dict[str, Any], repository) -> dict[str, Any]:
    open_kfid = message.get("open_kfid") or WECOM_KF_OPEN_KFID
    external_userid = message.get("external_userid") or "unknown-wecom-kf-user"
    msgid = message.get("msgid") or message.get("msg_id")
    msgtype = message.get("msgtype") or "unknown"
    label = _non_text_label(msgtype)
    content = f"[客户发送了{label}，系统已按非文本客服流程转人工处理。]"

    contact = _upsert_contact_if_supported(repository, external_userid, {**message, "channel": "wecom_kf"})
    conversation_external_id = f"wecom-kf-{open_kfid}-{external_userid}"
    existing = repository.find_conversation_by_external_id(conversation_external_id, channel="wecom_kf")
    is_new_conversation = not existing
    if not existing:
        existing = repository.create_conversation(
            conversation_external_id,
            customer_name=external_userid,
            customer_type="微信客服客户",
            channel="wecom_kf",
            customer_id=contact.get("id") if contact else None,
        )

    try:
        trigger_message_id = repository.add_message(
            existing["id"],
            "customer",
            content,
            direction="inbound",
            channel="wecom_kf",
            raw_payload=message,
            wecom_msg_id=msgid,
        )
    except SupabaseError as exc:
        if msgid and "duplicate key value" in str(exc):
            return {"ok": True, "duplicate": True, "conversation": existing}
        raise

    repository.update_conversation_status(existing["id"], "needs_human")
    notice_text = f"已收到您发送的{label}。为了避免识别错误，这类内容会转给人工客服处理，请稍等。"
    message_id = repository.add_message(
        existing["id"],
        "system",
        notice_text,
        direction="outbound",
        channel="wecom_kf",
        raw_payload={
            "source": "wecom_kf_non_text_notice",
            "trigger_message_id": str(trigger_message_id),
            "msgtype": msgtype,
        },
        delivery_status="stored",
    )
    delivery_status = "stored"
    delivery_error = None
    if wecom_client.customer_service_enabled():
        try:
            wecom_client.send_customer_service_text(
                open_kfid=open_kfid,
                external_userid=external_userid,
                content=notice_text,
            )
            delivery_status = "sent"
        except Exception as exc:
            delivery_status = "failed"
            delivery_error = str(exc)
        if hasattr(repository, "update_message_delivery_status"):
            repository.update_message_delivery_status(message_id, delivery_status)

    if hasattr(repository, "add_audit_log"):
        repository.add_audit_log(
            actor_type="wecom",
            action="wecom_kf.non_text_handoff",
            target_type="message",
            target_id=str(trigger_message_id),
            metadata={
                "conversation_id": str(existing["id"]),
                "notice_message_id": str(message_id),
                "open_kfid": open_kfid,
                "external_userid": external_userid,
                "msgtype": msgtype,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
            },
        )
    return {"ok": True, "conversation": existing, "handoff": True}


def _process_customer_text(message: dict[str, Any], repository) -> dict[str, Any]:
    open_kfid = message.get("open_kfid") or WECOM_KF_OPEN_KFID
    external_userid = message.get("external_userid") or "unknown-wecom-kf-user"
    msgid = message.get("msgid") or message.get("msg_id")
    content = ((message.get("text") or {}).get("content") or "").strip()
    if not content:
        return {"ok": False, "reason": "empty message"}

    contact = _upsert_contact_if_supported(repository, external_userid, {**message, "channel": "wecom_kf"})
    conversation_external_id = f"wecom-kf-{open_kfid}-{external_userid}"
    existing = repository.find_conversation_by_external_id(conversation_external_id, channel="wecom_kf")
    is_new_conversation = not existing
    if not existing:
        existing = repository.create_conversation(
            conversation_external_id,
            customer_name=external_userid,
            customer_type="微信客服客户",
            channel="wecom_kf",
            customer_id=contact.get("id") if contact else None,
        )

    try:
        trigger_message_id = repository.add_message(
            existing["id"],
            "customer",
            content,
            direction="inbound",
            channel="wecom_kf",
            raw_payload=message,
            wecom_msg_id=msgid,
        )
    except SupabaseError as exc:
        if msgid and "duplicate key value" in str(exc):
            return {"ok": True, "duplicate": True, "conversation": existing}
        raise

    _send_welcome_if_needed(
        repository,
        existing["id"],
        open_kfid,
        external_userid,
        trigger_message_id,
        is_new_conversation=is_new_conversation,
    )
    _send_immediate_ack(repository, existing["id"], open_kfid, external_userid, trigger_message_id)

    result = AIOrchestrationService(repository).handle_customer_message(
        conversation_id=existing["id"],
        trigger_message_id=trigger_message_id,
        message=content,
        channel="wecom_kf",
        customer_profile={
            "name": existing.get("customer_name") or external_userid,
            "type": existing.get("customer_type") or "微信客服客户",
            "source": "wecom_kf",
            "open_kfid": open_kfid,
        },
    )

    assistant_message_id = result.get("assistant_message_id")
    if result["decision"]["action"] == "send" and wecom_client.customer_service_enabled():
        delivery_status = "stored"
        delivery_error = None
        try:
            wecom_client.send_customer_service_text(
                open_kfid=open_kfid,
                external_userid=external_userid,
                content=result["answer"],
            )
            delivery_status = "sent"
        except Exception as exc:
            delivery_status = "failed"
            delivery_error = str(exc)
        if assistant_message_id and hasattr(repository, "update_message_delivery_status"):
            repository.update_message_delivery_status(assistant_message_id, delivery_status)
        if hasattr(repository, "add_audit_log"):
            repository.add_audit_log(
                actor_type="wecom",
                action="wecom_kf.auto_reply_delivery",
                target_type="message",
                target_id=str(assistant_message_id) if assistant_message_id else None,
                metadata={
                    "conversation_id": str(existing["id"]),
                    "open_kfid": open_kfid,
                    "external_userid": external_userid,
                    "delivery_status": delivery_status,
                    "delivery_error": delivery_error,
                    "decision": result.get("decision"),
                },
            )
        if delivery_status == "failed":
            repository.update_conversation_status(existing["id"], "needs_human")
    elif result["decision"]["action"] in {"handoff", "no_answer", "retry"}:
        _send_followup_notice(
            repository,
            existing["id"],
            open_kfid,
            external_userid,
            trigger_message_id,
            result,
        )

    return {"ok": True, "conversation": existing, "result": result}


def _send_welcome_if_needed(
    repository,
    conversation_id: str,
    open_kfid: str,
    external_userid: str,
    trigger_message_id: str,
    *,
    is_new_conversation: bool,
) -> None:
    if not (is_new_conversation and WECOM_KF_WELCOME_ENABLED and wecom_client.customer_service_enabled()):
        return
    welcome_text = WECOM_KF_WELCOME_TEXT.strip()
    if not welcome_text:
        return
    message_id = repository.add_message(
        conversation_id,
        "system",
        welcome_text,
        direction="outbound",
        channel="wecom_kf",
        raw_payload={
            "source": "wecom_kf_welcome",
            "trigger_message_id": str(trigger_message_id),
        },
        delivery_status="stored",
    )
    delivery_status = "stored"
    delivery_error = None
    try:
        wecom_client.send_customer_service_text(
            open_kfid=open_kfid,
            external_userid=external_userid,
            content=welcome_text,
        )
        delivery_status = "sent"
    except Exception as exc:
        delivery_status = "failed"
        delivery_error = str(exc)
    if hasattr(repository, "update_message_delivery_status"):
        repository.update_message_delivery_status(message_id, delivery_status)
    if hasattr(repository, "add_audit_log"):
        repository.add_audit_log(
            actor_type="wecom",
            action="wecom_kf.welcome_delivery",
            target_type="message",
            target_id=str(message_id),
            metadata={
                "conversation_id": str(conversation_id),
                "trigger_message_id": str(trigger_message_id),
                "open_kfid": open_kfid,
                "external_userid": external_userid,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
            },
        )


def _send_immediate_ack(
    repository,
    conversation_id: str,
    open_kfid: str,
    external_userid: str,
    trigger_message_id: str,
) -> None:
    if not (WECOM_KF_IMMEDIATE_ACK_ENABLED and wecom_client.customer_service_enabled()):
        return
    ack_text = WECOM_KF_IMMEDIATE_ACK_TEXT.strip()
    if not ack_text:
        return
    message_id = repository.add_message(
        conversation_id,
        "system",
        ack_text,
        direction="outbound",
        channel="wecom_kf",
        raw_payload={
            "source": "wecom_kf_immediate_ack",
            "trigger_message_id": str(trigger_message_id),
        },
        delivery_status="stored",
    )
    delivery_status = "stored"
    delivery_error = None
    try:
        wecom_client.send_customer_service_text(
            open_kfid=open_kfid,
            external_userid=external_userid,
            content=ack_text,
        )
        delivery_status = "sent"
    except Exception as exc:
        delivery_status = "failed"
        delivery_error = str(exc)
    if hasattr(repository, "update_message_delivery_status"):
        repository.update_message_delivery_status(message_id, delivery_status)
    if hasattr(repository, "add_audit_log"):
        repository.add_audit_log(
            actor_type="wecom",
            action="wecom_kf.immediate_ack_delivery",
            target_type="message",
            target_id=str(message_id),
            metadata={
                "conversation_id": str(conversation_id),
                "trigger_message_id": str(trigger_message_id),
                "open_kfid": open_kfid,
                "external_userid": external_userid,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
            },
        )


def _send_followup_notice(
    repository,
    conversation_id: str,
    open_kfid: str,
    external_userid: str,
    trigger_message_id: str,
    result: dict[str, Any],
) -> None:
    if not wecom_client.customer_service_enabled():
        return
    notice_text = "这个问题需要人工核实具体规格、库存或报价条件，我已转给人工客服处理，稍后会继续回复您。"
    message_id = repository.add_message(
        conversation_id,
        "system",
        notice_text,
        direction="outbound",
        channel="wecom_kf",
        raw_payload={
            "source": "wecom_kf_followup_notice",
            "trigger_message_id": str(trigger_message_id),
            "decision": result.get("decision"),
        },
        delivery_status="stored",
    )
    delivery_status = "stored"
    delivery_error = None
    try:
        wecom_client.send_customer_service_text(
            open_kfid=open_kfid,
            external_userid=external_userid,
            content=notice_text,
        )
        delivery_status = "sent"
    except Exception as exc:
        delivery_status = "failed"
        delivery_error = str(exc)
    if hasattr(repository, "update_message_delivery_status"):
        repository.update_message_delivery_status(message_id, delivery_status)
    if hasattr(repository, "add_audit_log"):
        repository.add_audit_log(
            actor_type="wecom",
            action="wecom_kf.followup_notice_delivery",
            target_type="message",
            target_id=str(message_id),
            metadata={
                "conversation_id": str(conversation_id),
                "trigger_message_id": str(trigger_message_id),
                "open_kfid": open_kfid,
                "external_userid": external_userid,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
                "decision": result.get("decision"),
            },
        )


def _extract_encrypt(body: str) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    node = root.find("Encrypt")
    return node.text if node is not None and node.text else ""


def _is_customer_message(message: dict[str, Any]) -> bool:
    origin = message.get("origin")
    if origin is None:
        return True
    return int(origin) in {3, 4}


def _non_text_label(msgtype: str) -> str:
    return {
        "image": "图片",
        "voice": "语音",
        "video": "视频",
        "file": "文件",
        "location": "位置",
        "link": "链接",
        "miniprogram": "小程序卡片",
    }.get(msgtype, "非文本消息")


def _upsert_contact_if_supported(repository, external_userid: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if hasattr(repository, "upsert_wecom_contact"):
        return repository.upsert_wecom_contact(external_userid, display_name=external_userid, raw_profile=payload)
    return None


def _log_sync(repository, callback_payload: dict[str, Any], sync_result: dict[str, Any], error: str | None) -> None:
    if not hasattr(repository, "add_audit_log"):
        return
    repository.add_audit_log(
        actor_type="wecom",
        action="wecom_kf.sync_msg",
        target_type="conversation",
        target_id=None,
        metadata={
            "callback": callback_payload,
            "msg_count": len(sync_result.get("msg_list", [])) if sync_result else 0,
            "next_cursor": sync_result.get("next_cursor") if sync_result else None,
            "has_more": sync_result.get("has_more") if sync_result else None,
            "error": error,
        },
    )
