from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.knowledge_ops_service import KnowledgeOpsService
from services.repository import get_repository


MANUAL_EDITS = {
    "c3cc0e29-2e48-44d7-8579-aed51ca1e73e": {
        "item_type": "store",
        "product": "鑫源保温防水防火批发门店",
        "category": "门店",
        "brand": "鑫源保温防水防火批发",
        "spec": "天津市滨海新区",
        "unit": "张庆方 13512490668；刘美霞 13682003881",
        "params": "地址：天津市滨海新区厦门路环渤海建材市场L区33号；营业时间：7:30-18:30；导航关键词：鑫源保温防水防火、环渤海建材市场L区33号；停车场：可停车、不限行；支持自提。",
        "usage": "客户询问门店地址、自提、看样、附近仓库、导航路线时使用。",
        "question": "你们门店在哪？可以自提或到店看样吗？",
        "answer": "我们门店在天津市滨海新区厦门路环渤海建材市场L区33号，导航可搜“鑫源保温防水防火”或“环渤海建材市场L区33号”。营业时间 7:30-18:30，支持自提，可停车、不限行。联系电话：张庆方 13512490668，刘美霞 13682003881。",
        "sync": True,
    },
    "81bfdac8-cb69-47bc-9028-5add7f507c21": {
        "item_type": "contact",
        "product": "销售咨询联系人",
        "category": "销售咨询",
        "brand": "销售部",
        "spec": "13512490668；13682003881",
        "unit": "7:30-18:30",
        "params": "产品选型、报价、库存、工程批量、样品咨询由销售联系人承接；涉及最终价格和供货周期必须人工确认。",
        "usage": "客户需要报价、采购、批发、工程项目对接时使用。",
        "question": "我想买材料，找谁报价？",
        "answer": "我可以先帮您整理需求。请提供产品、规格、数量、项目地址和是否含税/配送；销售同事会结合库存和最新价格确认报价。联系电话：13512490668、13682003881，服务时间 7:30-18:30。",
        "sync": True,
    },
}


def main() -> None:
    repo = get_repository()
    service = KnowledgeOpsService(repo)
    items = repo.list_knowledge_items()
    by_doc_id = {str(item.get("dify_document_id")): item for item in items if item.get("dify_document_id")}

    for document_id, payload in MANUAL_EDITS.items():
        item = by_doc_id.get(document_id)
        if not item:
            print(f"missing mapping: {document_id}")
            continue
        updated = service.update_item(str(item["id"]), payload, sync=True)
        title = updated.get("title", "")
        ok = updated.get("sync_status") == "synced" and "?" not in title
        print(f"updated={ok} type={updated.get('item_type')} title={title!r} sync={updated.get('sync_status')}")


if __name__ == "__main__":
    main()
