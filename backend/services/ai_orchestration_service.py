from __future__ import annotations

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
            except Exception as exc:
                workflow_error = str(exc)
                result = self._fallback_result(message, workflow_error)

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

    def _fallback_result(self, message: str, error: str) -> dict[str, Any]:
        return {
            "intent": {
                "question_type": "未知",
                "customer_type": "未知",
                "urgency": "高",
                "sentiment": "中性",
                "entities": [],
            },
            "knowledge": {"hit": False, "sources": [], "gap_question": message},
            "answer": "AI 工作流暂时不可用，已转人工处理。",
            "qa": {
                "accuracy": 3,
                "completeness": 3,
                "professionalism": 3,
                "empathy": 3,
                "efficiency": 3,
                "overall_score": 3,
                "passed": False,
                "risk_level": "medium",
                "reason": "Dify 工作流调用失败，系统按企业级兜底策略转人工。",
                "evidence": [{"type": "workflow_error", "message": error[:500]}],
            },
            "decision": {
                "action": "handoff",
                "reason": "Dify 工作流调用失败，禁止自动回复并转人工。",
                "needs_human": True,
            },
            "knowledge_gap": None,
            "dify_conversation_id": None,
            "dify_message_id": None,
            "raw_dify_response": {"error": error[:1000]},
            "latency_ms": None,
        }

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
