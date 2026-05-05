from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


os.environ.setdefault("INTERNAL_AUTH_REQUIRED", "false")
os.environ.setdefault("MOCK_AI_ENABLED", "true")
os.environ["WECOM_KF_POLL_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_orchestration_service import AIOrchestrationService
from services.repository import get_repository


def main():
    repo = get_repository()
    conversation = repo.create_conversation(
        external_id=f"business-facts-{uuid.uuid4().hex}",
        customer_name="business-facts-smoke",
        customer_type="test",
        channel="internal",
    )
    trigger_message_id = repo.add_message(
        conversation_id=conversation["id"],
        role="customer",
        direction="inbound",
        channel="internal",
        content="你家在哪?",
    )
    result = AIOrchestrationService(repo).handle_customer_message(
        conversation_id=conversation["id"],
        trigger_message_id=trigger_message_id,
        message="你家在哪?",
        channel="internal",
    )
    answer = result["answer"]
    print(answer)
    assert result["decision"]["action"] == "send"
    assert result["knowledge"]["hit"] is True
    assert result["raw_dify_response"]["source"] == "business_fact_guard"
    assert "天津市滨海新区厦门路环渤海建材市场L区33号" in answer
    assert "13512490668" in answer
    assert "13682003881" in answer
    assert "山东" not in answer
    assert "淄博" not in answer
    assert "鲁阳" not in answer
    assert "洛科威" not in answer

    trigger_message_id = repo.add_message(
        conversation_id=conversation["id"],
        role="customer",
        direction="inbound",
        channel="internal",
        content="找谁报价？",
    )
    result = AIOrchestrationService(repo).handle_customer_message(
        conversation_id=conversation["id"],
        trigger_message_id=trigger_message_id,
        message="找谁报价？",
        channel="internal",
    )
    answer = result["answer"]
    print(answer)
    assert result["decision"]["action"] == "send"
    assert result["raw_dify_response"]["source"] == "business_fact_guard"
    assert "销售电话" in answer
    assert "13512490668" in answer
    assert "13682003881" in answer


if __name__ == "__main__":
    main()
