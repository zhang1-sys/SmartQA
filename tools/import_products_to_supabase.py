from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.knowledge_ops_service import KnowledgeOpsService
from services.repository import get_repository


CSV_FILES = [
    ROOT / "knowledge-base" / "产品知识表.csv",
    ROOT / "knowledge-base" / "产品知识补充表.csv",
]


def main():
    repo = get_repository()
    service = KnowledgeOpsService(repo)
    existing = {
        _key(item)
        for item in service.list_items(item_type="product")
    }
    created = 0
    skipped = 0

    for file_path in CSV_FILES:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                payload = _payload(row)
                key = _key(payload)
                if key in existing:
                    skipped += 1
                    continue
                service.create_item(payload, publish=True, sync=False)
                existing.add(key)
                created += 1

    print(f"products imported: created={created}, skipped={skipped}")


def _payload(row: dict[str, str]) -> dict[str, object]:
    return {
        "item_type": "product",
        "category": row.get("品类", "").strip(),
        "product": row.get("产品名称", "").strip(),
        "brand": row.get("品牌", "").strip(),
        "spec": row.get("规格型号", "").strip(),
        "unit": row.get("单位", "").strip(),
        "price": row.get("面价（元）", "").strip(),
        "wholesale_price": row.get("批发价（元）", "").strip(),
        "wholesale_condition": row.get("批发条件", "").strip(),
        "params": row.get("核心参数", "").strip(),
        "usage": row.get("适用场景", "").strip(),
        "related_items": row.get("搭配推荐", "").strip(),
        "question": row.get("常见问题", "").strip(),
        "answer": _answer_from_question(row.get("常见问题", "")),
        "lifecycle_status": row.get("状态", "在售").strip(),
        "publish_status": "published",
        "sync_status": "synced",
    }


def _answer_from_question(text: str) -> str:
    text = (text or "").strip()
    if "？" in text:
        return text.split("？", 1)[1].strip()
    if "?" in text:
        return text.split("?", 1)[1].strip()
    return text


def _key(item: dict[str, object]) -> tuple[str, str, str, str]:
    title = str(item.get("title") or item.get("product") or "").strip()
    return (
        str(item.get("category") or "").strip(),
        title,
        str(item.get("brand") or "").strip(),
        str(item.get("spec") or "").strip(),
    )


if __name__ == "__main__":
    main()
