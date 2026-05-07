from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import DIFY_DATASET_ID
from dify_dataset_client import build_knowledge_text, delete_document, list_documents, upsert_document


class KnowledgeOpsService:
    ALLOWED_ITEM_TYPES = {"product", "policy", "faq", "store", "contact"}

    def __init__(self, repository):
        self.repository = repository

    def list_items(self, item_type: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_knowledge_items(item_type=item_type, category=category)

    def create_item(self, payload: dict[str, Any], publish: bool = True, sync: bool = True) -> dict[str, Any]:
        item_payload = self._normalize_payload(payload)
        if publish:
            item_payload["publish_status"] = "published"
            item_payload.setdefault("sync_status", "pending")
        item = self.repository.create_knowledge_item(item_payload)
        if sync and publish:
            item = self.sync_item(item["id"])
        return item

    def update_item(self, item_id: str, payload: dict[str, Any], sync: bool = True) -> dict[str, Any]:
        updates = self._normalize_payload(payload, partial=True)
        updates["sync_status"] = "pending"
        item = self.repository.update_knowledge_item(item_id, updates)
        if sync and item.get("publish_status") == "published":
            item = self.sync_item(item_id)
        return item

    def sync_item(self, item_id: str) -> dict[str, Any]:
        item = self.repository.get_knowledge_item(item_id)
        if not item:
            raise ValueError("Knowledge item not found")

        request_payload = {"text": build_knowledge_text(item), "dify_document_id": item.get("dify_document_id")}
        job = self.repository.create_sync_job(item_id, request_payload=request_payload)
        now = _now()
        self.repository.update_sync_job(job["id"], {"status": "running", "started_at": now})
        self.repository.mark_knowledge_sync(item_id, sync_status="syncing", last_sync_error=None)

        try:
            response = upsert_document(item)
            document_id = _extract_document_id(response) or item.get("dify_document_id")
            self.repository.update_sync_job(
                job["id"],
                {
                    "status": "succeeded",
                    "response_payload": response,
                    "finished_at": _now(),
                },
            )
            return self.repository.mark_knowledge_sync(
                item_id,
                sync_status="synced",
                dify_dataset_id=DIFY_DATASET_ID,
                dify_document_id=document_id,
                last_sync_error=None,
                last_synced_at=_now(),
            )
        except Exception as exc:
            message = str(exc)
            self.repository.update_sync_job(
                job["id"],
                {
                    "status": "failed",
                    "error": message,
                    "finished_at": _now(),
                },
            )
            return self.repository.mark_knowledge_sync(item_id, sync_status="failed", last_sync_error=message)

    def list_sync_jobs(self, item_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_sync_jobs(item_id)

    def dify_document_status(self) -> dict[str, Any]:
        items = self.repository.list_knowledge_items()
        tracked_document_ids = {
            str(item.get("dify_document_id"))
            for item in items
            if item.get("dify_document_id")
        }
        documents = _all_dify_documents()
        managed_documents = [
            document for document in documents
            if _document_id(document) in tracked_document_ids or _is_single_item_document(document)
        ]
        stale_documents = [
            document for document in managed_documents
            if _document_id(document) and _document_id(document) not in tracked_document_ids
        ]
        return {
            "ok": True,
            "tracked_document_count": len(tracked_document_ids),
            "dify_document_count": len(documents),
            "managed_document_count": len(managed_documents),
            "stale_document_count": len(stale_documents),
            "stale_documents": [_document_summary(document) for document in stale_documents[:50]],
        }

    def cleanup_stale_dify_documents(self, limit: int = 20) -> dict[str, Any]:
        status = self.dify_document_status()
        results = []
        for document in status["stale_documents"][:max(1, min(limit, 50))]:
            document_id = document.get("id")
            try:
                response = delete_document(document_id)
                results.append({"id": document_id, "name": document.get("name"), "deleted": True, "response": response})
            except Exception as exc:
                results.append({"id": document_id, "name": document.get("name"), "deleted": False, "error": str(exc)})
        return {
            "ok": all(item.get("deleted") for item in results),
            "available": status["stale_document_count"],
            "attempted": len(results),
            "results": results,
        }

    def promote_gap_to_item(self, gap_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        gap = self._get_gap(gap_id)
        if not gap:
            raise ValueError("Knowledge gap not found")

        item_type = self._item_type(payload.get("item_type") or "faq")
        answer = (payload.get("answer") or gap.get("suggested_answer") or "").strip()
        item_payload = {
            "item_type": item_type,
            "title": payload.get("title") or _title_from_gap(gap),
            "category": payload.get("category") or gap.get("category") or "知识盲区",
            "question": payload.get("question") or gap.get("question") or "",
            "answer": answer,
            "usage_scenarios": payload.get("usage_scenarios") or payload.get("usage") or "",
            "publish_status": "published",
            "sync_status": "pending",
        }
        if item_type == "policy":
            item_payload.update(
                {
                    "policy_scope": payload.get("policy_scope") or payload.get("usage_scenarios") or "",
                    "policy_rule": payload.get("policy_rule") or answer,
                    "policy_timeframe": payload.get("policy_timeframe") or "",
                    "policy_note": payload.get("policy_note") or "",
                }
            )

        item = self.create_item(item_payload, publish=True, sync=payload.get("sync", True))
        updates = {
            "status": "added_to_kb",
            "suggested_answer": answer,
            "resolved_at": _now(),
        }
        gap = self.repository.update_knowledge_gap(gap_id, updates)
        return {"gap": gap, "knowledge_item": item}

    def _get_gap(self, gap_id: str) -> dict[str, Any] | None:
        if hasattr(self.repository, "get_knowledge_gap"):
            return self.repository.get_knowledge_gap(gap_id)
        for gap in self.repository.list_knowledge_gaps():
            if str(gap.get("id")) == str(gap_id):
                return gap
        return None

    def _normalize_payload(self, payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        item_type = self._item_type(payload.get("item_type") or payload.get("type") or "product")
        normalized: dict[str, Any] = {}
        mapping = {
            "category": "category",
            "title": "title",
            "product": "title",
            "brand": "brand",
            "spec": "spec",
            "unit": "unit",
            "price": "list_price",
            "list_price": "list_price",
            "wholesale_price": "wholesale_price",
            "wholesale_condition": "wholesale_condition",
            "params": "core_params",
            "core_params": "core_params",
            "usage": "usage_scenarios",
            "usage_scenarios": "usage_scenarios",
            "related_items": "related_items",
            "question": "question",
            "answer": "answer",
            "policy_scope": "policy_scope",
            "policy_rule": "policy_rule",
            "policy_timeframe": "policy_timeframe",
            "policy_note": "policy_note",
            "status": "lifecycle_status",
            "lifecycle_status": "lifecycle_status",
            "publish_status": "publish_status",
            "sync_status": "sync_status",
        }
        for source, target in mapping.items():
            if source in payload:
                normalized[target] = payload[source]

        if "lifecycle_status" in normalized:
            normalized["lifecycle_status"] = _status_to_code(str(normalized["lifecycle_status"]))
        if "list_price" in normalized:
            normalized["list_price"] = _number_or_none(normalized["list_price"])
        if "wholesale_price" in normalized:
            normalized["wholesale_price"] = _number_or_none(normalized["wholesale_price"])
        if not partial:
            normalized.setdefault("item_type", item_type)
            normalized.setdefault("title", "")
            normalized.setdefault("category", "")
            normalized.setdefault("publish_status", "published")
            normalized.setdefault("sync_status", "pending")
            normalized.setdefault("lifecycle_status", "active")
        elif "item_type" in payload:
            normalized["item_type"] = item_type
        return normalized

    def _item_type(self, item_type: Any) -> str:
        value = str(item_type or "product").strip()
        if value not in self.ALLOWED_ITEM_TYPES:
            raise ValueError(f"Unsupported knowledge item_type: {value}")
        return value


def _extract_document_id(response: dict[str, Any]) -> str | None:
    document = response.get("document") if isinstance(response, dict) else None
    if isinstance(document, dict):
        return document.get("id")
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        document = data.get("document")
        if isinstance(document, dict):
            return document.get("id")
        return data.get("id")
    return response.get("id") if isinstance(response, dict) else None


def _title_from_gap(gap: dict[str, Any]) -> str:
    question = (gap.get("question") or "未命名知识盲区").strip()
    return question[:48]


def _status_to_code(status: str) -> str:
    return {
        "在售": "active",
        "缺货": "out_of_stock",
        "下架": "inactive",
        "active": "active",
        "out_of_stock": "out_of_stock",
        "inactive": "inactive",
    }.get(status, "active")


def _number_or_none(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all_dify_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    page = 1
    while page <= 20:
        response = list_documents(page=page, limit=100)
        rows = response.get("data") or response.get("documents") or []
        if not isinstance(rows, list):
            break
        documents.extend([row for row in rows if isinstance(row, dict)])
        if not response.get("has_more") and len(rows) < 100:
            break
        page += 1
    return documents


def _document_id(document: dict[str, Any]) -> str:
    return str(document.get("id") or "")


def _document_name(document: dict[str, Any]) -> str:
    return str(document.get("name") or document.get("display_name") or "")


def _is_single_item_document(document: dict[str, Any]) -> bool:
    name = _document_name(document)
    return name.startswith(("产品：", "政策：", "FAQ：", "门店：", "联系人："))


def _document_summary(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _document_id(document),
        "name": _document_name(document),
        "indexing_status": document.get("indexing_status") or document.get("status"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
    }
