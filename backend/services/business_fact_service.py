from __future__ import annotations

import re
from typing import Any


DEFAULT_STORE_FACTS = {
    "company": "鑫源保温防水防火批发",
    "address": "天津市滨海新区厦门路环渤海建材市场L区33号",
    "hours": "7:30-18:30",
    "phones": ["13512490668", "13682003881"],
    "contacts": ["张庆方", "刘美霞"],
    "navigation": ["鑫源保温防水防火", "环渤海建材市场L区33号"],
    "service_notes": ["支持自提", "可停车", "不限行"],
}


class BusinessFactService:
    """Answers strong business facts from authoritative data before LLM/RAG."""

    ADDRESS_PATTERNS = [
        "你家在哪",
        "你们在哪",
        "门店在哪",
        "店在哪",
        "公司在哪",
        "仓库在哪",
        "地址",
        "位置",
        "定位",
        "导航",
        "到店",
        "自提地址",
    ]
    CONTACT_PATTERNS = [
        "电话",
        "手机号",
        "联系方式",
        "联系人",
        "找谁",
        "联系谁",
        "怎么联系",
        "报价电话",
        "销售电话",
        "微信",
    ]
    HOURS_PATTERNS = ["营业时间", "几点开门", "几点关门", "几点上班", "几点下班", "开门吗", "现在营业"]

    PRODUCT_LOCATION_FALSE_POSITIVES = ["用在哪", "适合在哪", "施工在哪", "项目在哪", "哪里用", "哪里施工"]

    def __init__(self, repository):
        self.repository = repository

    def maybe_answer(self, message: str) -> dict[str, Any] | None:
        fact_type = self._classify(message)
        if not fact_type:
            return None

        store_items = self._list_items("store")
        contact_items = self._list_items("contact")
        facts = self._facts_from_items(store_items, contact_items)
        answer = self._build_answer(fact_type, facts)
        evidence = self._evidence(store_items + contact_items, facts)

        return {
            "intent": {
                "question_type": "门店/联系方式咨询",
                "customer_type": "未知",
                "urgency": "中",
                "sentiment": "中性",
                "entities": ["门店地址", "联系方式"],
            },
            "knowledge": {
                "hit": True,
                "sources": evidence,
                "gap_question": None,
            },
            "answer": answer,
            "qa": {
                "accuracy": 5,
                "completeness": 5,
                "professionalism": 5,
                "empathy": 4,
                "efficiency": 5,
                "overall_score": 4.8,
                "passed": True,
                "risk_level": "low",
                "reason": "门店地址、电话、营业时间属于强事实信息，由后端从 Supabase 门店/联系人知识项优先生成，避免模型编造。",
                "evidence": evidence,
            },
            "decision": {
                "action": "send",
                "reason": "强事实命中，使用权威门店/联系人数据直接自动回复。",
                "needs_human": False,
            },
            "knowledge_gap": None,
            "dify_conversation_id": None,
            "dify_message_id": None,
            "raw_dify_response": {"source": "business_fact_guard", "fact_type": fact_type},
            "latency_ms": 0,
        }

    def _classify(self, message: str) -> str | None:
        normalized = self._normalize(message)
        if not normalized:
            return None
        if any(term in normalized for term in self.PRODUCT_LOCATION_FALSE_POSITIVES):
            return None
        has_address = any(term in normalized for term in self.ADDRESS_PATTERNS)
        has_contact = any(term in normalized for term in self.CONTACT_PATTERNS)
        has_hours = any(term in normalized for term in self.HOURS_PATTERNS)
        if has_address and has_contact:
            return "all"
        if has_address:
            return "address"
        if has_contact:
            return "contact"
        if has_hours:
            return "hours"
        return None

    def _list_items(self, item_type: str) -> list[dict[str, Any]]:
        if not hasattr(self.repository, "list_knowledge_items"):
            return []
        try:
            return self.repository.list_knowledge_items(item_type=item_type)
        except Exception:
            return []

    def _facts_from_items(self, store_items: list[dict[str, Any]], contact_items: list[dict[str, Any]]) -> dict[str, Any]:
        facts = dict(DEFAULT_STORE_FACTS)
        text = "\n".join(self._item_text(item) for item in [*store_items, *contact_items])

        phones = re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", text)
        if phones:
            facts["phones"] = list(dict.fromkeys(phones))

        hours = re.search(r"(\d{1,2}:\d{2}\s*(?:-|至|到|~)\s*\d{1,2}:\d{2})", text)
        if hours:
            facts["hours"] = hours.group(1).replace(" ", "").replace("至", "-").replace("到", "-").replace("~", "-")

        address = re.search(r"(天津市[^，。\n；;]*?(?:L区|Ｌ区)?\s*33号)", text)
        if address:
            facts["address"] = re.sub(r"\s+", "", address.group(1))

        contact_names = []
        for name in DEFAULT_STORE_FACTS["contacts"]:
            if name in text:
                contact_names.append(name)
        if contact_names:
            facts["contacts"] = contact_names

        return facts

    def _build_answer(self, fact_type: str, facts: dict[str, Any]) -> str:
        phones = "、".join(facts.get("phones") or DEFAULT_STORE_FACTS["phones"])
        navigation = " / ".join(facts.get("navigation") or DEFAULT_STORE_FACTS["navigation"])
        notes = "，".join(facts.get("service_notes") or DEFAULT_STORE_FACTS["service_notes"])

        if fact_type == "contact":
            return (
                f"可以直接联系销售电话：{phones}。"
                f"服务时间：{facts['hours']}。"
                "如果要报价，建议一起发产品名称、规格、数量和项目地址，我会先帮您整理报价前置条件。"
            )
        if fact_type == "hours":
            return (
                f"我们营业时间是 {facts['hours']}。"
                f"门店地址：{facts['address']}；销售电话：{phones}。"
            )
        return (
            f"我们门店在{facts['address']}。"
            f"导航可搜：{navigation}。"
            f"营业时间：{facts['hours']}；销售电话：{phones}。"
            f"{notes}。"
        )

    def _evidence(self, items: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
        evidence = []
        for item in items[:5]:
            evidence.append(
                {
                    "type": "supabase_knowledge_item",
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "item_type": item.get("item_type"),
                    "content": self._item_text(item)[:500],
                }
            )
        if not evidence:
            evidence.append(
                {
                    "type": "backend_authoritative_fallback",
                    "title": facts.get("company"),
                    "content": f"{facts.get('address')}；{facts.get('hours')}；{'、'.join(facts.get('phones') or [])}",
                }
            )
        return evidence

    def _item_text(self, item: dict[str, Any]) -> str:
        fields = [
            "title",
            "category",
            "brand",
            "spec",
            "unit",
            "core_params",
            "usage_scenarios",
            "related_items",
            "question",
            "answer",
        ]
        return "\n".join(str(item.get(field) or "") for field in fields if item.get(field))

    def _normalize(self, message: str) -> str:
        return re.sub(r"[\s，。！？、,.!?;；:：]+", "", (message or "").lower())
