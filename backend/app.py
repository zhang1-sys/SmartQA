import uuid
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS

from auth_service import api_auth_required, is_public_customer_chat, verify_request
from config import (
    DIFY_ENABLED,
    DIFY_APP_MODE,
    FLASK_DEBUG,
    FLASK_PORT,
    MOCK_AI_ENABLED,
    SUPABASE_ENABLED,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    WECOM_AGENT_ID,
    WECOM_CORP_ID,
    WECOM_ENCODING_AES_KEY,
    WECOM_ENABLED,
    WECOM_KF_ENABLED,
    WECOM_KF_OPEN_KFID,
    WECOM_KF_POLL_ENABLED,
    WECOM_KF_SECRET,
    WECOM_PUBLIC_BASE_URL,
    WECOM_SECRET,
    WECOM_TOKEN,
)
from customer_access import issue_customer_token, verify_customer_token
from dify_client import effective_app_mode
from db import init_db
from services.ai_orchestration_service import AIOrchestrationService
from services.alert_service import OperationsAlertService
from services.data_governance import mask_json
from services.knowledge_quality_service import KnowledgeQualityService
from services.knowledge_ops_service import KnowledgeOpsService
from services.knowledge_base import knowledge_base
from services.message_delivery_service import MessageDeliveryService
from services.repository import get_repository
from supabase_client import supabase
from wecom_client import wecom_client
from message_delivery_retry_scheduler import start_message_delivery_retry_scheduler
from wecom_gateway import handle_callback as handle_wecom_callback
from wecom_gateway import verify_url as verify_wecom_url
from wecom_kf_gateway import handle_callback as handle_wecom_kf_callback
from wecom_kf_gateway import handle_simulated_text as handle_wecom_kf_simulated_text
from wecom_kf_gateway import sync_customer_service_messages
from wecom_kf_gateway import verify_url as verify_wecom_kf_url
from wecom_kf_poller import start_wecom_kf_poller

app = Flask(__name__)
CORS(app)


@app.before_request
def require_internal_auth():
    if is_public_customer_chat(request):
        return None
    if not api_auth_required(request.path):
        return None
    user, error = verify_request(request)
    if error:
        return jsonify({"error": "unauthorized", "reason": error}), 401
    g.current_user = user
    return None


def _seed_demo_data():
    """插入演示数据，让看板有真实数据展示。"""
    from db import get_db

    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    if count > 0:
        conn.close()
        return

    # 演示会话
    demos = [
        ("demo-001", "张经理", "施工方", "已解决"),
        ("demo-002", "李工", "总包方", "已解决"),
        ("demo-003", "王老板", "建材商", "已转人工"),
        ("demo-004", "赵工", "施工方", "进行中"),
        ("demo-005", "陈总", "开发商", "已解决"),
    ]
    for sid, name, ctype, status in demos:
        conn.execute(
            "INSERT INTO conversations (session_id, customer_name, customer_type, status) VALUES (?, ?, ?, ?)",
            (sid, name, ctype, status),
        )
    conn.commit()

    # 演示消息 & 质检结果
    import random

    demo_chats = [
        (1, "你好，我们项目需要100mm岩棉板，容重120的，大概要5000平，什么价格？"),
        (1, "张经理您好！100mm岩棉板（容重120kg/m³）批量报价为50元/m²，5000平以上可额外优惠3%。检测报告可提供。"),
        (1, "在山东济南，运费大概多少？另外岩棉板和挤塑板哪个更适合外墙？"),
        (1, "济南运费约3元/m²（专线物流3-5天到货）。岩棉板A级防火适合高层，挤塑板保温更好价格更低适合多层。"),
        (2, "XPS板导热系数是多少？50mm的够用吗？"),
        (2, "XPS导热系数≤0.030W/(m·K)，50mm热阻约1.67(m²·K)/W，寒冷地区建议用50mm以上。"),
        (3, "上次送的岩棉板有破损，你们不管吗？"),
        (3, "非常抱歉给您带来不便，我已记录您的情况。"),
        (4, "聚氨酯喷涂多少钱一平？施工要多久？"),
        (4, "聚氨酯喷涂约85元/m²（≥2000m²批量65元/m²）。喷涂后表干30分钟，完全固化24小时。"),
        (5, "我们需要一批外墙保温系统材料，能出整体方案吗？"),
        (5, "当然可以！请提供项目面积、建筑高度、所在城市，我为您量身定制保温方案。"),
    ]
    scores_pool = [
        {"accuracy": 5, "completeness": 5, "professionalism": 5, "empathy": 4, "efficiency": 5},
        {"accuracy": 4, "completeness": 4, "professionalism": 4, "empathy": 3, "efficiency": 4},
        {"accuracy": 5, "completeness": 4, "professionalism": 5, "empathy": 4, "efficiency": 5},
        {"accuracy": 3, "completeness": 3, "professionalism": 3, "empathy": 1, "efficiency": 3},
        {"accuracy": 4, "completeness": 5, "professionalism": 4, "empathy": 3, "efficiency": 4},
        {"accuracy": 5, "completeness": 4, "professionalism": 5, "empathy": 4, "efficiency": 5},
    ]
    for idx, (conv_id, content) in enumerate(demo_chats):
        role = "customer" if idx % 2 == 0 else "assistant"
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, role, content),
        )
        if role == "assistant":
            scores = random.choice(scores_pool)
            overall = sum(scores.values()) / 5.0
            passed = 1 if all(v >= 3 for v in scores.values()) else 0
            conn.execute(
                """INSERT INTO qa_results
                   (message_id, accuracy, completeness, professionalism, empathy, efficiency,
                    overall_score, passed, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cur.lastrowid,
                    scores["accuracy"],
                    scores["completeness"],
                    scores["professionalism"],
                    scores["empathy"],
                    scores["efficiency"],
                    round(overall, 2),
                    passed,
                    "自动评分",
                ),
            )
    conn.commit()

    # 演示知识盲区
    gaps = [
        ("保温砂浆施工配比", "紧急"),
        ("EPS与XPS性能对比", "中"),
        ("特殊规格定制流程", "中"),
        ("聚氨酯喷涂施工工艺", "中"),
        ("防水涂料施工面积", "低"),
    ]
    for q, p in gaps:
        conn.execute(
            "INSERT INTO knowledge_gaps (question, priority, frequency) VALUES (?, ?, ?)",
            (q, p, 12 - gaps.index((q, p)) * 2),
        )
    conn.commit()
    conn.close()


# ── 会话接口 ──

@app.route("/api/conversations", methods=["GET"])
def api_conversations():
    repo = get_repository()
    return jsonify(repo.list_conversations())


@app.route("/api/conversations/<conv_id>", methods=["GET"])
def api_conversation_detail(conv_id):
    repo = get_repository()
    conv = repo.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify(conv)


@app.route("/api/conversations/<conv_id>/status", methods=["PATCH"])
def api_conversation_status(conv_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in {"active", "ai_replied", "needs_human", "resolved", "进行中", "已回复", "已转人工", "已解决"}:
        return jsonify({"error": "无效会话状态"}), 400
    repo = get_repository()
    repo.update_conversation_status(conv_id, status)
    reason = (data.get("reason") or "").strip()
    operator = data.get("operator", "SmartQA Admin")
    status_message_id = None
    if status == "needs_human" and reason:
        status_message_id = repo.add_message(
            conv_id,
            "system",
            f"转人工原因：{reason}",
            direction="outbound",
            channel=data.get("channel", "internal"),
            raw_payload={
                "source": "internal_workbench_handoff",
                "operator": operator,
                "status": status,
                "reason": reason,
            },
            delivery_status="stored",
        )
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="conversation.status_updated",
            target_type="conversation",
            target_id=conv_id,
            metadata={
                "status": status,
                "reason": reason,
                "operator": operator,
                "message_id": status_message_id,
            },
        )
    return jsonify({"ok": True})


@app.route("/api/conversations/<conv_id>/operations", methods=["PATCH"])
def api_conversation_operations(conv_id):
    data = request.get_json(force=True)
    lead_status = data.get("lead_status")
    quotation_status = data.get("quotation_status")
    conversion_stage = data.get("conversion_stage")
    if lead_status and lead_status not in {"new", "qualified", "quoted", "won", "lost", "nurture"}:
        return jsonify({"error": "invalid_lead_status"}), 400
    if quotation_status and quotation_status not in {"none", "needed", "sent", "accepted", "rejected"}:
        return jsonify({"error": "invalid_quotation_status"}), 400
    if conversion_stage and conversion_stage not in {"inquiry", "needs_confirmed", "quoted", "won", "lost"}:
        return jsonify({"error": "invalid_conversion_stage"}), 400
    if "quotation_amount" in data and data.get("quotation_amount") not in {None, ""}:
        try:
            data["quotation_amount"] = float(data["quotation_amount"])
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_quotation_amount"}), 400
    repo = get_repository()
    if not hasattr(repo, "update_conversation_operations"):
        return jsonify({"error": "operations_loop_not_supported"}), 501
    conversation = repo.update_conversation_operations(conv_id, data)
    if not conversation:
        return jsonify({"error": "conversation_not_found"}), 404
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="conversation.operations_updated",
            target_type="conversation",
            target_id=conv_id,
            metadata={
                "lead_status": data.get("lead_status"),
                "next_follow_up_at": data.get("next_follow_up_at"),
                "quotation_status": data.get("quotation_status"),
                "quotation_amount": data.get("quotation_amount"),
                "conversion_stage": data.get("conversion_stage"),
            },
        )
    return jsonify(conversation)


@app.route("/api/conversations/<conv_id>/human-reply", methods=["POST"])
def api_conversation_human_reply(conv_id):
    data = request.get_json(force=True)
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "人工回复不能为空"}), 400

    repo = get_repository()
    conv = repo.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "会话不存在"}), 404

    message_id = repo.add_message(
        conv_id,
        "human",
        content,
        direction="outbound",
        channel=conv.get("channel", "internal"),
        raw_payload={"source": "internal_workbench", "operator": data.get("operator", "SmartQA Admin")},
        delivery_status="stored",
    )
    delivery_status = "stored"
    delivery_error = None
    delivery_target = None

    if conv.get("channel") == "wecom" and wecom_client.enabled():
        contact = repo.get_wecom_contact_for_conversation(conv_id) if hasattr(repo, "get_wecom_contact_for_conversation") else None
        external_user_id = (contact or {}).get("external_user_id")
        if external_user_id:
            delivery_target = external_user_id
            try:
                wecom_client.send_text(external_user_id, content)
                delivery_status = "sent"
            except Exception as exc:
                delivery_status = "failed"
                delivery_error = str(exc)
            if hasattr(repo, "update_message_delivery_status"):
                repo.update_message_delivery_status(message_id, delivery_status, delivery_error)
    elif conv.get("channel") == "wecom_kf" and wecom_client.customer_service_enabled():
        contact = repo.get_wecom_contact_for_conversation(conv_id) if hasattr(repo, "get_wecom_contact_for_conversation") else None
        external_userid = (contact or {}).get("external_user_id")
        open_kfid = _contact_open_kfid(contact) or _conversation_open_kfid(conv) or WECOM_KF_OPEN_KFID
        if external_userid and open_kfid:
            delivery_target = external_userid
            try:
                wecom_client.send_customer_service_text(
                    open_kfid=open_kfid,
                    external_userid=external_userid,
                    content=content,
                )
                delivery_status = "sent"
            except Exception as exc:
                delivery_status = "failed"
                delivery_error = str(exc)
            if hasattr(repo, "update_message_delivery_status"):
                repo.update_message_delivery_status(message_id, delivery_status, delivery_error)

    repo.update_conversation_status(conv_id, "resolved" if data.get("resolve", True) else "ai_replied")
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="conversation.human_replied",
            target_type="conversation",
            target_id=conv_id,
            metadata={
                "message_id": message_id,
                "channel": conv.get("channel", "internal"),
                "delivery_target_present": bool(delivery_target),
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
            },
        )

    return jsonify({
        "ok": True,
        "message_id": message_id,
        "channel": conv.get("channel", "internal"),
        "delivery_target_present": bool(delivery_target),
        "delivery_status": delivery_status,
        "delivery_error": delivery_error,
    })


# ── 聊天接口 ──

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    repo = get_repository()
    session_id = data.get("session_id") or f"internal-{uuid.uuid4().hex[:12]}"
    requested_channel = data.get("channel")
    source = data.get("source")
    channel = "web_customer" if requested_channel == "web_customer" or source == "customer" else "internal"
    existing = repo.find_conversation_by_external_id(session_id, channel=channel)
    if not existing:
        if channel == "web_customer":
            return jsonify({"error": "客户会话不存在，请先注册"}), 404
        existing = repo.create_conversation(
            session_id,
            customer_name=data.get("customer_name", "匿名客户"),
            customer_type=data.get("customer_type", "未知"),
            channel=channel,
        )
    if channel == "web_customer":
        token = data.get("access_token") or request.headers.get("X-Customer-Access-Token", "")
        _, token_error = verify_customer_token(
            token,
            session_id=session_id,
            conversation_id=str(existing["id"]),
            channel="web_customer",
        )
        if token_error:
            return jsonify({"error": "customer_unauthorized", "reason": token_error}), 401

    conv_id = existing["id"]
    customer_message_id = repo.add_message(
        conv_id,
        "customer",
        message,
        direction="inbound",
        channel=channel,
        raw_payload=data,
    )

    result = AIOrchestrationService(repo).handle_customer_message(
        conversation_id=conv_id,
        trigger_message_id=customer_message_id,
        message=message,
        channel=channel,
        dify_conversation_id=data.get("dify_conversation_id"),
        customer_profile={
            "name": existing.get("customer_name") or data.get("customer_name", "匿名客户"),
            "type": existing.get("customer_type") or data.get("customer_type", "未知"),
            "source": channel,
        },
    )

    return jsonify({
        "answer": result["answer"],
        "session_id": session_id,
        "conversation_id": conv_id,
        "access_token": data.get("access_token") if channel == "web_customer" else None,
        "dify_conversation_id": result.get("dify_conversation_id"),
        "message_id": result.get("assistant_message_id"),
        "ai_run_id": result.get("ai_run_id"),
        "qa": result.get("qa"),
        "decision": result.get("decision"),
        "knowledge_gap": result.get("knowledge_gap"),
    })


@app.route("/api/test-chat", methods=["POST"])
def api_test_chat():
    return api_chat()


@app.route("/api/customer/register", methods=["POST"])
def api_customer_register():
    data = request.get_json(force=True)
    company = (data.get("company") or "").strip()
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not company or not name:
        return jsonify({"error": "公司名称和联系人不能为空"}), 400

    repo = get_repository()
    session_id = data.get("session_id") or f"web-{uuid.uuid4().hex[:12]}"
    existing = repo.find_conversation_by_external_id(session_id, channel="web_customer")
    if not existing:
        existing = repo.create_conversation(
            session_id,
            customer_name=name,
            customer_type=company,
            channel="web_customer",
        )
        if hasattr(repo, "add_audit_log"):
            repo.add_audit_log(
                actor_type="system",
                action="customer.registered",
                target_type="conversation",
                target_id=str(existing.get("id")),
                metadata={"company": company, "name": name, "phone_present": bool(phone), "channel": "web_customer"},
            )
    access_token = issue_customer_token(
        session_id=session_id,
        conversation_id=str(existing["id"]),
        channel="web_customer",
    )
    return jsonify({
        "ok": True,
        "session_id": session_id,
        "conversation_id": existing["id"],
        "access_token": access_token,
        "company": company,
        "name": name,
    })


@app.route("/api/customer/history", methods=["GET"])
def api_customer_history():
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "session_id 不能为空"}), 400

    repo = get_repository()
    conv = repo.find_conversation_by_external_id(session_id, channel="web_customer")
    if not conv:
        return jsonify({"messages": []})
    token = request.args.get("access_token") or request.headers.get("X-Customer-Access-Token", "")
    _, token_error = verify_customer_token(
        token,
        session_id=session_id,
        conversation_id=str(conv["id"]),
        channel="web_customer",
    )
    if token_error:
        return jsonify({"error": "customer_unauthorized", "reason": token_error}), 401
    detail = repo.get_conversation(conv["id"])
    if not detail:
        return jsonify({"messages": []})
    public_messages = [
        {
            "role": "customer" if message.get("role") == "customer" else "assistant",
            "content": message.get("content", ""),
            "timestamp": message.get("timestamp") or message.get("created_at"),
        }
        for message in detail.get("messages", [])
        if message.get("role") in {"customer", "assistant", "human"}
    ]
    return jsonify({
        "conversation_id": conv["id"],
        "session_id": session_id,
        "messages": public_messages,
    })


# ── 看板接口 ──

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    repo = get_repository()
    return jsonify(repo.dashboard())


@app.route("/api/operations/monitor", methods=["GET"])
def api_operations_monitor():
    repo = get_repository()
    if not hasattr(repo, "operations_monitor"):
        return jsonify({"error": "当前数据层不支持运行监控"}), 501
    return jsonify(repo.operations_monitor())


@app.route("/api/operations/send-alerts", methods=["POST"])
def api_operations_send_alerts():
    repo = get_repository()
    if not hasattr(repo, "operations_monitor"):
        return jsonify({"error": "当前数据层不支持运行监控"}), 501
    result = OperationsAlertService(repo).send_monitor_alerts(force=True)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/operations/resolve-current", methods=["POST"])
def api_operations_resolve_current():
    repo = get_repository()
    if not hasattr(repo, "resolve_current_operation_failures"):
        return jsonify({"error": "当前数据层不支持异常归档"}), 501
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip()
    return jsonify(repo.resolve_current_operation_failures(note=note, resolved_by="admin"))


@app.route("/api/audit-logs", methods=["GET"])
def api_audit_logs():
    repo = get_repository()
    if not hasattr(repo, "list_audit_logs"):
        return jsonify([])
    limit = request.args.get("limit", "100")
    try:
        limit_int = int(limit)
    except ValueError:
        limit_int = 100
    rows = repo.list_audit_logs(
        limit=limit_int,
        target_type=request.args.get("target_type") or None,
        action=request.args.get("action") or None,
    )
    return jsonify(mask_json(rows))


@app.route("/api/data-governance", methods=["GET"])
def api_data_governance():
    repo = get_repository()
    policies = repo.list_data_governance_policies() if hasattr(repo, "list_data_governance_policies") else []
    return jsonify({
        "policies": policies,
        "summary": {
            "policy_count": len(policies),
            "masking_enabled": any(p.get("policy_type") == "masking" and p.get("enabled") for p in policies),
            "retention_policies": len([p for p in policies if p.get("policy_type") == "retention"]),
            "audit_masking_applied": True,
        },
    })


# ── 知识盲区接口 ──

@app.route("/api/knowledge-gaps", methods=["GET"])
def api_knowledge_gaps():
    repo = get_repository()
    return jsonify(repo.list_knowledge_gaps())


@app.route("/api/knowledge-gaps/<gap_id>", methods=["PATCH"])
def api_knowledge_gap_update(gap_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status and status not in {"open", "drafted", "added_to_kb", "ignored"}:
        return jsonify({"error": "无效知识盲区状态"}), 400

    updates = {}
    for key in ["status", "priority", "category", "suggested_answer"]:
        if key in data:
            updates[key] = data[key]
    if status in {"added_to_kb", "ignored"}:
        updates["resolved_at"] = datetime.now(timezone.utc).isoformat()

    repo = get_repository()
    if not hasattr(repo, "update_knowledge_gap"):
        return jsonify({"error": "当前数据层不支持知识盲区更新"}), 501
    gap = repo.update_knowledge_gap(gap_id, updates)
    if not gap:
        return jsonify({"error": "知识盲区不存在"}), 404
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="knowledge_gap.updated",
            target_type="knowledge_gap",
            target_id=gap_id,
            metadata=updates,
        )
    return jsonify(gap)


@app.route("/api/knowledge-gaps/<gap_id>/promote", methods=["POST"])
def api_knowledge_gap_promote(gap_id):
    data = request.get_json(force=True)
    repo = get_repository()
    if not hasattr(repo, "create_knowledge_item"):
        return jsonify({"error": "当前数据层不支持知识条目创建"}), 501
    try:
        result = KnowledgeOpsService(repo).promote_gap_to_item(gap_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"知识盲区沉淀失败: {exc}"}), 500

    item = _knowledge_item_for_frontend(result["knowledge_item"])
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="knowledge_gap.promoted",
            target_type="knowledge_gap",
            target_id=gap_id,
            metadata={
                "knowledge_item_id": str(item.get("id")),
                "sync_status": item.get("sync_status"),
            },
        )
    return jsonify({"gap": result["gap"], "knowledge_item": item})


# ── 知识库接口 ──

@app.route("/api/knowledge", methods=["GET"])
def api_knowledge_list():
    category = request.args.get("category")
    keyword = request.args.get("keyword")
    item_type = request.args.get("item_type")
    repo = get_repository()
    if hasattr(repo, "list_knowledge_items"):
        items = KnowledgeOpsService(repo).list_items(item_type=item_type, category=category)
        if keyword:
            kw = keyword.lower()
            items = [
                item for item in items
                if kw in (item.get("title") or "").lower()
                or kw in (item.get("brand") or "").lower()
                or kw in (item.get("spec") or "").lower()
                or kw in (item.get("core_params") or "").lower()
            ]
        return jsonify([_knowledge_item_for_frontend(item) for item in items])
    return jsonify(knowledge_base.list(category=category, keyword=keyword))


@app.route("/api/knowledge", methods=["POST"])
def api_knowledge_add():
    data = request.get_json(force=True)
    repo = get_repository()
    if hasattr(repo, "create_knowledge_item"):
        try:
            item = KnowledgeOpsService(repo).create_item(data, publish=data.get("publish", True), sync=data.get("sync", True))
        except Exception as exc:
            return jsonify({"error": f"知识保存失败: {exc}"}), 500
        if hasattr(repo, "add_audit_log"):
            repo.add_audit_log(
                actor_type="admin",
                action="knowledge_item.created",
                target_type="knowledge_item",
                target_id=str(item.get("id")),
                metadata={"sync_status": item.get("sync_status"), "item_type": item.get("item_type")},
            )
        return jsonify(_knowledge_item_for_frontend(item)), 201
    item = knowledge_base.add(data)
    return jsonify(item), 201


@app.route("/api/knowledge/<item_id>", methods=["PATCH"])
def api_knowledge_update(item_id):
    data = request.get_json(force=True)
    repo = get_repository()
    if not hasattr(repo, "update_knowledge_item"):
        return jsonify({"error": "当前数据层不支持知识条目更新"}), 501
    try:
        item = KnowledgeOpsService(repo).update_item(item_id, data, sync=data.get("sync", True))
    except Exception as exc:
        return jsonify({"error": f"知识更新失败: {exc}"}), 500
    if not item:
        return jsonify({"error": "知识条目不存在"}), 404
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="knowledge_item.updated",
            target_type="knowledge_item",
            target_id=str(item.get("id")),
            metadata={"sync_status": item.get("sync_status"), "item_type": item.get("item_type")},
        )
    return jsonify(_knowledge_item_for_frontend(item))


@app.route("/api/knowledge/<item_id>/sync", methods=["POST"])
def api_knowledge_sync(item_id):
    repo = get_repository()
    if not hasattr(repo, "create_sync_job"):
        return jsonify({"error": "当前数据层不支持知识同步"}), 501
    try:
        item = KnowledgeOpsService(repo).sync_item(item_id)
    except Exception as exc:
        return jsonify({"error": f"知识同步失败: {exc}"}), 500
    return jsonify(_knowledge_item_for_frontend(item))


@app.route("/api/knowledge/sync-failed", methods=["POST"])
def api_knowledge_sync_failed():
    repo = get_repository()
    if not hasattr(repo, "list_knowledge_items"):
        return jsonify({"error": "当前数据层不支持知识同步"}), 501
    items = [
        item for item in KnowledgeOpsService(repo).list_items()
        if item.get("sync_status") == "failed"
    ]
    results = []
    service = KnowledgeOpsService(repo)
    for item in items[:20]:
        try:
            synced = service.sync_item(item["id"])
            results.append({
                "id": synced.get("id"),
                "title": synced.get("title"),
                "sync_status": synced.get("sync_status"),
                "last_sync_error": synced.get("last_sync_error"),
            })
        except Exception as exc:
            results.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "sync_status": "failed",
                "last_sync_error": str(exc),
            })
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="knowledge_sync.retry_failed",
            target_type="knowledge_item",
            metadata={"attempted": len(results)},
        )
    return jsonify({"attempted": len(results), "results": results})


@app.route("/api/knowledge/sync-pending", methods=["POST"])
def api_knowledge_sync_pending():
    repo = get_repository()
    if not hasattr(repo, "list_knowledge_items"):
        return jsonify({"error": "褰撳墠鏁版嵁灞備笉鏀寔鐭ヨ瘑鍚屾"}), 501
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit", 20) or 20)
    items = [
        item for item in KnowledgeOpsService(repo).list_items()
        if item.get("publish_status") == "published" and item.get("sync_status") in {"pending", "syncing"}
    ]
    results = []
    service = KnowledgeOpsService(repo)
    for item in items[:max(1, min(limit, 50))]:
        try:
            synced = service.sync_item(item["id"])
            results.append({
                "id": synced.get("id"),
                "title": synced.get("title"),
                "sync_status": synced.get("sync_status"),
                "last_sync_error": synced.get("last_sync_error"),
            })
        except Exception as exc:
            results.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "sync_status": "failed",
                "last_sync_error": str(exc),
            })
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="knowledge_sync.sync_pending",
            target_type="knowledge_item",
            metadata={"attempted": len(results), "available": len(items)},
        )
    return jsonify({"available": len(items), "attempted": len(results), "results": results})


@app.route("/api/knowledge-sync-jobs", methods=["GET"])
def api_knowledge_sync_jobs():
    repo = get_repository()
    if not hasattr(repo, "list_sync_jobs"):
        return jsonify([])
    return jsonify(repo.list_sync_jobs(request.args.get("item_id")))


@app.route("/api/knowledge/<item_id>/versions", methods=["GET"])
def api_knowledge_versions(item_id):
    repo = get_repository()
    if not hasattr(repo, "list_knowledge_item_versions"):
        return jsonify([])
    return jsonify(repo.list_knowledge_item_versions(item_id))


@app.route("/api/knowledge-quality", methods=["GET"])
def api_knowledge_quality():
    repo = get_repository()
    return jsonify(KnowledgeQualityService(repo).report())


def _knowledge_item_for_frontend(item: dict) -> dict:
    status_map = {"active": "在售", "out_of_stock": "缺货", "inactive": "下架"}
    return {
        **item,
        "product": item.get("title", ""),
        "price": item.get("list_price"),
        "wholesale_price": item.get("wholesale_price"),
        "params": item.get("core_params", ""),
        "usage": item.get("usage_scenarios", ""),
        "status": status_map.get(item.get("lifecycle_status"), item.get("lifecycle_status", "active")),
        "status_code": item.get("lifecycle_status"),
    }


@app.route("/api/system/health", methods=["GET"])
def api_system_health():
    repo = get_repository()
    supabase_health = supabase.health()
    wecom_health = wecom_client.health() if WECOM_ENABLED else {"enabled": False, "ok": False, "reason": "WeCom is not configured"}
    return jsonify({
        "ok": True,
        "data_backend": repo.backend_name,
        "supabase": supabase_health,
        "wecom": wecom_health,
        "supabase_public": {
            "url": SUPABASE_URL,
            "anon_key": SUPABASE_ANON_KEY,
        },
        "config": {
            "supabase_enabled": SUPABASE_ENABLED,
            "dify_enabled": DIFY_ENABLED,
            "dify_app_mode": DIFY_APP_MODE,
            "dify_effective_app_mode": effective_app_mode(),
            "mock_ai_enabled": MOCK_AI_ENABLED,
            "wecom_enabled": WECOM_ENABLED,
            "wecom_kf_enabled": WECOM_KF_ENABLED,
            "wecom_kf_poll_enabled": WECOM_KF_POLL_ENABLED,
            "internal_auth_required": api_auth_required("/api/conversations"),
        },
        "knowledge_items": len(knowledge_base.items),
    })


@app.route("/api/dify/workflow-version", methods=["GET"])
def api_dify_workflow_version():
    path = Path(__file__).resolve().parents[1] / "dify-workflow" / "workflow-version.json"
    if not path.exists():
        return jsonify({"error": "workflow version file not found"}), 404
    return jsonify(json.loads(path.read_text(encoding="utf-8")))


@app.route("/api/auth/session", methods=["GET"])
def api_auth_session():
    required = api_auth_required("/api/conversations")
    if not required:
        return jsonify({"required": False, "user": None})
    user, error = verify_request(request)
    if error:
        return jsonify({"required": True, "authenticated": False, "reason": error}), 401
    return jsonify({"required": True, "authenticated": True, "user": user})


@app.route("/wecom/callback", methods=["GET"])
def wecom_callback_verify():
    body, status = verify_wecom_url(request.args)
    return body, status


@app.route("/wecom/callback", methods=["POST"])
def wecom_callback_receive():
    repo = get_repository()
    body, status = handle_wecom_callback(request.args, request.get_data(as_text=True), repo)
    return body, status


@app.route("/wecom/kf/callback", methods=["GET"])
def wecom_kf_callback_verify():
    body, status = verify_wecom_kf_url(request.args)
    return body, status


@app.route("/wecom/kf/callback", methods=["POST"])
def wecom_kf_callback_receive():
    repo = get_repository()
    body, status = handle_wecom_kf_callback(request.args, request.get_data(as_text=True), repo)
    return body, status


@app.route("/api/wecom-kf/sync", methods=["POST"])
def api_wecom_kf_sync():
    if not WECOM_KF_ENABLED:
        return jsonify({"error": "wecom_kf_not_configured"}), 400
    data = request.get_json(silent=True) or {}
    cursor = (data.get("cursor") or "").strip()
    token = (data.get("token") or "").strip()
    repo = get_repository()
    before_count = len(repo.list_conversations())
    try:
        result = sync_customer_service_messages(repo, token=token, cursor=cursor)
    except Exception as exc:
        if hasattr(repo, "add_audit_log"):
            repo.add_audit_log(
                actor_type="admin",
                action="wecom_kf.manual_sync_failed",
                target_type="conversation",
                target_id=None,
                metadata={"cursor_present": bool(cursor), "token_present": bool(token), "error": str(exc)},
            )
        return jsonify({"error": "wecom_kf_sync_failed", "detail": str(exc)}), 502

    after_conversations = repo.list_conversations()
    new_count = max(0, len(after_conversations) - before_count)
    recent_wecom_kf = [
        {
            "id": conversation.get("id"),
            "session_id": conversation.get("session_id"),
            "customer_name": conversation.get("customer_name"),
            "status": conversation.get("status"),
            "updated_at": conversation.get("updated_at"),
        }
        for conversation in after_conversations
        if conversation.get("channel") == "wecom_kf"
    ][:10]
    response = {
        "ok": True,
        "msg_count": len(result.get("msg_list", [])),
        "has_more": bool(result.get("has_more")),
        "next_cursor": result.get("next_cursor") or "",
        "persisted_cursor": (repo.get_wecom_runtime_state("kf_sync_cursor") or {}).get("state_value") if hasattr(repo, "get_wecom_runtime_state") else "",
        "new_conversation_count": new_count,
        "recent_wecom_kf_conversations": recent_wecom_kf,
    }
    if hasattr(repo, "add_audit_log"):
        repo.add_audit_log(
            actor_type="admin",
            action="wecom_kf.manual_sync",
            target_type="conversation",
            target_id=None,
            metadata=response,
        )
    return jsonify(response)


@app.route("/api/messages/<message_id>/delivery/retry", methods=["POST"])
def api_retry_message_delivery(message_id):
    repo = get_repository()
    result = MessageDeliveryService(repo).retry_failed_delivery(message_id)
    return jsonify(result), 200 if result.get("ok") else 400


@app.route("/api/messages/delivery/retry-failed", methods=["POST"])
def api_retry_failed_message_deliveries():
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit") or 10)
    repo = get_repository()
    result = MessageDeliveryService(repo).retry_failed_deliveries(limit=limit)
    return jsonify(result), 200 if result.get("ok") else 400


@app.route("/api/wecom/status", methods=["GET"])
def api_wecom_status():
    local_callback_url = request.host_url.rstrip("/") + "/wecom/callback"
    public_callback_url = f"{WECOM_PUBLIC_BASE_URL}/wecom/callback" if WECOM_PUBLIC_BASE_URL else ""
    local_kf_callback_url = request.host_url.rstrip("/") + "/wecom/kf/callback"
    public_kf_callback_url = f"{WECOM_PUBLIC_BASE_URL}/wecom/kf/callback" if WECOM_PUBLIC_BASE_URL else ""
    callback_url = public_callback_url or local_callback_url
    kf_callback_url = public_kf_callback_url or local_kf_callback_url
    missing = [
        name
        for name, value in {
            "WECOM_CORP_ID": WECOM_CORP_ID,
            "WECOM_AGENT_ID": WECOM_AGENT_ID,
            "WECOM_SECRET": WECOM_SECRET,
            "WECOM_TOKEN": WECOM_TOKEN,
            "WECOM_ENCODING_AES_KEY": WECOM_ENCODING_AES_KEY,
        }.items()
        if not value
    ]
    return jsonify({
        "enabled": WECOM_ENABLED,
        "customer_service_enabled": WECOM_KF_ENABLED,
        "callback_url": callback_url,
        "customer_service_callback_url": kf_callback_url,
        "local_callback_url": local_callback_url,
        "local_customer_service_callback_url": local_kf_callback_url,
        "public_callback_url": public_callback_url,
        "public_customer_service_callback_url": public_kf_callback_url,
        "public_base_configured": bool(WECOM_PUBLIC_BASE_URL),
        "encryption_enabled": bool(WECOM_ENCODING_AES_KEY),
        "missing_env": missing,
        "configured": {
            "corp_id": _mask_config(WECOM_CORP_ID),
            "agent_id": WECOM_AGENT_ID or "",
            "secret": _mask_config(WECOM_SECRET),
            "kf_secret": _mask_config(WECOM_KF_SECRET),
            "kf_open_kfid": _mask_config(WECOM_KF_OPEN_KFID),
            "token": _mask_config(WECOM_TOKEN),
            "encoding_aes_key": _mask_config(WECOM_ENCODING_AES_KEY),
        },
        "health": wecom_client.health() if WECOM_ENABLED else {"enabled": False, "ok": False, "reason": "WeCom is not configured"},
        "readiness": {
            "env_configured": len(missing) == 0,
            "public_https_configured": public_callback_url.startswith("https://"),
            "encryption_configured": bool(WECOM_ENCODING_AES_KEY),
            "send_api_configured": bool(WECOM_CORP_ID and WECOM_AGENT_ID and WECOM_SECRET),
            "callback_path": "/wecom/callback",
            "customer_service_callback_path": "/wecom/kf/callback",
            "text_message_supported": True,
            "active_send_supported": True,
            "customer_service_supported": WECOM_KF_ENABLED,
            "customer_service_poll_enabled": WECOM_KF_POLL_ENABLED,
        },
        "setup": {
            "url": callback_url,
            "local_url": local_callback_url,
            "public_url": public_callback_url,
            "customer_service_url": kf_callback_url,
            "token_env": "WECOM_TOKEN",
            "encoding_aes_key_env": "WECOM_ENCODING_AES_KEY",
        },
    })


@app.route("/api/wecom/simulate", methods=["POST"])
def api_wecom_simulate():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "100mm岩棉板多少钱？").strip()
    from_user = (data.get("from_user") or f"local-demo-{uuid.uuid4().hex[:8]}").strip()
    msg_id = data.get("msg_id") or f"local-wecom-{uuid.uuid4().hex}"
    xml = f"""<xml>
  <ToUserName><![CDATA[smartqa-local]]></ToUserName>
  <FromUserName><![CDATA[{_xml_cdata_safe(from_user)}]]></FromUserName>
  <CreateTime>{int(datetime.now(timezone.utc).timestamp())}</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[{_xml_cdata_safe(content)}]]></Content>
  <MsgId>{_xml_cdata_safe(msg_id)}</MsgId>
  <AgentID>{WECOM_AGENT_ID or "1"}</AgentID>
</xml>"""
    repo = get_repository()
    body, status = handle_wecom_callback({}, xml, repo)
    conversation = repo.find_conversation_by_external_id(f"wecom-{from_user}", channel="wecom")
    return jsonify({
        "ok": status == 200,
        "callback_status": status,
        "callback_body": body,
        "from_user": from_user,
        "msg_id": msg_id,
        "conversation": conversation,
    }), status


@app.route("/api/wecom-kf/simulate", methods=["POST"])
def api_wecom_kf_simulate():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "100mm岩棉板多少钱？").strip()
    external_userid = (data.get("external_userid") or f"local-kf-{uuid.uuid4().hex[:8]}").strip()
    open_kfid = (data.get("open_kfid") or WECOM_KF_OPEN_KFID or "local-open-kfid").strip()
    msgid = data.get("msgid") or f"local-wecom-kf-{uuid.uuid4().hex}"
    repo = get_repository()
    result = handle_wecom_kf_simulated_text(
        repo,
        open_kfid=open_kfid,
        external_userid=external_userid,
        content=content,
        msgid=msgid,
    )
    conversation = repo.find_conversation_by_external_id(f"wecom-kf-{open_kfid}-{external_userid}", channel="wecom_kf")
    return jsonify({
        "ok": bool(result.get("ok")),
        "external_userid": external_userid,
        "open_kfid": open_kfid,
        "msgid": msgid,
        "conversation": conversation,
        "result": result,
    }), 200 if result.get("ok") else 400


def _mask_config(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]


def _xml_cdata_safe(value: str) -> str:
    return str(value).replace("]]>", "]]]]><![CDATA[>")


def _conversation_open_kfid(conv: dict) -> str:
    external_id = conv.get("external_conversation_id") or ""
    if external_id.startswith("wecom-kf-"):
        return external_id.removeprefix("wecom-kf-").rsplit("-", 1)[0]
    return ""


def _contact_open_kfid(contact: dict | None) -> str:
    if not contact:
        return ""
    raw_profile = contact.get("raw_profile") or {}
    if isinstance(raw_profile, dict):
        return raw_profile.get("open_kfid") or ""
    return ""


# ── 前端静态文件 ──

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
)


@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def serve_frontend(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# ── 启动 ──

def init_app():
    init_db()
    knowledge_base.load_from_csv()
    if get_repository().backend_name == "sqlite":
        _seed_demo_data()
    start_wecom_kf_poller()
    start_message_delivery_retry_scheduler()
    return app


if __name__ == "__main__":
    init_app()
    print(f"SmartQA 后端启动中...")
    print(f"知识库已加载 {len(knowledge_base.items)} 条产品数据")
    print(f"API 地址: http://localhost:{FLASK_PORT}")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT, use_reloader=False)
