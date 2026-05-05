from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.knowledge_ops_service import KnowledgeOpsService
from services.repository import get_repository


ITEMS = [
    {
        "item_type": "store",
        "category": "门店",
        "product": "门店地址与自提规则模板（待补充真实地址）",
        "brand": "待补充负责人/公司名称",
        "spec": "待补充城市/区域",
        "unit": "待补充联系电话",
        "params": "待补充：详细地址、导航关键词、营业时间、是否支持自提、装车条件、停车/限行说明。",
        "usage": "客户询问门店地址、自提、看样、附近仓库、导航路线时使用。",
        "question": "你们门店在哪？可以自提或到店看样吗？",
        "answer": "可以，我先帮您确认离您最近的门店/仓库。请您提供所在城市或项目地址；门店详细地址、营业时间和联系电话以最新维护信息为准。",
    },
    {
        "item_type": "contact",
        "category": "销售咨询",
        "product": "销售咨询联系人模板（待补充真实电话）",
        "brand": "销售部/待补充联系人",
        "spec": "待补充手机号、座机或企业微信",
        "unit": "待补充服务时间",
        "params": "产品选型、报价、库存、工程批量、样品咨询由销售联系人承接；涉及最终价格和供货周期必须人工确认。",
        "usage": "客户需要报价、采购、批发、工程项目对接时使用。",
        "question": "我想买材料，找谁报价？",
        "answer": "我可以先帮您整理需求。请提供产品、规格、数量、项目地址和是否含税/配送；最终报价由销售同事确认后回复您。",
    },
    {
        "item_type": "contact",
        "category": "售后服务",
        "product": "售后服务联系人模板（待补充真实电话）",
        "brand": "售后部/待补充联系人",
        "spec": "待补充手机号、座机或企业微信",
        "unit": "待补充服务时间",
        "params": "破损、少货、错发、退款、投诉升级必须转人工；客服先收集订单号、到货时间、照片/视频、签收单据。",
        "usage": "客户反馈货损、少货、错发、售后争议、投诉退款时使用。",
        "question": "货破损了怎么办？你们不处理我就投诉退款。",
        "answer": "非常抱歉给您带来影响，这类售后问题需要人工马上核实。我会优先转给售后同事，请您先保留破损照片/视频、订单号、到货时间和签收凭证，方便快速处理。",
    },
    {
        "item_type": "contact",
        "category": "财务开票",
        "product": "财务开票联系人模板（待补充真实电话）",
        "brand": "财务部/待补充联系人",
        "spec": "待补充电话、邮箱或企业微信",
        "unit": "待补充服务时间",
        "params": "开票前需确认公司抬头、税号、地址电话、开户行账号、发票类型、订单/合同信息；对公账户以财务最新确认为准。",
        "usage": "客户询问开票、对公转账、发票资料、合同付款时使用。",
        "question": "可以开发票吗？对公账户发我一下。",
        "answer": "可以处理开票和对公付款信息。为避免信息错误，我会转财务同事确认最新资料；请您提供开票抬头、税号、订单或合同信息。",
    },
    {
        "item_type": "policy",
        "category": "物流规则",
        "product": "天津武清区无电梯配送与上楼规则",
        "policy_scope": "天津武清区及类似需配送、卸货、上楼的项目场景",
        "policy_rule": "报价前必须确认收货地址、楼层、是否有电梯、是否可叉车/货车进场、卸货距离、货量和包装规格。无电梯、限行、人工搬运、夜间进场等可能产生额外费用，最终费用需人工确认。",
        "policy_timeframe": "报价前确认；发货前复核",
        "policy_note": "不得直接承诺免费上楼或固定运费。",
        "question": "天津市武清区，没有电梯。要鲁阳的，能送吗？",
        "answer": "可以先评估配送方案。请您补充具体地址、楼层、是否能进货车/叉车、预计数量和规格；无电梯上楼和人工搬运费用需要人工核算后确认。",
    },
    {
        "item_type": "faq",
        "category": "报价规则",
        "product": "100平米材料报价前置问题",
        "question": "大概100平米多少钱？",
        "answer": "100平米可以估算，但需要先确认材料类型、厚度/规格、品牌、施工位置、是否含税、是否配送和项目地址。不同保温、防水、冷补料、聚氨酯材料的计价单位不同，最终报价以销售确认的最新价格为准。",
        "usage": "客户只提供面积或数量，未提供规格、品牌、配送地址时使用。",
    },
]


def main() -> None:
    repo = get_repository()
    service = KnowledgeOpsService(repo)
    existing = {_key(item) for item in service.list_items()}
    created = 0
    skipped = 0
    for payload in ITEMS:
        key = _key(payload)
        if key in existing:
            skipped += 1
            continue
        service.create_item(payload, publish=True, sync=True)
        existing.add(key)
        created += 1
    print(f"enterprise knowledge seeded: created={created}, skipped={skipped}")


def _key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("item_type") or "").strip(),
        str(item.get("category") or "").strip(),
        str(item.get("title") or item.get("product") or "").strip(),
    )


if __name__ == "__main__":
    main()
