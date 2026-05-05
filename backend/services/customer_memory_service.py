from __future__ import annotations

import re
from typing import Any


PRODUCT_KEYWORDS = [
    "岩棉板",
    "聚氨酯",
    "聚氨酯喷涂",
    "冷补料",
    "防水涂料",
    "保温砂浆",
    "挤塑板",
    "XPS",
    "EPS",
]

CITY_PATTERN = re.compile(r"([\u4e00-\u9fa5]{2,8})(?:市|区|县|镇|新区)")
SPEC_PATTERN = re.compile(r"(\d+(?:\.\d+)?\s*(?:mm|cm|米|公斤|kg|kg/m3|kg/m³|平|平方|㎡|m2|吨))", re.I)


class CustomerMemoryService:
    def __init__(self, repository):
        self.repository = repository

    def profile_for_conversation(self, conversation: dict[str, Any] | None) -> dict[str, Any]:
        if not conversation or not hasattr(self.repository, "get_customer_memory"):
            return {}
        try:
            memory = self.repository.get_customer_memory(str(conversation["id"]))
        except Exception:
            return {}
        if not memory:
            return {}
        return self._for_dify(memory)

    def update_after_ai(
        self,
        *,
        conversation: dict[str, Any] | None,
        trigger_message_id: str | int,
        customer_message: str,
        result: dict[str, Any],
    ) -> None:
        if not conversation or not hasattr(self.repository, "upsert_customer_memory"):
            return
        facts = self._extract_facts(customer_message, result)
        summary = self._build_summary(customer_message, result)
        try:
            self.repository.upsert_customer_memory(
                conversation=conversation,
                facts=facts,
                summary=summary,
                source_message_id=str(trigger_message_id),
            )
        except Exception:
            return

    def _extract_facts(self, message: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        text = message or ""
        intent = result.get("intent") or {}
        answer = result.get("answer") or ""

        for product in PRODUCT_KEYWORDS:
            if product.lower() in text.lower() or product.lower() in answer.lower():
                facts.append(self._fact("product_interest", self._key(product), product, 0.85))

        for entity in intent.get("entities") or []:
            entity_text = str(entity).strip()
            if entity_text and len(entity_text) <= 40:
                facts.append(self._fact("product_interest", self._key(entity_text), entity_text, 0.75))

        for match in SPEC_PATTERN.findall(text):
            value = re.sub(r"\s+", "", match)
            facts.append(self._fact("spec_requirement", self._key(value), value, 0.8))

        for match in CITY_PATTERN.findall(text):
            city = match.strip()
            if city:
                facts.append(self._fact("city", "last_mentioned_city", city, 0.65))

        if any(keyword in text for keyword in ["多少钱", "报价", "价格", "批发", "一平", "一平方"]):
            facts.append(self._fact("budget_signal", "asks_price", "关注价格/报价", 0.8))

        if any(keyword in text for keyword in ["投诉", "退款", "赔偿", "破损", "漏水", "不处理"]):
            facts.append(self._fact("risk", "after_sales_risk", "存在售后或投诉风险", 0.9))

        question_type = str(intent.get("question_type") or "").strip()
        if question_type:
            facts.append(self._fact("preference", "last_question_type", question_type, 0.7))

        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for fact in facts:
            deduped[(fact["fact_type"], fact["fact_key"])] = fact
        return list(deduped.values())

    def _build_summary(self, message: str, result: dict[str, Any]) -> dict[str, Any]:
        intent = result.get("intent") or {}
        decision = result.get("decision") or {}
        products = [
            fact["fact_value"]
            for fact in self._extract_facts(message, result)
            if fact["fact_type"] == "product_interest"
        ]
        specs = [
            fact["fact_value"]
            for fact in self._extract_facts(message, result)
            if fact["fact_type"] == "spec_requirement"
        ]
        summary_parts = []
        if products:
            summary_parts.append(f"关注产品：{', '.join(products[:3])}")
        if specs:
            summary_parts.append(f"提到规格：{', '.join(specs[:5])}")
        if intent.get("question_type"):
            summary_parts.append(f"最近意图：{intent.get('question_type')}")
        if not summary_parts:
            summary_parts.append(f"最近咨询：{message[:120]}")
        open_questions = ""
        if decision.get("action") in {"handoff", "no_answer", "retry"}:
            open_questions = message[:200]
        return {
            "summary": "；".join(summary_parts),
            "open_questions": open_questions,
            "last_intent": str(intent.get("question_type") or ""),
            "last_product_interest": ", ".join(products[:3]),
            "last_decision": str(decision.get("action") or ""),
        }

    def _for_dify(self, memory: dict[str, Any]) -> dict[str, Any]:
        profile = memory.get("profile") or {}
        facts = memory.get("facts") or []
        summary = memory.get("summary") or {}
        return {
            "memory_profile": {
                "display_name": profile.get("display_name"),
                "company_name": profile.get("company_name"),
                "city": profile.get("city"),
                "customer_type": profile.get("customer_type"),
                "lifecycle_stage": profile.get("lifecycle_stage"),
                "preference_summary": profile.get("preference_summary"),
                "risk_notes": profile.get("risk_notes"),
                "last_intent": profile.get("last_intent"),
                "last_product_interest": profile.get("last_product_interest"),
            },
            "stable_facts": [
                {
                    "type": fact.get("fact_type"),
                    "key": fact.get("fact_key"),
                    "value": fact.get("fact_value"),
                    "confidence": fact.get("confidence"),
                }
                for fact in facts[:20]
            ],
            "conversation_summary": {
                "summary": summary.get("summary"),
                "open_questions": summary.get("open_questions"),
                "last_decision": summary.get("last_decision"),
                "turn_count": summary.get("turn_count"),
            },
        }

    def _fact(self, fact_type: str, fact_key: str, fact_value: str, confidence: float) -> dict[str, Any]:
        return {
            "fact_type": fact_type,
            "fact_key": fact_key,
            "fact_value": fact_value,
            "confidence": confidence,
        }

    def _key(self, value: str) -> str:
        return re.sub(r"\s+", "_", value.strip().lower())[:80]
