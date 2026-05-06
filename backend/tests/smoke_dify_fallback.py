from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_orchestration_service import AIOrchestrationService


class FakeRepository:
    def __init__(self):
        self.ai_runs = []

    def get_conversation(self, conversation_id):
        return {"id": conversation_id, "messages": []}

    def list_knowledge_items(self, item_type=None, category=None):
        items = [
            {
                "id": "winter-cold-patch",
                "item_type": "product",
                "category": "修补材料",
                "title": "冷补料（冬季低温型）",
                "core_params": "适合低温季节应急修补；低温下仍保持一定和易性；施工前建议室内存放回温",
                "usage_scenarios": "冬季道路抢修、北方市政养护、低温停车场修补",
                "answer": "低温型和易性更好，极低温时建议材料提前回温并清理冰雪。",
                "publish_status": "published",
                "lifecycle_status": "active",
            },
            {
                "id": "aftersales",
                "item_type": "contact",
                "category": "售后服务",
                "title": "售后服务联系人",
                "core_params": "破损、少货、错发、退款、投诉升级必须转人工。",
                "usage_scenarios": "客户反馈货损、少货、错发、售后争议、投诉退款时使用。",
                "answer": "请保留订单号、照片视频和签收凭证。",
                "publish_status": "published",
                "lifecycle_status": "active",
            },
        ]
        if item_type:
            return [item for item in items if item["item_type"] == item_type]
        return items

    def save_ai_run(self, **payload):
        self.ai_runs.append(payload)
        return f"ai-run-{len(self.ai_runs)}"

    def add_message(self, **payload):
        return "assistant-message-1"

    def save_qa_result(self, *args, **kwargs):
        return None

    def update_conversation_status(self, *args, **kwargs):
        return None


def main():
    service = AIOrchestrationService(FakeRepository())
    with patch("services.ai_orchestration_service.run_workflow", side_effect=RuntimeError("Dify schema error")):
        product = service.handle_customer_message(
            conversation_id="conv-1",
            trigger_message_id="msg-1",
            message="冷补料冬天能用吗？",
        )
        assert product["decision"]["action"] == "send"
        assert product["qa"]["passed"] is True
        assert "冬季低温型" in product["answer"]
        assert "Dify schema error" in product["raw_dify_response"]["error"]

        complaint = service.handle_customer_message(
            conversation_id="conv-2",
            trigger_message_id="msg-2",
            message="货破损了，你们不处理我就投诉退款",
        )
        assert complaint["decision"]["action"] == "handoff"
        assert complaint["qa"]["risk_level"] == "high"
        assert "订单号" in complaint["answer"]
        assert "破损照片" in complaint["answer"]
    print("dify fallback smoke passed")


if __name__ == "__main__":
    main()
