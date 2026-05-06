from __future__ import annotations

import re
from typing import Any

from dify_client import run_workflow
from services.business_fact_service import BusinessFactService
from services.customer_memory_service import CustomerMemoryService
from services.knowledge_retrieval_service import KnowledgeRetrievalService


class AIOrchestrationService:
    def __init__(self, repository):
        self.repository = repository

    def handle_customer_message(
        self,
        *,
        conversation_id: str | int,
        trigger_message_id: str | int,
        message: str,
        channel: str = "internal",
        dify_conversation_id: str | None = None,
        customer_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id)
        history = self._history_for_dify(conversation.get("messages", []) if conversation else [])
        memory_service = CustomerMemoryService(self.repository)
        memory_profile = memory_service.profile_for_conversation(conversation)
        enriched_customer_profile = {
            **(customer_profile or {}),
            **memory_profile,
        }
        input_payload = {
            "channel": channel,
            "conversation_id": str(conversation_id),
            "customer_message": message,
            "conversation_history": history,
            "customer_profile": enriched_customer_profile,
        }

        workflow_error = None
        fact_result = BusinessFactService(self.repository).maybe_answer(message)
        if fact_result:
            result = fact_result
        else:
            retrieval = KnowledgeRetrievalService(self.repository).retrieve(message)
            input_payload["knowledge_context"] = retrieval.get("context", "")
            input_payload["knowledge_sources"] = retrieval.get("sources", [])
            try:
                result = run_workflow(
                    message=message,
                    conversation_id=str(conversation_id),
                    conversation_history=history,
                    customer_profile=enriched_customer_profile,
                    knowledge_context=retrieval.get("context", ""),
                    knowledge_sources=retrieval.get("sources", []),
                    dify_conversation_id=dify_conversation_id,
                    channel=channel,
                )
                guarded_result = self._guard_low_quality_dify_result(message, result, retrieval)
                if guarded_result is not result:
                    workflow_error = "Dify quality guard: invalid-input answer for meaningful customer message"
                    result = guarded_result
            except Exception as exc:
                workflow_error = str(exc)
                result = self._fallback_result(message, workflow_error, retrieval)

        decision = result["decision"]["action"]
        ai_run_id = self.repository.save_ai_run(
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            input_payload=input_payload,
            output_payload=result,
            decision=decision,
            status="failed" if workflow_error else "succeeded",
            error=workflow_error,
            latency_ms=result.get("latency_ms"),
            dify_conversation_id=result.get("dify_conversation_id"),
            dify_run_id=result.get("dify_message_id"),
        )

        assistant_message_id = None
        if decision == "send":
            assistant_message_id = self.repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                direction="outbound",
                channel=channel,
                content=result["answer"],
                raw_payload=result,
                dify_message_id=result.get("dify_message_id"),
                delivery_status="stored",
            )
            self.repository.save_qa_result(assistant_message_id, ai_run_id, result["qa"])
            self.repository.update_conversation_status(conversation_id, "ai_replied")
        else:
            self.repository.update_conversation_status(conversation_id, "needs_human")

        gap = result.get("knowledge_gap")
        if gap:
            self.repository.add_or_increment_knowledge_gap(
                question=gap.get("question") or message,
                priority=gap.get("priority", "medium"),
                category=gap.get("category", ""),
                suggested_answer=gap.get("suggested_answer", ""),
                conversation_id=str(conversation_id),
                message_id=str(trigger_message_id),
            )

        memory_service.update_after_ai(
            conversation=conversation,
            trigger_message_id=trigger_message_id,
            customer_message=message,
            result=result,
        )

        return {
            **result,
            "ai_run_id": ai_run_id,
            "assistant_message_id": assistant_message_id,
            "conversation_id": conversation_id,
        }

    def _fallback_result(self, message: str, error: str, retrieval: dict[str, Any] | None = None) -> dict[str, Any]:
        retrieval = retrieval or {}
        if self._is_high_risk_message(message):
            return self._handoff_fallback_result(message, error)
        if retrieval.get("hit") and retrieval.get("sources"):
            return self._knowledge_fallback_result(message, error, retrieval)
        return self._handoff_fallback_result(message, error)

    def _guard_low_quality_dify_result(self, message: str, result: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
        if not self._looks_like_meaningful_chinese(message):
            return result
        answer = str(result.get("answer") or "")
        if not self._looks_like_invalid_input_answer(answer):
            return result
        if retrieval.get("hit") and retrieval.get("sources"):
            fallback = self._knowledge_fallback_result(
                message,
                "Dify returned an invalid-input/garbled-text answer for a meaningful Chinese customer message",
                retrieval,
            )
            fallback["raw_dify_response"] = {
                "source": "quality_guard_supabase_retrieval_fallback",
                "guard_reason": "dify_invalid_input_answer",
                "dify_result": result,
            }
            fallback["dify_conversation_id"] = result.get("dify_conversation_id")
            fallback["dify_message_id"] = result.get("dify_message_id")
            fallback["latency_ms"] = result.get("latency_ms")
            return fallback
        return result

    def _knowledge_fallback_result(self, message: str, error: str, retrieval: dict[str, Any]) -> dict[str, Any]:
        sources = retrieval.get("sources") or []
        answer = self._build_retrieval_answer(message, sources)
        evidence = [
            {"type": "supabase_knowledge_item", **source}
            for source in sources[:5]
            if isinstance(source, dict)
        ]
        evidence.append({"type": "workflow_error", "message": error[:500]})
        return {
            "intent": {
                "question_type": "售前咨询",
                "customer_type": "未知",
                "urgency": "中",
                "sentiment": "中性",
                "entities": self._entities_from_sources(sources),
            },
            "knowledge": {"hit": True, "sources": sources[:5], "gap_question": None},
            "answer": answer,
            "qa": {
                "accuracy": 4,
                "completeness": 4,
                "professionalism": 4,
                "empathy": 3,
                "efficiency": 5,
                "overall_score": 4,
                "passed": True,
                "risk_level": "low",
                "reason": "Dify 工作流异常时，后端基于 Supabase 已命中的结构化知识生成保守答复，并保留人工确认边界。",
                "evidence": evidence,
            },
            "decision": {
                "action": "send",
                "reason": "Dify 工作流异常，但 Supabase 权威知识已命中且问题为低风险，允许后端保守自动回复。",
                "needs_human": False,
            },
            "knowledge_gap": None,
            "dify_conversation_id": None,
            "dify_message_id": None,
            "raw_dify_response": {"error": error[:1000], "source": "supabase_retrieval_fallback"},
            "latency_ms": None,
        }

    def _handoff_fallback_result(self, message: str, error: str) -> dict[str, Any]:
        high_risk = self._is_high_risk_message(message)
        return {
            "intent": {
                "question_type": "售后支持" if high_risk else "未知",
                "customer_type": "未知",
                "urgency": "高",
                "sentiment": "负面" if high_risk else "中性",
                "entities": [],
            },
            "knowledge": {"hit": False, "sources": [], "gap_question": message},
            "answer": (
                "非常抱歉给您带来影响，这类售后问题需要人工同事马上核实处理。"
                "请您先保留订单号、到货时间、破损照片或视频、破损数量和签收凭证，我会为您转人工跟进。"
                if high_risk
                else "AI 工作流暂时不可用，已转人工处理。"
            ),
            "qa": {
                "accuracy": 4 if high_risk else 3,
                "completeness": 4 if high_risk else 3,
                "professionalism": 4 if high_risk else 3,
                "empathy": 5 if high_risk else 3,
                "efficiency": 4 if high_risk else 3,
                "overall_score": 4.2 if high_risk else 3,
                "passed": False,
                "risk_level": "high" if high_risk else "medium",
                "reason": (
                    "售后、破损、投诉或退款场景命中高风险规则，系统在 Dify 异常时仍按企业级兜底转人工，避免承诺赔付或退款结果。"
                    if high_risk
                    else "Dify 工作流调用失败，系统按企业级兜底策略转人工。"
                ),
                "evidence": [{"type": "workflow_error", "message": error[:500]}],
            },
            "decision": {
                "action": "handoff",
                "reason": (
                    "高风险售后/投诉场景必须人工核实，禁止自动承诺处理结果。"
                    if high_risk
                    else "Dify 工作流调用失败，禁止自动回复并转人工。"
                ),
                "needs_human": True,
            },
            "knowledge_gap": None,
            "dify_conversation_id": None,
            "dify_message_id": None,
            "raw_dify_response": {"error": error[:1000]},
            "latency_ms": None,
        }

    def _build_retrieval_answer(self, message: str, sources: list[dict[str, Any]]) -> str:
        primary = next((source for source in sources if isinstance(source, dict)), {})
        title = str(primary.get("title") or "这个产品").strip()
        content = self._clean_source_content(str(primary.get("content") or ""))
        category = str(primary.get("category") or "").strip()
        prefix = f"{title}可以参考以下信息"
        if category and category not in title:
            prefix = f"{title}（{category}）可以参考以下信息"

        if self._asks_price(message):
            return (
                f"{prefix}：{content or '知识库已命中相关产品，但价格需要结合规格、数量和配送方式确认。'}"
                "最终价格、库存和配送费建议由销售同事按当日情况确认。请您补充规格、数量和项目地址。"
            )[:280]
        if self._asks_construction_or_usage(message):
            return (
                f"{prefix}：{content or '按产品说明和现场条件施工，基层、温度和用量需要现场确认。'}"
                "如果您方便，可以再发一下施工位置、用量和现场温度，我帮您继续核对。"
            )[:260]
        return (
            f"{prefix}：{content or '知识库已命中相关资料。'}"
            "如需报价或供货确认，请补充规格、数量和项目地址。"
        )[:260]

    def _clean_source_content(self, content: str) -> str:
        content = re.sub(r"\s+", " ", content).strip(" ；。")
        if not content:
            return ""
        fragments = [fragment.strip() for fragment in re.split(r"[；。]", content) if fragment.strip()]
        return "；".join(fragments[:3]) + ("。" if fragments else "")

    def _entities_from_sources(self, sources: list[dict[str, Any]]) -> list[str]:
        entities = []
        for source in sources[:3]:
            if isinstance(source, dict) and source.get("title"):
                entities.append(str(source["title"]))
        return entities

    def _asks_price(self, message: str) -> bool:
        return any(keyword in message for keyword in ["价格", "报价", "多少钱", "费用", "批发价", "面价"])

    def _asks_construction_or_usage(self, message: str) -> bool:
        return any(keyword in message for keyword in ["施工", "能用", "怎么用", "适合", "冬天", "雨天", "低温", "高温", "用法"])

    def _is_high_risk_message(self, message: str) -> bool:
        return any(
            keyword in message
            for keyword in [
                "投诉",
                "破损",
                "破了",
                "坏了",
                "漏水",
                "退货",
                "退款",
                "赔偿",
                "赔付",
                "不处理",
                "工商",
                "举报",
                "差评",
            ]
        )

    def _looks_like_meaningful_chinese(self, message: str) -> bool:
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", message or "")
        if len(cjk_chars) < 2:
            return False
        noisy_chars = re.findall(r"[?？!！@#$%^&*_=+~`|\\/<>{}\[\]]", message or "")
        return len(noisy_chars) <= max(3, len(cjk_chars) // 2)

    def _looks_like_invalid_input_answer(self, answer: str) -> bool:
        if not answer:
            return False
        return any(
            phrase in answer
            for phrase in [
                "乱码",
                "无法识别您的具体需求",
                "无法识别具体需求",
                "请您重新描述",
                "请重新描述您的需求",
                "重新描述一下",
            ]
        )

    def _history_for_dify(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        history = []
        for message in messages[-10:]:
            role = message.get("role")
            if role not in {"customer", "assistant", "human"}:
                continue
            history.append({
                "role": "assistant" if role in {"assistant", "human"} else "customer",
                "content": message.get("content", ""),
            })
        return history
