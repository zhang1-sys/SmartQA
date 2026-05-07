from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase_client import SupabaseRestClient


class SupabaseRepository:
    backend_name = "supabase"

    def __init__(self, client: SupabaseRestClient):
        self.client = client

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = self.client.select(
            "conversations",
            {
                "select": "*",
                "order": "last_message_at.desc",
            },
        )
        return [self._normalize_conversation(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self.client.select("conversations", {"id": f"eq.{conversation_id}", "select": "*"})
        if not rows:
            return None
        messages = self.client.select(
            "messages",
            {
                "conversation_id": f"eq.{conversation_id}",
                "select": "*",
                "order": "created_at.asc",
            },
        )
        ai_runs = self.client.select(
            "ai_runs",
            {
                "conversation_id": f"eq.{conversation_id}",
                "select": "*",
                "order": "created_at.desc",
                "limit": "20",
            },
        )
        gaps = self.client.select(
            "knowledge_gaps",
            {
                "conversation_id": f"eq.{conversation_id}",
                "select": "*",
                "order": "updated_at.desc",
            },
        )
        enriched_runs = [self._normalize_ai_run(run) for run in ai_runs]
        enriched_messages = self._enrich_messages(messages, enriched_runs, gaps)
        customer_memory = None
        try:
            customer_memory = self.get_customer_memory(str(rows[0]["id"]))
        except Exception:
            customer_memory = None
        return {
            **self._normalize_conversation(rows[0]),
            "messages": enriched_messages,
            "ai_runs": enriched_runs,
            "knowledge_gaps": gaps,
            "customer_memory": customer_memory,
        }

    def find_conversation_by_external_id(self, external_id: str, channel: str = "internal") -> dict[str, Any] | None:
        rows = self.client.select(
            "conversations",
            {
                "channel": f"eq.{channel}",
                "external_conversation_id": f"eq.{external_id}",
                "select": "*",
                "limit": "1",
            },
        )
        return self._normalize_conversation(rows[0]) if rows else None

    def create_conversation(
        self,
        external_id: str,
        customer_name: str = "匿名客户",
        customer_type: str = "未知",
        channel: str = "internal",
        customer_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        rows = self.client.insert(
            "conversations",
            {
                "channel": channel,
                "external_conversation_id": external_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "customer_type": customer_type,
                "status": status,
            },
        )
        return self._normalize_conversation(rows[0])

    def upsert_wecom_contact(self, external_user_id: str, display_name: str = "", raw_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self.client.upsert(
            "wecom_contacts",
            {
                "external_user_id": external_user_id,
                "display_name": display_name or external_user_id,
                "raw_profile": raw_profile or {},
            },
            on_conflict="external_user_id",
        )
        return rows[0]

    def update_conversation_status(self, conversation_id: str, status: str) -> None:
        self.client.update("conversations", {"id": f"eq.{conversation_id}"}, {"status": status})

    def update_conversation_operations(self, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "lead_status",
            "next_follow_up_at",
            "quotation_status",
            "quotation_amount",
            "conversion_stage",
        }
        updates = {key: value for key, value in payload.items() if key in allowed}
        if not updates:
            rows = self.client.select("conversations", {"id": f"eq.{conversation_id}", "select": "*", "limit": "1"})
            return self._normalize_conversation(rows[0]) if rows else {}
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self.client.update("conversations", {"id": f"eq.{conversation_id}"}, updates)
        return self._normalize_conversation(rows[0]) if rows else {}

    def get_wecom_contact_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self.client.select(
            "conversations",
            {"id": f"eq.{conversation_id}", "select": "customer_id", "limit": "1"},
        )
        if not rows or not rows[0].get("customer_id"):
            return None
        contacts = self.client.select(
            "wecom_contacts",
            {"id": f"eq.{rows[0]['customer_id']}", "select": "*", "limit": "1"},
        )
        return contacts[0] if contacts else None

    def get_customer_memory(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self.client.select(
            "conversations",
            {"id": f"eq.{conversation_id}", "select": "*", "limit": "1"},
        )
        if not rows:
            return None
        conversation = self._normalize_conversation(rows[0])
        external_key = self._customer_memory_external_key(conversation)
        profiles = self.client.select(
            "customer_profiles",
            {
                "channel": f"eq.{conversation.get('channel') or ''}",
                "external_customer_key": f"eq.{external_key}",
                "select": "*",
                "limit": "1",
            },
        )
        if not profiles:
            return None
        profile = profiles[0]
        facts = self.client.select(
            "customer_facts",
            {
                "customer_profile_id": f"eq.{profile['id']}",
                "select": "*",
                "order": "last_seen_at.desc",
                "limit": "30",
            },
        )
        summaries = self.client.select(
            "conversation_summaries",
            {
                "conversation_id": f"eq.{conversation_id}",
                "select": "*",
                "limit": "1",
            },
        )
        return {
            "profile": profile,
            "facts": facts,
            "summary": summaries[0] if summaries else {},
        }

    def upsert_customer_memory(
        self,
        *,
        conversation: dict[str, Any],
        facts: list[dict[str, Any]],
        summary: dict[str, Any],
        source_message_id: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        external_key = self._customer_memory_external_key(conversation)
        profile_rows = self.client.upsert(
            "customer_profiles",
            {
                "customer_id": conversation.get("customer_id"),
                "channel": conversation.get("channel") or "",
                "external_customer_key": external_key,
                "display_name": conversation.get("customer_name") or "",
                "company_name": conversation.get("customer_type") or "",
                "customer_type": conversation.get("customer_type") or "",
                "last_intent": summary.get("last_intent", ""),
                "last_product_interest": summary.get("last_product_interest", ""),
                "last_contacted_at": now,
                "updated_at": now,
            },
            on_conflict="channel,external_customer_key",
        )
        profile = profile_rows[0]
        for fact in facts:
            fact_type = fact.get("fact_type")
            fact_key = fact.get("fact_key")
            fact_value = fact.get("fact_value")
            if not (fact_type and fact_key and fact_value):
                continue
            self.client.upsert(
                "customer_facts",
                {
                    "customer_profile_id": profile["id"],
                    "fact_type": fact_type,
                    "fact_key": fact_key,
                    "fact_value": fact_value,
                    "confidence": fact.get("confidence", 0.7),
                    "source_conversation_id": conversation.get("id"),
                    "source_message_id": source_message_id,
                    "last_seen_at": now,
                },
                on_conflict="customer_profile_id,fact_type,fact_key",
            )

        existing_summaries = self.client.select(
            "conversation_summaries",
            {
                "conversation_id": f"eq.{conversation['id']}",
                "select": "turn_count",
                "limit": "1",
            },
        )
        turn_count = int((existing_summaries[0] if existing_summaries else {}).get("turn_count") or 0) + 1
        self.client.upsert(
            "conversation_summaries",
            {
                "conversation_id": conversation["id"],
                "customer_profile_id": profile["id"],
                "summary": summary.get("summary", ""),
                "open_questions": summary.get("open_questions", ""),
                "last_intent": summary.get("last_intent", ""),
                "last_product_interest": summary.get("last_product_interest", ""),
                "last_decision": summary.get("last_decision", ""),
                "turn_count": turn_count,
                "updated_at": now,
            },
            on_conflict="conversation_id",
        )
        return self.get_customer_memory(str(conversation["id"])) or {"profile": profile, "facts": [], "summary": {}}

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        direction: str = "inbound",
        channel: str = "internal",
        raw_payload: dict[str, Any] | None = None,
        wecom_msg_id: str | None = None,
        dify_message_id: str | None = None,
        delivery_status: str = "stored",
    ) -> str:
        rows = self.client.insert(
            "messages",
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "direction": direction,
                "channel": channel,
                "raw_payload": raw_payload or {},
                "wecom_msg_id": wecom_msg_id,
                "dify_message_id": dify_message_id,
                "delivery_status": delivery_status,
            },
        )
        return rows[0]["id"]

    def update_message_delivery_status(
        self,
        message_id: str,
        delivery_status: str,
        delivery_error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "delivery_status": delivery_status,
            "delivery_error": delivery_error,
        }
        if delivery_status == "sent":
            payload["delivered_at"] = datetime.now(timezone.utc).isoformat()
        self.client.update("messages", {"id": f"eq.{message_id}"}, payload)

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        try:
            rows = self.client.select(
                "messages",
                {"id": f"eq.{message_id}", "select": "*", "limit": "1"},
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def list_failed_deliveries(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.client.select(
            "messages",
            {
                "select": "id,conversation_id,role,direction,channel,content,delivery_status,delivery_error,created_at,raw_payload",
                "direction": "eq.outbound",
                "delivery_status": "eq.failed",
                "order": "created_at.desc",
                "limit": str(max(1, min(limit, 100))),
            },
        )

    def get_wecom_runtime_state(self, state_key: str) -> dict[str, Any] | None:
        try:
            rows = self.client.select(
                "wecom_runtime_state",
                {"state_key": f"eq.{state_key}", "select": "*", "limit": "1"},
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def upsert_wecom_runtime_state(
        self,
        state_key: str,
        state_value: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            rows = self.client.upsert(
                "wecom_runtime_state",
                {
                    "state_key": state_key,
                    "state_value": state_value,
                    "metadata": metadata or {},
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="state_key",
            )
        except Exception:
            return {}
        return rows[0] if rows else {}

    def list_wecom_runtime_state(self) -> list[dict[str, Any]]:
        try:
            return self.client.select(
                "wecom_runtime_state",
                {"select": "*", "order": "updated_at.desc", "limit": "50"},
            )
        except Exception:
            return []

    def add_audit_log(
        self,
        *,
        actor_type: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.client.insert(
            "audit_logs",
            {
                "actor_type": actor_type,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "metadata": metadata or {},
            },
        )

    def save_ai_run(
        self,
        conversation_id: str,
        trigger_message_id: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        decision: str,
        status: str = "succeeded",
        error: str | None = None,
        latency_ms: int | None = None,
        dify_conversation_id: str | None = None,
        dify_run_id: str | None = None,
    ) -> str:
        rows = self.client.insert(
            "ai_runs",
            {
                "conversation_id": conversation_id,
                "trigger_message_id": trigger_message_id,
                "input": input_payload,
                "output": output_payload,
                "decision": decision,
                "status": status,
                "error": error,
                "latency_ms": latency_ms,
                "dify_conversation_id": dify_conversation_id,
                "dify_run_id": dify_run_id,
            },
        )
        return rows[0]["id"]

    def save_qa_result(self, message_id: str, ai_run_id: str | None, qa: dict[str, Any]) -> None:
        self.client.insert(
            "qa_results",
            {
                "message_id": message_id,
                "ai_run_id": ai_run_id,
                "accuracy": qa["accuracy"],
                "completeness": qa["completeness"],
                "professionalism": qa["professionalism"],
                "empathy": qa["empathy"],
                "efficiency": qa["efficiency"],
                "overall_score": qa["overall_score"],
                "passed": qa["passed"],
                "risk_level": qa.get("risk_level", "low"),
                "reason": qa.get("reason", ""),
                "evidence": qa.get("evidence", []),
            },
        )

    def list_knowledge_gaps(self) -> list[dict[str, Any]]:
        return self.client.select(
            "knowledge_gaps",
            {
                "select": "*",
                "order": "updated_at.desc",
            },
        )

    def get_knowledge_gap(self, gap_id: str) -> dict[str, Any] | None:
        rows = self.client.select("knowledge_gaps", {"id": f"eq.{gap_id}", "select": "*", "limit": "1"})
        return rows[0] if rows else None

    def update_knowledge_gap(self, gap_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"status", "priority", "category", "suggested_answer", "resolved_at"}
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            rows = self.client.select("knowledge_gaps", {"id": f"eq.{gap_id}", "select": "*", "limit": "1"})
            return rows[0] if rows else {}
        rows = self.client.update("knowledge_gaps", {"id": f"eq.{gap_id}"}, payload)
        return rows[0] if rows else {}

    def list_knowledge_items(self, item_type: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "updated_at.desc"}
        if item_type:
            params["item_type"] = f"eq.{item_type}"
        if category:
            params["category"] = f"eq.{category}"
        return self.client.select("knowledge_items", params)

    def get_knowledge_item(self, item_id: str) -> dict[str, Any] | None:
        rows = self.client.select("knowledge_items", {"id": f"eq.{item_id}", "select": "*", "limit": "1"})
        return rows[0] if rows else None

    def create_knowledge_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.insert("knowledge_items", payload)
        item = rows[0]
        self._save_knowledge_version(item, "created")
        return item

    def update_knowledge_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.update("knowledge_items", {"id": f"eq.{item_id}"}, payload)
        item = rows[0] if rows else {}
        if item:
            self._save_knowledge_version(item, "updated")
        return item

    def create_sync_job(self, item_id: str, operation: str = "upsert", request_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self.client.insert(
            "knowledge_sync_jobs",
            {
                "knowledge_item_id": item_id,
                "operation": operation,
                "request_payload": request_payload or {},
            },
        )
        return rows[0]

    def update_sync_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.update("knowledge_sync_jobs", {"id": f"eq.{job_id}"}, updates)
        return rows[0] if rows else {}

    def list_sync_jobs(self, item_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "created_at.desc", "limit": "50"}
        if item_id:
            params["knowledge_item_id"] = f"eq.{item_id}"
        return self.client.select("knowledge_sync_jobs", params)

    def list_knowledge_item_versions(self, item_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.client.select(
            "knowledge_item_versions",
            {
                "knowledge_item_id": f"eq.{item_id}",
                "select": "*",
                "order": "version_number.desc",
                "limit": str(limit),
            },
        )

    def list_audit_logs(
        self,
        *,
        limit: int = 100,
        target_type: str | None = None,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(max(1, min(limit, 200))),
        }
        if target_type:
            params["target_type"] = f"eq.{target_type}"
        if action:
            params["action"] = f"eq.{action}"
        return self.client.select("audit_logs", params)

    def list_data_governance_policies(self) -> list[dict[str, Any]]:
        return self.client.select(
            "data_governance_policies",
            {
                "select": "*",
                "order": "policy_type.asc,policy_key.asc",
            },
        )

    def mark_knowledge_sync(
        self,
        item_id: str,
        *,
        sync_status: str,
        dify_dataset_id: str | None = None,
        dify_document_id: str | None = None,
        last_sync_error: str | None = None,
        last_synced_at: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sync_status": sync_status,
            "last_sync_error": last_sync_error,
        }
        if dify_dataset_id is not None:
            payload["dify_dataset_id"] = dify_dataset_id
        if dify_document_id is not None:
            payload["dify_document_id"] = dify_document_id
        if last_synced_at is not None:
            payload["last_synced_at"] = last_synced_at
        rows = self.client.update("knowledge_items", {"id": f"eq.{item_id}"}, payload)
        return rows[0] if rows else {}

    def add_or_increment_knowledge_gap(
        self,
        question: str,
        priority: str = "medium",
        category: str = "",
        suggested_answer: str = "",
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> None:
        existing = self.client.select(
            "knowledge_gaps",
            {
                "question": f"eq.{question}",
                "status": "eq.open",
                "select": "*",
                "limit": "1",
            },
        )
        if existing:
            row = existing[0]
            self.client.update(
                "knowledge_gaps",
                {"id": f"eq.{row['id']}"},
                {"frequency": int(row.get("frequency", 1)) + 1},
            )
            return
        self.client.insert(
            "knowledge_gaps",
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "question": question,
                "category": category,
                "priority": priority,
                "suggested_answer": suggested_answer,
            },
        )

    def dashboard(self) -> dict[str, Any]:
        conversations = self.client.select("conversations", {"select": "id,status,channel,customer_name,customer_type,lead_status,next_follow_up_at,quotation_status,quotation_amount,conversion_stage"})
        qa_results = self.client.select("qa_results", {"select": "*"})
        gaps = self.client.select("knowledge_gaps", {"select": "id,status,question,priority,category,frequency,updated_at"})
        ai_runs = self.client.select("ai_runs", {"select": "id,decision,status,error,created_at,output,conversation_id", "order": "created_at.desc", "limit": "200"})

        total = len(conversations)
        total_qa = len(qa_results)
        passed = sum(1 for row in qa_results if row.get("passed"))
        handoff = sum(1 for row in conversations if row.get("status") == "needs_human")
        avg_score = round(sum(float(row.get("overall_score") or 0) for row in qa_results) / total_qa, 2) if total_qa else 0
        failed_runs = sum(1 for run in ai_runs if run.get("status") == "failed")
        high_risk = sum(1 for row in qa_results if row.get("risk_level") == "high")
        open_gaps = len([g for g in gaps if g.get("status") == "open"])
        handled_gaps = len([g for g in gaps if g.get("status") in {"added_to_kb", "ignored"}])
        gap_total = len(gaps)
        wecom_total = sum(1 for row in conversations if row.get("channel") == "wecom")
        lead_summary = self._lead_summary(conversations)
        ai_send_runs = sum(1 for run in ai_runs if run.get("decision") == "send")

        dimensions = {}
        for key in ["accuracy", "completeness", "professionalism", "empathy", "efficiency"]:
            dimensions[key] = round(sum(int(row.get(key) or 0) for row in qa_results) / total_qa, 2) if total_qa else 0
        low_score_cases = self._low_score_cases(qa_results, conversations)
        trend = self._qa_trend(qa_results)

        return {
            "total_conversations": total,
            "wecom_conversations": wecom_total,
            "avg_score": avg_score,
            "pass_rate": round(passed / total_qa * 100, 1) if total_qa else 0,
            "auto_reply_rate": round(ai_send_runs / len(ai_runs) * 100, 1) if ai_runs else 0,
            "handoff_rate": round(handoff / total * 100, 1) if total else 0,
            "failed_ai_runs": failed_runs,
            "high_risk_qa": high_risk,
            "knowledge_gaps": open_gaps,
            "knowledge_gap_resolution_rate": round(handled_gaps / gap_total * 100, 1) if gap_total else 0,
            "top_knowledge_gaps": self._top_knowledge_gaps(gaps),
            "qa_count": total_qa,
            "ai_run_count": len(ai_runs),
            "dimensions": dimensions,
            "trend": trend,
            "low_score_cases": low_score_cases,
            "lead_summary": lead_summary,
        }

    def operations_monitor(self) -> dict[str, Any]:
        conversations = self.client.select("conversations", {"select": "id,status,channel,last_message_at,created_at"})
        messages = self.client.select(
            "messages",
            {
                "select": "id,conversation_id,role,direction,channel,delivery_status,delivery_error,created_at,raw_payload",
                "order": "created_at.desc",
                "limit": "300",
            },
        )
        ai_runs = self.client.select(
            "ai_runs",
            {
                "select": "id,status,decision,error,latency_ms,created_at",
                "order": "created_at.desc",
                "limit": "200",
            },
        )
        knowledge_items = self.client.select(
            "knowledge_items",
            {
                "select": "id,title,item_type,sync_status,last_sync_error,last_synced_at,updated_at",
                "order": "updated_at.desc",
                "limit": "200",
            },
        )
        sync_jobs = self.client.select(
            "knowledge_sync_jobs",
            {
                "select": "id,knowledge_item_id,status,error,created_at,finished_at",
                "order": "created_at.desc",
                "limit": "100",
            },
        )
        gaps = self.client.select(
            "knowledge_gaps",
            {
                "select": "id,status,priority,question,updated_at",
                "order": "updated_at.desc",
                "limit": "200",
            },
        )
        recent_audit = self.list_audit_logs(limit=20)
        wecom_runtime = self.list_wecom_runtime_state()

        resolution_keys = self._active_operation_resolution_keys()
        failed_ai_runs = [
            run for run in ai_runs
            if run.get("status") == "failed" and not self._is_operation_resolved(resolution_keys, "ai_run_failed", "ai_runs", run.get("id"))
        ]
        failed_deliveries = [
            msg for msg in messages
            if msg.get("direction") == "outbound"
            and msg.get("delivery_status") == "failed"
            and not self._is_operation_resolved(resolution_keys, "delivery_failed", "messages", msg.get("id"))
        ]
        needs_human = [conv for conv in conversations if conv.get("status") == "needs_human"]
        failed_sync_jobs = [
            job for job in sync_jobs
            if job.get("status") == "failed" and not self._is_operation_resolved(resolution_keys, "knowledge_sync_job_failed", "knowledge_sync_jobs", job.get("id"))
        ]
        failed_sync_items = [
            item for item in knowledge_items
            if item.get("sync_status") == "failed" and not self._is_operation_resolved(resolution_keys, "knowledge_item_sync_failed", "knowledge_items", item.get("id"))
        ]
        pending_sync_items = [item for item in knowledge_items if item.get("sync_status") in {"pending", "syncing"}]
        high_open_gaps = [gap for gap in gaps if gap.get("status") == "open" and gap.get("priority") == "high"]

        latency_values = [int(run.get("latency_ms") or 0) for run in ai_runs if run.get("latency_ms")]
        avg_latency_ms = round(sum(latency_values) / len(latency_values)) if latency_values else 0
        auto_send_runs = [run for run in ai_runs if run.get("decision") == "send"]

        alerts: list[dict[str, Any]] = []
        if failed_ai_runs:
            alerts.append({"level": "critical", "title": "Dify/AI 运行失败", "count": len(failed_ai_runs), "hint": "优先查看失败原因、Dify 工作流状态和模型/知识库配置。"})
        if failed_deliveries:
            alerts.append({"level": "critical", "title": "外发消息投递失败", "count": len(failed_deliveries), "hint": "检查企业微信 access_token、客服账号和客户会话是否仍可回复。"})
        if failed_sync_jobs or failed_sync_items:
            alerts.append({"level": "warning", "title": "知识库同步失败", "count": max(len(failed_sync_jobs), len(failed_sync_items)), "hint": "在知识库页面或监控页执行重试，并查看 Dify Dataset API 返回。"})
        kf_poller_state = next((item for item in wecom_runtime if item.get("state_key") == "kf_poller"), None)
        kf_failures = int(((kf_poller_state or {}).get("metadata") or {}).get("consecutive_failures") or 0)
        if kf_failures:
            alerts.append({"level": "warning", "title": "WeCom KF poller sync failed", "count": kf_failures, "hint": "Check WeCom rate limits, trusted IP, access token, and wecom_runtime.kf_poller last_error."})
        delivery_retry_state = next((item for item in wecom_runtime if item.get("state_key") == "message_delivery_retry"), None)
        delivery_retry_failures = int(((delivery_retry_state or {}).get("metadata") or {}).get("consecutive_failures") or 0)
        if delivery_retry_failures:
            alerts.append({"level": "warning", "title": "Message delivery retry scheduler failed", "count": delivery_retry_failures, "hint": "Check WeCom delivery credentials, failed message targets, and wecom_runtime.message_delivery_retry last_error."})
        if needs_human:
            alerts.append({"level": "warning", "title": "存在待人工会话", "count": len(needs_human), "hint": "内部客服需要及时接管，避免客户长时间等待。"})
        if high_open_gaps:
            alerts.append({"level": "warning", "title": "高优先级知识盲区未处理", "count": len(high_open_gaps), "hint": "先补高频、高风险、影响成交的问题。"})

        return {
            "summary": {
                "conversations": len(conversations),
                "wecom_conversations": len([c for c in conversations if c.get("channel") in {"wecom", "wecom_kf"}]),
                "messages_sampled": len(messages),
                "ai_runs_sampled": len(ai_runs),
                "auto_send_rate": round(len(auto_send_runs) / len(ai_runs) * 100, 1) if ai_runs else 0,
                "avg_ai_latency_ms": avg_latency_ms,
                "needs_human": len(needs_human),
                "failed_ai_runs": len(failed_ai_runs),
                "failed_deliveries": len(failed_deliveries),
                "failed_sync_jobs": len(failed_sync_jobs),
                "pending_sync_items": len(pending_sync_items),
                "open_high_gaps": len(high_open_gaps),
            },
            "alerts": alerts,
            "failed_ai_runs": failed_ai_runs[:10],
            "failed_deliveries": failed_deliveries[:10],
            "failed_sync_jobs": failed_sync_jobs[:10],
            "failed_sync_items": failed_sync_items[:10],
            "pending_sync_items": pending_sync_items[:10],
            "high_open_gaps": high_open_gaps[:10],
            "wecom_runtime": wecom_runtime,
            "recent_audit": recent_audit,
        }

    def resolve_current_operation_failures(self, note: str = "", resolved_by: str = "admin") -> dict[str, Any]:
        candidates = self._operation_resolution_candidates()
        existing = self._active_operation_resolution_keys()
        inserted: list[dict[str, Any]] = []
        skipped = 0
        for candidate in candidates:
            key = (candidate["issue_type"], candidate["target_table"], str(candidate["target_id"]))
            if key in existing:
                skipped += 1
                continue
            rows = self.client.upsert(
                "operations_resolutions",
                {
                    **candidate,
                    "target_id": str(candidate["target_id"]),
                    "status": "active",
                    "resolution_note": note or "历史联调异常已确认归档",
                    "resolved_by": resolved_by,
                },
                on_conflict="issue_type,target_table,target_id",
            )
            if rows:
                inserted.append(rows[0])
        if inserted:
            self.add_audit_log(
                actor_type=resolved_by,
                action="operations.failures_resolved",
                target_type="operations",
                target_id=None,
                metadata={
                    "resolved_count": len(inserted),
                    "skipped_count": skipped,
                    "note": note or "历史联调异常已确认归档",
                },
            )
        return {"ok": True, "resolved_count": len(inserted), "skipped_count": skipped}

    def _operation_resolution_candidates(self) -> list[dict[str, Any]]:
        messages = self.client.select(
            "messages",
            {
                "select": "id,conversation_id,role,direction,channel,delivery_status,created_at",
                "delivery_status": "eq.failed",
                "direction": "eq.outbound",
                "order": "created_at.desc",
                "limit": "300",
            },
        )
        ai_runs = self.client.select(
            "ai_runs",
            {
                "select": "id,status,decision,error,created_at",
                "status": "eq.failed",
                "order": "created_at.desc",
                "limit": "200",
            },
        )
        sync_jobs = self.client.select(
            "knowledge_sync_jobs",
            {
                "select": "id,knowledge_item_id,status,error,created_at",
                "status": "eq.failed",
                "order": "created_at.desc",
                "limit": "100",
            },
        )
        knowledge_items = self.client.select(
            "knowledge_items",
            {
                "select": "id,title,item_type,sync_status,last_sync_error,updated_at",
                "sync_status": "eq.failed",
                "order": "updated_at.desc",
                "limit": "200",
            },
        )
        candidates: list[dict[str, Any]] = []
        candidates.extend({
            "issue_type": "ai_run_failed",
            "target_table": "ai_runs",
            "target_id": run.get("id"),
            "metadata": {"status": run.get("status"), "decision": run.get("decision"), "error": run.get("error"), "created_at": run.get("created_at")},
        } for run in ai_runs if run.get("id"))
        candidates.extend({
            "issue_type": "delivery_failed",
            "target_table": "messages",
            "target_id": msg.get("id"),
            "metadata": {"conversation_id": msg.get("conversation_id"), "channel": msg.get("channel"), "role": msg.get("role"), "created_at": msg.get("created_at")},
        } for msg in messages if msg.get("id"))
        candidates.extend({
            "issue_type": "knowledge_sync_job_failed",
            "target_table": "knowledge_sync_jobs",
            "target_id": job.get("id"),
            "metadata": {"knowledge_item_id": job.get("knowledge_item_id"), "error": job.get("error"), "created_at": job.get("created_at")},
        } for job in sync_jobs if job.get("id"))
        candidates.extend({
            "issue_type": "knowledge_item_sync_failed",
            "target_table": "knowledge_items",
            "target_id": item.get("id"),
            "metadata": {"title": item.get("title"), "item_type": item.get("item_type"), "error": item.get("last_sync_error"), "updated_at": item.get("updated_at")},
        } for item in knowledge_items if item.get("id"))
        return candidates

    def _active_operation_resolution_keys(self) -> set[tuple[str, str, str]]:
        try:
            rows = self.client.select(
                "operations_resolutions",
                {
                    "select": "issue_type,target_table,target_id,status",
                    "status": "eq.active",
                    "limit": "1000",
                },
            )
        except Exception:
            return set()
        return {
            (str(row.get("issue_type")), str(row.get("target_table")), str(row.get("target_id")))
            for row in rows
            if row.get("issue_type") and row.get("target_table") and row.get("target_id")
        }

    def _is_operation_resolved(self, resolution_keys: set[tuple[str, str, str]], issue_type: str, target_table: str, target_id: Any) -> bool:
        if not target_id:
            return False
        return (issue_type, target_table, str(target_id)) in resolution_keys

    def _customer_memory_external_key(self, conversation: dict[str, Any]) -> str:
        if conversation.get("customer_id"):
            return f"contact:{conversation['customer_id']}"
        if conversation.get("external_conversation_id"):
            return str(conversation["external_conversation_id"])
        return str(conversation["id"])

    def _save_knowledge_version(self, item: dict[str, Any], change_note: str) -> None:
        existing = self.client.select(
            "knowledge_item_versions",
            {
                "knowledge_item_id": f"eq.{item['id']}",
                "select": "version_number",
                "order": "version_number.desc",
                "limit": "1",
            },
        )
        next_version = int(existing[0]["version_number"]) + 1 if existing else 1
        self.client.insert(
            "knowledge_item_versions",
            {
                "knowledge_item_id": item["id"],
                "version_number": next_version,
                "snapshot": item,
                "change_note": change_note,
            },
        )

    def _normalize_conversation(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "session_id": row.get("external_conversation_id"),
            "status_code": row.get("status"),
        }

    def _lead_summary(self, conversations: list[dict[str, Any]]) -> dict[str, Any]:
        lead_statuses: dict[str, int] = {}
        quotation_statuses: dict[str, int] = {}
        conversion_stages: dict[str, int] = {}
        overdue_followups = 0
        now = datetime.now(timezone.utc)
        total_quotation_amount = 0.0
        for conversation in conversations:
            lead_status = conversation.get("lead_status") or "new"
            quotation_status = conversation.get("quotation_status") or "none"
            conversion_stage = conversation.get("conversion_stage") or "inquiry"
            lead_statuses[lead_status] = lead_statuses.get(lead_status, 0) + 1
            quotation_statuses[quotation_status] = quotation_statuses.get(quotation_status, 0) + 1
            conversion_stages[conversion_stage] = conversion_stages.get(conversion_stage, 0) + 1
            amount = conversation.get("quotation_amount")
            if amount not in {None, ""}:
                try:
                    total_quotation_amount += float(amount)
                except (TypeError, ValueError):
                    pass
            follow_at = conversation.get("next_follow_up_at")
            if follow_at:
                try:
                    parsed = datetime.fromisoformat(str(follow_at).replace("Z", "+00:00"))
                    if parsed < now and lead_status not in {"won", "lost"}:
                        overdue_followups += 1
                except ValueError:
                    pass
        return {
            "lead_statuses": lead_statuses,
            "quotation_statuses": quotation_statuses,
            "conversion_stages": conversion_stages,
            "overdue_followups": overdue_followups,
            "total_quotation_amount": round(total_quotation_amount, 2),
        }

    def _enrich_messages(
        self,
        messages: list[dict[str, Any]],
        ai_runs: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        message_ids = [str(message["id"]) for message in messages if message.get("id")]
        qa_rows: list[dict[str, Any]] = []
        if message_ids:
            qa_rows = self.client.select(
                "qa_results",
                {
                    "message_id": f"in.({','.join(message_ids)})",
                    "select": "*",
                },
            )

        qa_by_message = {str(row.get("message_id")): row for row in qa_rows}
        run_by_id = {str(run.get("id")): run for run in ai_runs}
        run_by_trigger = {
            str(run.get("trigger_message_id")): run
            for run in ai_runs
            if run.get("trigger_message_id")
        }
        run_by_dify_message = {
            str(run.get("dify_run_id")): run
            for run in ai_runs
            if run.get("dify_run_id")
        }
        gaps_by_message: dict[str, list[dict[str, Any]]] = {}
        for gap in gaps:
            message_id = gap.get("message_id")
            if message_id:
                gaps_by_message.setdefault(str(message_id), []).append(gap)

        enriched: list[dict[str, Any]] = []
        for message in messages:
            item = {**message, "timestamp": message.get("created_at")}
            message_id = str(item.get("id"))
            qa = qa_by_message.get(message_id)
            run = None
            if qa and qa.get("ai_run_id"):
                run = run_by_id.get(str(qa.get("ai_run_id")))
            if not run and item.get("dify_message_id"):
                run = run_by_dify_message.get(str(item.get("dify_message_id")))
            if not run:
                run = run_by_trigger.get(message_id)

            if qa:
                item["qa"] = qa
            if run:
                item["ai_run"] = run
                item["decision"] = run.get("decision_detail")
                item["intent"] = run.get("intent")
                item["knowledge"] = run.get("knowledge")
                item["knowledge_gap"] = run.get("knowledge_gap")
                item["dify_conversation_id"] = run.get("dify_conversation_id")
            if gaps_by_message.get(message_id):
                item["knowledge_gaps"] = gaps_by_message[message_id]
                if not item.get("knowledge_gap"):
                    first_gap = gaps_by_message[message_id][0]
                    item["knowledge_gap"] = {
                        "question": first_gap.get("question"),
                        "priority": first_gap.get("priority"),
                        "category": first_gap.get("category"),
                        "suggested_answer": first_gap.get("suggested_answer"),
                    }
            enriched.append(item)
        return enriched

    def _normalize_ai_run(self, row: dict[str, Any]) -> dict[str, Any]:
        output = row.get("output") or {}
        decision_detail = output.get("decision") or {"action": row.get("decision")}
        return {
            **row,
            "decision_detail": decision_detail,
            "qa": output.get("qa"),
            "intent": output.get("intent"),
            "knowledge": output.get("knowledge"),
            "knowledge_gap": output.get("knowledge_gap"),
            "answer": output.get("answer"),
        }

    def _qa_trend(self, qa_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[float]] = {}
        for row in qa_results:
            created_at = str(row.get("created_at") or "")
            day = created_at[:10] or "unknown"
            buckets.setdefault(day, []).append(float(row.get("overall_score") or 0))
        trend = [
            {"date": day, "score": round(sum(scores) / len(scores), 2), "count": len(scores)}
            for day, scores in buckets.items()
            if day != "unknown" and scores
        ]
        return sorted(trend, key=lambda item: item["date"])[-7:]

    def _low_score_cases(
        self,
        qa_results: list[dict[str, Any]],
        conversations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        low_rows = sorted(
            [
                row for row in qa_results
                if (not row.get("passed")) or float(row.get("overall_score") or 0) < 4 or row.get("risk_level") in {"medium", "high"}
            ],
            key=lambda row: str(row.get("created_at") or ""),
            reverse=True,
        )[:5]
        if not low_rows:
            return []

        message_ids = [str(row["message_id"]) for row in low_rows if row.get("message_id")]
        messages = self.client.select(
            "messages",
            {
                "id": f"in.({','.join(message_ids)})",
                "select": "id,conversation_id,content,created_at",
            },
        ) if message_ids else []
        message_by_id = {str(row.get("id")): row for row in messages}
        conversation_by_id = {str(row.get("id")): row for row in conversations}

        cases: list[dict[str, Any]] = []
        for row in low_rows:
            message = message_by_id.get(str(row.get("message_id")), {})
            conversation = conversation_by_id.get(str(message.get("conversation_id")), {})
            dimensions = {
                "accuracy": row.get("accuracy"),
                "completeness": row.get("completeness"),
                "professionalism": row.get("professionalism"),
                "empathy": row.get("empathy"),
                "efficiency": row.get("efficiency"),
            }
            weakest = min(dimensions.items(), key=lambda item: int(item[1] or 0))[0] if dimensions else ""
            cases.append({
                "message_id": row.get("message_id"),
                "conversation_id": message.get("conversation_id"),
                "customer_name": conversation.get("customer_name") or "未知客户",
                "customer_type": conversation.get("customer_type") or "未知",
                "channel": conversation.get("channel") or "internal",
                "content": message.get("content") or "",
                "overall_score": float(row.get("overall_score") or 0),
                "risk_level": row.get("risk_level") or "low",
                "passed": row.get("passed"),
                "reason": row.get("reason") or "",
                "weakest_dimension": weakest,
                "created_at": row.get("created_at"),
            })
        return cases

    def _top_knowledge_gaps(self, gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        priority_rank = {"high": 3, "medium": 2, "low": 1}
        grouped: dict[str, dict[str, Any]] = {}
        for gap in gaps:
            if gap.get("status") != "open":
                continue
            question = (gap.get("question") or "").strip()
            if not question:
                continue
            current = grouped.setdefault(question, {
                **gap,
                "frequency": 0,
                "duplicate_count": 0,
            })
            current["frequency"] = int(current.get("frequency") or 0) + int(gap.get("frequency") or 1)
            current["duplicate_count"] = int(current.get("duplicate_count") or 0) + 1
            if priority_rank.get(gap.get("priority"), 0) > priority_rank.get(current.get("priority"), 0):
                current["priority"] = gap.get("priority")
        return sorted(
            grouped.values(),
            key=lambda row: (
                priority_rank.get(row.get("priority"), 0),
                int(row.get("frequency") or 0),
                str(row.get("updated_at") or ""),
            ),
            reverse=True,
        )[:8]
