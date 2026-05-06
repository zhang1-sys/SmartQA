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
                "id": "cn-winter-cold-patch",
                "item_type": "product",
                "category": "\u4fee\u8865\u6750\u6599",
                "title": "\u51b7\u8865\u6599\uff08\u51ac\u5b63\u4f4e\u6e29\u578b\uff09",
                "core_params": "\u9002\u5408\u4f4e\u6e29\u5b63\u8282\u5e94\u6025\u4fee\u8865\uff1b\u65bd\u5de5\u524d\u5efa\u8bae\u5ba4\u5185\u5b58\u653e\u56de\u6e29\uff1b\u5751\u69fd\u9700\u6e05\u7406\u79ef\u6c34\u548c\u6d6e\u7070\u3002",
                "usage_scenarios": "\u51ac\u5b63\u9053\u8def\u62a2\u4fee\u3001\u4f4e\u6e29\u505c\u8f66\u573a\u4fee\u8865\u3001\u96e8\u540e\u5c0f\u9762\u79ef\u5751\u69fd\u4fee\u590d",
                "answer": "\u4f4e\u6e29\u578b\u51b7\u8865\u6599\u53ef\u7528\u4e8e\u51ac\u5b63\u5e94\u6025\u4fee\u8865\uff0c\u4f46\u65bd\u5de5\u524d\u9700\u6e05\u7406\u79ef\u6c34\u3001\u51b0\u96ea\u548c\u677e\u6563\u57fa\u5c42\u3002",
                "publish_status": "published",
                "lifecycle_status": "active",
            },
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

    with patch(
        "services.ai_orchestration_service.run_workflow",
        return_value={
            "intent": {"question_type": "\u552e\u524d\u54a8\u8be2", "customer_type": "\u672a\u77e5", "urgency": "\u4e2d", "sentiment": "\u4e2d\u6027", "entities": []},
            "knowledge": {"hit": False, "sources": [], "gap_question": None},
            "answer": "\u60a8\u597d\uff0c\u60a8\u53d1\u9001\u7684\u5185\u5bb9\u4f3c\u4e4e\u5305\u542b\u4e71\u7801\uff0c\u65e0\u6cd5\u8bc6\u522b\u5177\u4f53\u9700\u6c42\u3002\u8bf7\u91cd\u65b0\u63cf\u8ff0\u60a8\u7684\u9700\u6c42\u3002",
            "qa": {
                "accuracy": 4,
                "completeness": 4,
                "professionalism": 4,
                "empathy": 3,
                "efficiency": 4,
                "overall_score": 3.8,
                "passed": True,
                "risk_level": "low",
                "reason": "mock",
                "evidence": [],
            },
            "decision": {"action": "send", "reason": "mock", "needs_human": False},
            "knowledge_gap": None,
            "dify_conversation_id": "mock-dify-conv",
            "dify_message_id": "mock-dify-msg",
            "raw_dify_response": {"mock": True},
            "latency_ms": 1000,
        },
    ):
        guarded = service.handle_customer_message(
            conversation_id="conv-3",
            trigger_message_id="msg-3",
            message="\u51b7\u8865\u6599\u51ac\u5929\u80fd\u7528\u5417\uff1f",
        )
        assert guarded["decision"]["action"] == "send"
        assert "\u4e71\u7801" not in guarded["answer"]
        assert guarded["raw_dify_response"]["source"] == "quality_guard_supabase_retrieval_fallback"
    print("dify fallback smoke passed")


if __name__ == "__main__":
    main()
