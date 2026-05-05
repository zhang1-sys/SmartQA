from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
OUTPUT_DIR = PROJECT_ROOT / "dify-workflow" / "aggregate-docs"
sys.path.insert(0, str(BACKEND_DIR))

from services.repository import get_repository  # noqa: E402


GROUPS = [
    ("01-store-contacts", "门店地址与联系人", lambda item: item.get("item_type") in {"store", "contact"}),
    ("02-pricing-logistics-aftersales", "报价、物流配送与售后规则", lambda item: item.get("item_type") in {"policy", "faq"}),
    ("03-insulation-products", "保温材料产品知识", lambda item: item.get("item_type") == "product" and "保温" in (item.get("category") or "")),
    ("04-waterproof-products", "防水材料产品知识", lambda item: item.get("item_type") == "product" and "防水" in (item.get("category") or "")),
    ("05-mortar-adhesive-products", "砂浆与粘接材料产品知识", lambda item: item.get("item_type") == "product" and any(key in (item.get("category") or "") for key in ["砂浆", "粘接"])),
    ("06-repair-cold-patch-products", "修补材料与冷补料产品知识", lambda item: item.get("item_type") == "product" and any(key in _item_text(item) for key in ["修补", "冷补", "补漏", "裂缝"])),
    ("07-polyurethane-sealant-products", "聚氨酯、发泡和密封材料知识", lambda item: item.get("item_type") == "product" and any(key in _item_text(item) for key in ["聚氨酯", "发泡", "密封", "胶"])),
    ("08-accessory-products", "辅材及其他产品知识", lambda item: item.get("item_type") == "product" and "辅材" in (item.get("category") or "")),
]


def main() -> int:
    repo = get_repository()
    items = _list_knowledge_items(repo)
    if not items:
        print("No knowledge items found")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    assigned: set[str] = set()
    for item in items:
        item_id = str(item.get("id"))
        for slug, _, predicate in GROUPS:
            if item_id not in assigned and predicate(item):
                grouped[slug].append(item)
                assigned.add(item_id)
                break
    leftovers = [item for item in items if str(item.get("id")) not in assigned]
    if leftovers:
        grouped["09-other-products"].extend(leftovers)

    written = []
    for slug, title, _ in GROUPS + [("09-other-products", "其他未分类知识", lambda item: True)]:
        group_items = grouped.get(slug, [])
        if not group_items:
            continue
        path = OUTPUT_DIR / f"{slug}.md"
        path.write_text(_render_doc(title, group_items), encoding="utf-8")
        written.append({"file": str(path.relative_to(PROJECT_ROOT)), "items": len(group_items)})

    manifest = OUTPUT_DIR / "manifest.md"
    manifest.write_text(_render_manifest(written, len(items)), encoding="utf-8")
    print({"total_items": len(items), "documents": len(written), "written": written})
    return 0


def _list_knowledge_items(repo: Any) -> list[dict[str, Any]]:
    if not hasattr(repo, "list_knowledge_items"):
        return []
    client = getattr(repo, "client", None)
    if not client:
        return repo.list_knowledge_items()

    fields = ",".join(
        [
            "id",
            "item_type",
            "category",
            "title",
            "brand",
            "spec",
            "unit",
            "list_price",
            "wholesale_price",
            "wholesale_condition",
            "core_params",
            "usage_scenarios",
            "related_items",
            "question",
            "answer",
            "policy_rule",
            "policy_scope",
            "policy_timeframe",
            "policy_note",
            "lifecycle_status",
            "updated_at",
        ]
    )
    rows: list[dict[str, Any]] = []
    page_size = 25
    for offset in range(0, 1000, page_size):
        page = client.select(
            "knowledge_items",
            {
                "select": fields,
                "order": "updated_at.desc",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        rows.extend(page)
        if len(page) < page_size:
            break
    return rows


def _render_manifest(written: list[dict[str, Any]], total: int) -> str:
    lines = [
        "# SmartQA Dify 聚合知识文档清单",
        "",
        f"- 来源：Supabase knowledge_items，共 {total} 条结构化知识。",
        "- 用途：导入 Dify Cloud Dataset，作为工作流 Knowledge Retrieval 节点的检索层。",
        "- 权威源：Supabase 仍是结构化数据源，Dify Dataset 是检索执行层。",
        "",
        "## 文档",
        "",
    ]
    for row in written:
        lines.append(f"- `{row['file']}`：{row['items']} 条知识")
    lines.append("")
    return "\n".join(lines)


def _render_doc(title: str, items: list[dict[str, Any]]) -> str:
    lines = [
        f"# {title}",
        "",
        "## 使用边界",
        "",
        "- 本文档用于 SmartQA 企业微信客服、内部客服工作台和 Dify 工作流检索。",
        "- 最终价格、库存、交期、运费、上楼费、赔付、退款、发票和对公账户必须以人工核实为准。",
        "- 未在本文档出现的参数、承诺和政策不得编造，应转人工或生成知识盲区。",
        "",
        "## 知识条目",
        "",
    ]
    for index, item in enumerate(items, 1):
        lines.extend(_render_item(index, item))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_item(index: int, item: dict[str, Any]) -> list[str]:
    item_type = item.get("item_type") or "knowledge"
    title = item.get("title") or item.get("question") or f"知识条目 {index}"
    lines = [f"### {index}. {title}", ""]
    fields = [
        ("类型", item_type),
        ("分类", item.get("category")),
        ("品牌/负责人", item.get("brand")),
        ("规格/区域/电话", item.get("spec")),
        ("单位/服务时间", item.get("unit")),
        ("面价", _money(item.get("list_price"))),
        ("批发价", _money(item.get("wholesale_price"))),
        ("批发条件", item.get("wholesale_condition")),
        ("核心参数/规则", item.get("core_params") or item.get("policy_rule")),
        ("适用场景/范围", item.get("usage_scenarios") or item.get("policy_scope")),
        ("搭配推荐", item.get("related_items")),
        ("常见问题", item.get("question")),
        ("标准答案", item.get("answer")),
        ("时效", item.get("policy_timeframe")),
        ("备注", item.get("policy_note")),
        ("状态", item.get("lifecycle_status")),
    ]
    for label, value in fields:
        value = _clean(value)
        if value:
            lines.append(f"- {label}：{value}")
    return lines


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "none":
        return ""
    return re.sub(r"\s+", " ", text)


def _money(value: Any) -> str:
    if value in {None, ""}:
        return ""
    return str(value)


def _item_text(item: dict[str, Any]) -> str:
    fields = ["category", "title", "brand", "spec", "core_params", "usage_scenarios", "related_items", "question", "answer"]
    return " ".join(str(item.get(field) or "") for field in fields)


if __name__ == "__main__":
    raise SystemExit(main())
