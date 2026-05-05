from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT


class KnowledgeBase:
    def __init__(self):
        self.items: list[dict[str, Any]] = []
        self._next_id = 1

    def load_from_csv(self) -> None:
        self.items = []
        self._next_id = 1
        csv_path = PROJECT_ROOT / "knowledge-base" / "产品知识表.csv"
        if not csv_path.exists():
            return
        with csv_path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.add({
                    "category": row.get("品类", ""),
                    "product": row.get("产品名称", ""),
                    "brand": row.get("品牌", ""),
                    "spec": row.get("规格型号", ""),
                    "unit": row.get("单位", ""),
                    "price": row.get("面价（元）", ""),
                    "wholesale_price": row.get("批发价（元）", ""),
                    "wholesale_condition": row.get("批发条件", ""),
                    "params": row.get("核心参数", ""),
                    "usage": row.get("适用场景", ""),
                    "combo": row.get("搭配推荐", ""),
                    "faq": row.get("常见问题", ""),
                    "status": row.get("状态", "在售"),
                })

    def list(self, category: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
        items = self.items
        if category and category != "all":
            items = [i for i in items if category in i.get("category", "")]
        if keyword:
            kw = keyword.lower()
            items = [
                i for i in items
                if kw in i.get("product", "").lower()
                or kw in i.get("brand", "").lower()
                or kw in i.get("spec", "").lower()
            ]
        return items

    def add(self, data: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": self._next_id,
            "category": data.get("category", ""),
            "product": data.get("product", ""),
            "brand": data.get("brand", ""),
            "spec": data.get("spec", ""),
            "unit": data.get("unit", ""),
            "price": data.get("price", ""),
            "wholesale_price": data.get("wholesale_price", ""),
            "wholesale_condition": data.get("wholesale_condition", ""),
            "status": data.get("status", "在售"),
            "params": data.get("params", ""),
            "usage": data.get("usage", ""),
            "combo": data.get("combo", ""),
            "faq": data.get("faq", ""),
        }
        self.items.append(item)
        self._next_id += 1
        return item


knowledge_base = KnowledgeBase()
