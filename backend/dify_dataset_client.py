from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from config import DIFY_API_URL, DIFY_DATASET_API_KEY, DIFY_DATASET_ID


class DifyDatasetError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(DIFY_DATASET_API_KEY and DIFY_DATASET_ID)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DIFY_DATASET_API_KEY}",
        "Content-Type": "application/json",
    }


def build_knowledge_text(item: dict[str, Any]) -> str:
    item_type = item.get("item_type", "product")
    if item_type == "policy":
        return _compact_lines(
            [
                f"# 售后政策：{item.get('title', '')}",
                f"- 政策类型：{item.get('category', '')}",
                f"- 适用范围：{item.get('policy_scope', '')}",
                f"- 具体规则：{item.get('policy_rule', '')}",
                f"- 时效：{item.get('policy_timeframe', '')}",
                f"- 备注：{item.get('policy_note', '')}",
                f"- 常见问题：{item.get('question', '')}",
                f"- 标准答案：{item.get('answer', '')}",
            ]
        )
    if item_type == "faq":
        return _compact_lines(
            [
                f"# FAQ：{item.get('title', '')}",
                f"- 分类：{item.get('category', '')}",
                f"- 问题：{item.get('question', '')}",
                f"- 答案：{item.get('answer', '')}",
                f"- 适用范围：{item.get('usage_scenarios', '')}",
            ]
        )
    if item_type == "store":
        return _compact_lines(
            [
                f"# 门店/仓库知识：{item.get('title', '')}",
                f"- 类型：{item.get('category', '')}",
                f"- 区域/城市：{item.get('spec', '')}",
                f"- 门店负责人/公司：{item.get('brand', '')}",
                f"- 联系电话/座机：{item.get('unit', '')}",
                f"- 地址、导航、营业时间：{item.get('core_params', '')}",
                f"- 服务范围：{item.get('usage_scenarios', '')}",
                f"- 客户常问问题：{item.get('question', '')}",
                f"- 标准答复：{item.get('answer', '')}",
            ]
        )
    if item_type == "contact":
        return _compact_lines(
            [
                f"# 联系方式知识：{item.get('title', '')}",
                f"- 联系类型/部门：{item.get('category', '')}",
                f"- 联系人/部门：{item.get('brand', '')}",
                f"- 电话/微信/邮箱：{item.get('spec', '')}",
                f"- 服务时间：{item.get('unit', '')}",
                f"- 转接规则：{item.get('core_params', '')}",
                f"- 适用场景：{item.get('usage_scenarios', '')}",
                f"- 客户常问问题：{item.get('question', '')}",
                f"- 标准答复：{item.get('answer', '')}",
            ]
        )
    return _compact_lines(
        [
            f"# 产品知识：{item.get('title', '')}",
            f"- 品类：{item.get('category', '')}",
            f"- 产品名称：{item.get('title', '')}",
            f"- 品牌：{item.get('brand', '')}",
            f"- 规格型号：{item.get('spec', '')}",
            f"- 单位：{item.get('unit', '')}",
            f"- 面价（元）：{item.get('list_price') or ''}",
            f"- 批发价（元）：{item.get('wholesale_price') or ''}",
            f"- 批发条件：{item.get('wholesale_condition', '')}",
            f"- 核心参数：{item.get('core_params', '')}",
            f"- 适用场景：{item.get('usage_scenarios', '')}",
            f"- 搭配推荐：{item.get('related_items', '')}",
            f"- 常见问题：{item.get('question', '')}",
            f"- 标准答案：{item.get('answer', '')}",
            f"- 状态：{item.get('lifecycle_status', '')}",
        ]
    )


def upsert_document(item: dict[str, Any]) -> dict[str, Any]:
    if not enabled():
        raise DifyDatasetError("Dify dataset sync is not configured")

    document_id = item.get("dify_document_id")
    if document_id:
        return update_document(document_id, item)
    return create_document(item)


def create_document(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": _document_name(item),
        "text": build_knowledge_text(item),
        "indexing_technique": "high_quality",
        "process_rule": {"mode": "automatic"},
    }
    response = requests.post(
        f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/document/create-by-text",
        headers=_headers(),
        json=payload,
        timeout=90,
    )
    return _json(response)


def update_document(document_id: str, item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": _document_name(item),
        "text": build_knowledge_text(item),
        "process_rule": {"mode": "automatic"},
    }
    response = requests.post(
        f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/documents/{document_id}/update-by-text",
        headers=_headers(),
        json=payload,
        timeout=90,
    )
    return _json(response)


def list_documents(page: int = 1, limit: int = 100) -> dict[str, Any]:
    if not enabled():
        raise DifyDatasetError("Dify dataset sync is not configured")
    response = requests.get(
        f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/documents",
        headers=_headers(),
        params={"page": page, "limit": limit},
        timeout=90,
    )
    return _json(response)


def delete_document(document_id: str) -> dict[str, Any]:
    if not enabled():
        raise DifyDatasetError("Dify dataset sync is not configured")
    encoded_id = quote(str(document_id), safe="")
    response = requests.delete(
        f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/documents/{encoded_id}",
        headers=_headers(),
        timeout=90,
    )
    return _json(response)


def _document_name(item: dict[str, Any]) -> str:
    prefix = {"product": "产品", "policy": "政策", "faq": "FAQ", "store": "门店", "contact": "联系人"}.get(item.get("item_type"), "知识")
    title = item.get("title") or "未命名知识"
    spec = item.get("spec") or item.get("policy_scope") or item.get("category") or ""
    suffix = f" - {spec}" if spec else ""
    return f"{prefix}：{title}{suffix}"


def _compact_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line.split("：", 1)[-1].strip())


def _json(response: requests.Response) -> dict[str, Any]:
    if not response.ok:
        raise DifyDatasetError(f"Dify Dataset {response.status_code}: {response.text}")
    return response.json() if response.content else {}
