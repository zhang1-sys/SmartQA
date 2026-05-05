from __future__ import annotations

import re
from typing import Any

from dify_dataset_client import build_knowledge_text


class KnowledgeRetrievalService:
    """Lightweight Supabase-backed retrieval used before calling Dify."""

    SEARCH_FIELDS = [
        "item_type",
        "category",
        "title",
        "brand",
        "spec",
        "unit",
        "core_params",
        "usage_scenarios",
        "related_items",
        "question",
        "answer",
        "policy_scope",
        "policy_rule",
        "policy_note",
    ]

    STOP_PHRASES = {
        "多少",
        "多少钱",
        "什么",
        "怎么",
        "可以",
        "能不能",
        "有没有",
        "你们",
        "我们",
        "这个",
        "那个",
        "一下",
        "报价",
        "价格",
        "电话",
        "地址",
    }

    def __init__(self, repository):
        self.repository = repository

    def retrieve(self, query: str, limit: int = 6) -> dict[str, Any]:
        if not query or not hasattr(self.repository, "list_knowledge_items"):
            return {"hit": False, "sources": [], "context": ""}

        try:
            items = self.repository.list_knowledge_items()
        except Exception:
            return {"hit": False, "sources": [], "context": ""}

        terms = self._terms(query)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            score = self._score(item, query, terms)
            if score > 0:
                ranked.append((score, item))

        ranked.sort(key=lambda pair: (pair[0], str(pair[1].get("updated_at") or "")), reverse=True)
        selected = [item for _, item in ranked[:limit]]
        if self._needs_exact_custom_policy_match(query) and not any(self._has_custom_policy_match(item) for item in selected):
            return {"hit": False, "sources": [], "context": ""}
        sources = [
            {
                "title": item.get("title") or item.get("question") or "Knowledge item",
                "content": self._summary(item),
                "item_type": item.get("item_type"),
                "category": item.get("category"),
                "id": str(item.get("id")),
            }
            for item in selected
        ]
        context = "\n\n---\n\n".join(build_knowledge_text(item) for item in selected)
        return {
            "hit": bool(sources),
            "sources": sources,
            "context": context[:12000],
        }

    def _score(self, item: dict[str, Any], query: str, terms: set[str]) -> int:
        text = self._search_text(item)
        lowered = text.lower()
        score = 0
        query_lower = query.lower()
        if query_lower and query_lower in lowered:
            score += 20
        for term in terms:
            if term.lower() in lowered:
                score += max(2, min(len(term), 8))
        title = str(item.get("title") or "")
        category = str(item.get("category") or "")
        for term in terms:
            if term and term in title:
                score += 8
            if term and term in category:
                score += 4
        if item.get("publish_status") == "published":
            score += 1
        if item.get("lifecycle_status") == "active":
            score += 1
        return score

    def _needs_exact_custom_policy_match(self, query: str) -> bool:
        return any(keyword in query for keyword in ["特殊", "定制", "非标"]) and any(
            keyword in query for keyword in ["政策", "防火", "资质", "承诺", "检测", "报告"]
        )

    def _has_custom_policy_match(self, item: dict[str, Any]) -> bool:
        text = self._search_text(item)
        return any(keyword in text for keyword in ["特殊", "定制", "非标"])

    def _search_text(self, item: dict[str, Any]) -> str:
        return " ".join(str(item.get(field) or "") for field in self.SEARCH_FIELDS)

    def _terms(self, query: str) -> set[str]:
        terms: set[str] = set()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+%-]*", query):
            if len(token) >= 2:
                terms.add(token)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", query))
        for size in range(2, min(7, len(cjk) + 1)):
            for index in range(0, len(cjk) - size + 1):
                phrase = cjk[index:index + size]
                if phrase not in self.STOP_PHRASES:
                    terms.add(phrase)
        return terms

    def _summary(self, item: dict[str, Any]) -> str:
        parts = [
            item.get("core_params"),
            item.get("usage_scenarios"),
            item.get("answer"),
            item.get("policy_rule"),
            item.get("policy_note"),
        ]
        return "；".join(str(part).strip() for part in parts if str(part or "").strip())[:800]
