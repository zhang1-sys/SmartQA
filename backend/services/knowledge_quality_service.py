from __future__ import annotations

from typing import Any


class KnowledgeQualityService:
    def __init__(self, repository):
        self.repository = repository

    def report(self) -> dict[str, Any]:
        if not hasattr(self.repository, "list_knowledge_items"):
            return {"items": [], "summary": {}}
        items = self.repository.list_knowledge_items()
        checked = [self._check_item(item) for item in items]
        issue_items = [item for item in checked if item["issues"]]
        return {
            "summary": {
                "total": len(checked),
                "with_issues": len(issue_items),
                "synced": len([i for i in items if i.get("sync_status") == "synced"]),
                "failed_sync": len([i for i in items if i.get("sync_status") == "failed"]),
                "published": len([i for i in items if i.get("publish_status") == "published"]),
                "avg_score": round(sum(item["score"] for item in checked) / len(checked), 1) if checked else 0,
            },
            "items": sorted(issue_items, key=lambda item: (item["score"], item["title"]))[:80],
        }

    def _check_item(self, item: dict[str, Any]) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        item_type = item.get("item_type") or "product"
        title = item.get("title") or ""
        category = item.get("category") or ""
        answer = item.get("answer") or ""
        question = item.get("question") or ""
        core_params = item.get("core_params") or ""
        usage = item.get("usage_scenarios") or ""

        if not title.strip():
            issues.append({"level": "critical", "field": "title", "message": "缺少标题/产品名"})
        if not category.strip():
            issues.append({"level": "warning", "field": "category", "message": "缺少品类，影响筛选和检索"})
        if item.get("publish_status") == "published" and item.get("sync_status") != "synced":
            issues.append({"level": "critical", "field": "sync_status", "message": "已发布但未成功同步到 Dify"})
        if item_type == "product":
            if not core_params.strip():
                issues.append({"level": "warning", "field": "core_params", "message": "缺少核心参数，AI 回答容易泛化"})
            if not usage.strip():
                issues.append({"level": "warning", "field": "usage_scenarios", "message": "缺少适用场景"})
            if not (item.get("list_price") or item.get("wholesale_price")):
                issues.append({"level": "info", "field": "price", "message": "缺少价格字段，涉及报价时更容易转人工"})
        if item_type in {"faq", "policy"}:
            if not question.strip():
                issues.append({"level": "warning", "field": "question", "message": "缺少标准问题"})
            if not answer.strip() and not (item.get("policy_rule") or "").strip():
                issues.append({"level": "critical", "field": "answer", "message": "缺少标准答案/政策规则"})
        if item_type == "store":
            if not core_params.strip():
                issues.append({"level": "critical", "field": "core_params", "message": "缺少门店地址、导航或营业时间"})
            if not (item.get("unit") or "").strip():
                issues.append({"level": "warning", "field": "unit", "message": "缺少门店联系电话"})
            if not usage.strip():
                issues.append({"level": "warning", "field": "usage_scenarios", "message": "缺少服务范围或自提/配送说明"})
            if not answer.strip():
                issues.append({"level": "warning", "field": "answer", "message": "缺少可直接回复客户的话术"})
        if item_type == "contact":
            if not (item.get("spec") or "").strip():
                issues.append({"level": "critical", "field": "spec", "message": "缺少电话、微信或邮箱"})
            if not core_params.strip():
                issues.append({"level": "warning", "field": "core_params", "message": "缺少转接规则或联系边界"})
            if not usage.strip():
                issues.append({"level": "warning", "field": "usage_scenarios", "message": "缺少适用场景"})
            if not answer.strip():
                issues.append({"level": "warning", "field": "answer", "message": "缺少可直接回复客户的话术"})

        score = 100
        for issue in issues:
            score -= {"critical": 30, "warning": 15, "info": 6}.get(issue["level"], 10)
        return {
            "id": item.get("id"),
            "title": title or item.get("product") or "未命名知识",
            "item_type": item_type,
            "category": category,
            "sync_status": item.get("sync_status"),
            "publish_status": item.get("publish_status"),
            "score": max(0, score),
            "issues": issues,
        }
