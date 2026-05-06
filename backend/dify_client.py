from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import requests

from config import DIFY_API_KEY, DIFY_API_URL, DIFY_USER, DIFY_APP_MODE, MOCK_AI_ENABLED


_MOCK_RESPONSES = [
    "您好！关于您咨询的产品，我们有以下推荐：\n\n1. **挤塑板 (XPS)** - 导热系数≤0.030，容重30-45kg/m³，适用于外墙保温和地暖隔热。\n2. **岩棉板** - A级防火，导热系数≤0.040，适合高层建筑外墙防火隔离带。\n\n如果是高层项目，建议优先使用岩棉板以满足消防要求。请问您的项目在哪个城市？",
    "收到您的需求！100mm岩棉板（容重120kg/m³）可按批量报价核算，5000平以上通常可以申请阶梯优惠。检测报告、导热系数和A级防火证明可以随货提供。运费需要根据项目城市核算，您方便告诉我项目位置吗？",
    "关于岩棉板和挤塑板的选择：岩棉板防火等级更高，适合高层外墙；挤塑板导热系数更低、价格更友好，适合多层或地暖隔热。若项目对消防要求严格，建议优先岩棉板。",
    "非常抱歉给您带来不便。您提到的是已发生的破损问题，我建议转人工同事马上跟进。请您保留破损照片、订单号和到货时间，我们会优先核实处理。",
    "施工方面建议控制基层平整、干燥、无浮灰；抹面砂浆通常分两遍施工，并配合网格布增强。不同产品配比和开放时间会有差异，建议以产品说明和现场温湿度为准。",
]

_RESOLVED_APP_MODE = DIFY_APP_MODE


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }


def effective_app_mode() -> str:
    return _resolved_app_mode()


def run_workflow(
    *,
    message: str,
    conversation_id: str,
    conversation_history: list[dict[str, str]] | None = None,
    customer_profile: dict[str, Any] | None = None,
    knowledge_context: str = "",
    knowledge_sources: list[dict[str, Any]] | None = None,
    dify_conversation_id: str | None = None,
    channel: str = "internal",
) -> dict[str, Any]:
    started = time.monotonic()
    if MOCK_AI_ENABLED or not DIFY_API_KEY:
        result = _mock_workflow(message, conversation_id, conversation_history or [], customer_profile or {}, channel)
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        return result

    inputs = {
        "channel": channel,
        "conversation_id": conversation_id,
        "customer_message": message,
        "conversation_history": json.dumps(conversation_history or [], ensure_ascii=False),
        "customer_profile": json.dumps(customer_profile or {}, ensure_ascii=False),
        "knowledge_context": knowledge_context or "",
        "knowledge_sources": json.dumps(knowledge_sources or [], ensure_ascii=False),
        "knowledge_hit": "true" if knowledge_sources else "false",
    }
    app_mode = _resolved_app_mode()
    if app_mode == "workflow":
        data = _run_workflow_endpoint(inputs)
        parsed = _parse_workflow_response(data)
    else:
        data, parsed = _run_chat_endpoint(inputs, message, dify_conversation_id, allow_workflow_fallback=app_mode == "auto")
    if knowledge_sources:
        _merge_knowledge_sources(parsed, knowledge_sources)
    parsed["dify_conversation_id"] = data.get("conversation_id") or data.get("workflow_run_id")
    parsed["dify_message_id"] = data.get("message_id") or data.get("task_id") or data.get("workflow_run_id")
    parsed["raw_dify_response"] = data
    parsed["latency_ms"] = int((time.monotonic() - started) * 1000)
    return _ensure_contract(parsed, message)


def _run_chat_endpoint(
    inputs: dict[str, Any],
    message: str,
    dify_conversation_id: str | None,
    *,
    allow_workflow_fallback: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "inputs": inputs,
        "query": message,
        "user": DIFY_USER,
        "response_mode": "blocking",
    }
    if dify_conversation_id:
        payload["conversation_id"] = dify_conversation_id
    try:
        response = requests.post(
            f"{DIFY_API_URL}/chat-messages",
            headers=_headers(),
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        parsed = _parse_structured_answer(data.get("answer", ""))
    except requests.HTTPError as exc:
        chat_error = exc
        if not allow_workflow_fallback or not _should_retry_as_workflow(exc.response):
            raise
        try:
            data = _run_workflow_endpoint(inputs)
            _remember_workflow_mode(chat_error)
        except requests.HTTPError as workflow_exc:
            raise RuntimeError(
                f"Dify chat endpoint failed: {_format_http_error(chat_error)}; "
                f"workflow endpoint failed: {_format_http_error(workflow_exc)}"
            ) from workflow_exc
        parsed = _parse_workflow_response(data)
    return data, parsed


def _resolved_app_mode() -> str:
    return _RESOLVED_APP_MODE if _RESOLVED_APP_MODE in {"auto", "chat", "workflow"} else "auto"


def _remember_workflow_mode(chat_error: requests.HTTPError) -> None:
    global _RESOLVED_APP_MODE
    if DIFY_APP_MODE != "auto":
        return
    response = chat_error.response
    body = response.text if response is not None else ""
    if "not_chat_app" in body or "workflow" in body or "matches the right API route" in body:
        _RESOLVED_APP_MODE = "workflow"


def _run_workflow_endpoint(inputs: dict[str, Any]) -> dict[str, Any]:
    workflow_payload = {
        "inputs": inputs,
        "user": DIFY_USER,
        "response_mode": "blocking",
    }
    response = requests.post(
        f"{DIFY_API_URL}/workflows/run",
        headers=_headers(),
        json=workflow_payload,
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def _should_retry_as_workflow(response) -> bool:
    return response is not None and response.status_code in {400, 404, 405, 422}


def _format_http_error(exc: requests.HTTPError) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    body = (response.text or "").strip().replace("\n", " ")
    if len(body) > 500:
        body = body[:500] + "..."
    return f"{response.status_code} {response.reason}: {body or str(exc)}"


def _parse_workflow_response(data: dict[str, Any]) -> dict[str, Any]:
    outputs = data.get("data", {}).get("outputs") or data.get("outputs") or {}
    if not isinstance(outputs, dict):
        outputs = {}
    for key in ("structured_answer", "result", "answer_json", "json"):
        value = outputs.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            parsed = _parse_structured_answer(value)
            if parsed:
                return parsed
    answer = outputs.get("answer") or outputs.get("text") or outputs.get("response") or ""
    if isinstance(answer, dict):
        return answer
    parsed = _parse_structured_answer(str(answer))
    if parsed:
        return parsed
    return {"answer": str(answer)}


def _merge_knowledge_sources(parsed: dict[str, Any], knowledge_sources: list[dict[str, Any]]) -> None:
    if not knowledge_sources:
        return
    knowledge = parsed.setdefault("knowledge", {"hit": True, "sources": [], "gap_question": None})
    if not isinstance(knowledge, dict):
        knowledge = {"hit": True, "sources": [], "gap_question": None}
        parsed["knowledge"] = knowledge
    existing_sources = knowledge.get("sources") if isinstance(knowledge, dict) else []
    if not isinstance(existing_sources, list):
        existing_sources = []
    known_titles = {str(source.get("title") or "") for source in existing_sources if isinstance(source, dict)}
    merged_sources = existing_sources + [
        source for source in knowledge_sources
        if isinstance(source, dict) and str(source.get("title") or "") not in known_titles
    ]
    knowledge["hit"] = bool(merged_sources) or bool(knowledge.get("hit"))
    knowledge["sources"] = merged_sources[:8]
    knowledge.setdefault("gap_question", None)


def send_message(conversation_id, message, user="customer", stream=False):
    """Backward-compatible wrapper used by older routes."""
    result = run_workflow(message=message, conversation_id=conversation_id or "legacy", customer_profile={"name": user})
    return {
        "answer": result["answer"],
        "conversation_id": result.get("dify_conversation_id") or f"mock-{random.randint(1000, 9999)}",
        "message_id": result.get("dify_message_id") or f"mock-msg-{random.randint(10000, 99999)}",
    }


def _parse_structured_answer(answer: str) -> dict[str, Any]:
    answer = (answer or "").strip()
    if not answer:
        return {}
    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", answer, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    inline = re.search(r"(\{.*\})", answer, re.S)
    if inline:
        try:
            return json.loads(inline.group(1))
        except json.JSONDecodeError:
            pass

    return {"answer": answer}


def _mock_workflow(
    message: str,
    conversation_id: str,
    conversation_history: list[dict[str, str]],
    customer_profile: dict[str, Any],
    channel: str,
) -> dict[str, Any]:
    msg_lower = message.lower()
    is_complaint = any(k in msg_lower for k in ["投诉", "破损", "不管", "赔", "退款", "坏了", "漏水"])
    is_price = any(k in msg_lower for k in ["报价", "价格", "多少钱", "费用", "一平"])
    is_compare = any(k in msg_lower for k in ["对比", "区别", "哪个好", "选哪个"])
    is_after_sales = any(k in msg_lower for k in ["退换", "退货", "换货", "售后"])
    is_construction = any(k in msg_lower for k in ["施工", "配比", "工艺", "怎么用"])

    if is_complaint:
        answer = _MOCK_RESPONSES[3]
        action = "handoff"
        risk_level = "high"
        sentiment = "负面"
        question_type = "投诉"
        qa = _qa(4, 3, 4, 5, 4, risk_level, "投诉场景已安抚并建议转人工。")
    elif is_price:
        answer = _MOCK_RESPONSES[1]
        action = "send"
        risk_level = "low"
        sentiment = "中性"
        question_type = "售前咨询"
        qa = _qa(4, 4, 4, 3, 4, risk_level, "报价回复未编造具体未确认价格，要求补充城市核算运费。")
    elif is_compare:
        answer = _MOCK_RESPONSES[2]
        action = "send"
        risk_level = "low"
        sentiment = "中性"
        question_type = "技术问题"
        qa = _qa(4, 4, 5, 3, 5, risk_level, "产品对比清晰，给出选型建议。")
    elif is_after_sales:
        answer = _MOCK_RESPONSES[3]
        action = "send"
        risk_level = "medium"
        sentiment = "中性"
        question_type = "售后支持"
        qa = _qa(4, 4, 4, 4, 4, risk_level, "售后问题先安抚并收集信息。")
    elif is_construction:
        answer = _MOCK_RESPONSES[4]
        action = "send"
        risk_level = "low"
        sentiment = "中性"
        question_type = "技术问题"
        qa = _qa(4, 3, 4, 3, 4, risk_level, "施工建议较稳妥，但需结合产品说明。")
    else:
        answer = _MOCK_RESPONSES[0]
        action = "send"
        risk_level = "low"
        sentiment = "中性"
        question_type = "售前咨询"
        qa = _qa(4, 4, 4, 3, 4, risk_level, "常规咨询回复通过。")

    gap = None
    if any(k in msg_lower for k in ["特殊", "定制", "没有", "未知"]):
        gap = {
            "question": message,
            "category": question_type,
            "priority": "medium",
            "suggested_answer": "补充该问题对应的产品政策、适用范围和人工兜底话术。",
        }

    return _ensure_contract(
        {
            "intent": {
                "question_type": question_type,
                "customer_type": customer_profile.get("type", "未知"),
                "urgency": "高" if is_complaint else "中",
                "sentiment": sentiment,
                "entities": _extract_entities(message),
            },
            "knowledge": {
                "hit": gap is None,
                "sources": [{"title": "Mock 建材知识库", "content": "本地 Mock 知识片段。"}] if gap is None else [],
                "gap_question": gap["question"] if gap else None,
            },
            "answer": answer,
            "qa": qa,
            "decision": {
                "action": action,
                "reason": "投诉或高风险场景转人工。" if action == "handoff" else "质检通过，允许自动回复。",
                "needs_human": action == "handoff",
            },
            "knowledge_gap": gap,
            "dify_conversation_id": f"mock-{random.randint(1000, 9999)}",
            "dify_message_id": f"mock-msg-{random.randint(10000, 99999)}",
            "raw_dify_response": {"mock": True, "conversation_id": conversation_id, "channel": channel},
        },
        message,
    )


def _qa(accuracy, completeness, professionalism, empathy, efficiency, risk_level, reason):
    overall = round((accuracy + completeness + professionalism + empathy + efficiency) / 5, 2)
    return {
        "accuracy": accuracy,
        "completeness": completeness,
        "professionalism": professionalism,
        "empathy": empathy,
        "efficiency": efficiency,
        "overall_score": overall,
        "passed": all(v >= 3 for v in [accuracy, completeness, professionalism, empathy, efficiency]),
        "risk_level": risk_level,
        "reason": reason,
        "evidence": [],
    }


def _extract_entities(message: str) -> list[str]:
    entities = []
    for word in ["岩棉板", "挤塑板", "XPS", "EPS", "聚氨酯", "防水涂料", "砂浆"]:
        if word.lower() in message.lower():
            entities.append(word)
    return entities


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _requires_conservative_gap(message: str, answer: str, knowledge: dict[str, Any], qa: dict[str, Any], action: str) -> bool:
    """Deterministic business guardrail for topics that should not rely only on LLM judgment."""
    high_stakes = _contains_any(
        message,
        ["价格", "报价", "多少钱", "费用", "政策", "承诺", "质保", "赔偿", "退款", "退货", "库存", "运费", "发票"],
    )
    uncertain_scope = _contains_any(message, ["特殊", "定制", "非标", "没有", "未知", "能不能", "可不可以"])
    answer_is_uncertain = _contains_any(
        answer,
        ["无法确认", "不能确认", "不确定", "需要人工", "人工核实", "人工确认", "暂时无法", "知识库未覆盖", "没有查到"],
    )
    knowledge_missed = not bool(knowledge.get("hit")) or not knowledge.get("sources")
    qa_not_low_risk = qa.get("risk_level") in {"medium", "high"} or not qa.get("passed", False)
    blocked_by_dify = action in {"handoff", "no_answer", "retry"}
    safe_send = (
        action == "send"
        and bool(answer.strip())
        and bool(qa.get("passed", False))
        and qa.get("risk_level") == "low"
        and not uncertain_scope
        and not answer_is_uncertain
    )
    if safe_send:
        return False
    return high_stakes and (uncertain_scope or knowledge_missed or answer_is_uncertain or qa_not_low_risk or blocked_by_dify)


def _complaint_or_after_sales_risk(message: str, intent: dict[str, Any], qa: dict[str, Any]) -> bool:
    if _contains_any(message, ["投诉", "破损", "漏水", "退款", "赔偿", "不处理", "态度差", "坏了", "退货"]):
        return True
    question_type = str(intent.get("question_type", ""))
    sentiment = str(intent.get("sentiment", ""))
    return ("投诉" in question_type and "负面" in sentiment) or qa.get("risk_level") == "high"


def _safe_handoff_answer() -> str:
    return "非常抱歉给您带来不便，这类售后问题需要人工同事马上核实处理。请您先提供订单号、到货时间、破损照片或视频、破损数量和签收凭证，我会为您转人工跟进。"


def _build_knowledge_gap(message: str, intent: dict[str, Any], priority: str = "medium") -> dict[str, Any]:
    return {
        "question": message,
        "category": intent.get("question_type") or "未知",
        "priority": priority,
        "suggested_answer": "补充该问题对应的适用条件、限制边界、可承诺内容、需人工核实的信息，以及可直接发给客户的标准话术。",
    }


def _ensure_contract(data: dict[str, Any], original_message: str) -> dict[str, Any]:
    qa = data.get("qa") or _qa(3, 3, 3, 3, 3, "medium", "Dify 未返回质检结构，后端使用保守默认值。")
    if "overall_score" not in qa:
        qa["overall_score"] = round(
            (int(qa.get("accuracy", 3)) + int(qa.get("completeness", 3)) + int(qa.get("professionalism", 3)) + int(qa.get("empathy", 3)) + int(qa.get("efficiency", 3))) / 5,
            2,
        )
    qa["passed"] = bool(qa.get("passed", all(int(qa.get(k, 3)) >= 3 for k in ["accuracy", "completeness", "professionalism", "empathy", "efficiency"])))
    qa.setdefault("risk_level", "medium")
    qa.setdefault("reason", "")
    qa.setdefault("evidence", [])

    decision = data.get("decision") or {}
    action = decision.get("action")
    if action not in {"send", "retry", "handoff", "no_answer"}:
        action = "send" if qa["passed"] and qa["risk_level"] != "high" else "handoff"

    intent = data.get("intent") or {
        "question_type": "未知",
        "customer_type": "未知",
        "urgency": "中",
        "sentiment": "中性",
        "entities": _extract_entities(original_message),
    }
    knowledge = data.get("knowledge") or {"hit": False, "sources": [], "gap_question": original_message}
    answer = data.get("answer") or "这个问题我暂时无法准确确认，已为您转人工处理。"
    knowledge_gap = data.get("knowledge_gap")

    if _complaint_or_after_sales_risk(original_message, intent, qa):
        action = "handoff"
        qa["risk_level"] = "high"
        knowledge_gap = None
        answer = _safe_handoff_answer()
        decision["reason"] = decision.get("reason") or "投诉、破损、退款、赔偿等高风险售后场景，必须转人工处理。"
    elif not knowledge_gap and _requires_conservative_gap(original_message, answer, knowledge, qa, action):
        knowledge_gap = _build_knowledge_gap(
            original_message,
            intent,
            "high" if _contains_any(original_message, ["赔偿", "退款", "投诉", "承诺", "政策"]) else "medium",
        )
        knowledge["hit"] = False
        knowledge["gap_question"] = original_message
        if action == "send":
            action = "no_answer"
        decision["reason"] = decision.get("reason") or "问题涉及高风险或未充分覆盖的知识，后端生成知识盲区并禁止直接自动发送。"

    return {
        "intent": intent,
        "knowledge": knowledge,
        "answer": answer,
        "qa": qa,
        "decision": {
            "action": action,
            "reason": decision.get("reason", "后端根据质检结果自动决策。"),
            "needs_human": action in {"handoff", "no_answer", "retry"},
        },
        "knowledge_gap": knowledge_gap,
        "dify_conversation_id": data.get("dify_conversation_id"),
        "dify_message_id": data.get("dify_message_id"),
        "raw_dify_response": data.get("raw_dify_response", data),
        "latency_ms": data.get("latency_ms"),
    }
