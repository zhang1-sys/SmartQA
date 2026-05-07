from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from db import (
    add_message,
    create_conversation,
    get_conversation,
    get_conversations,
    get_db,
    get_knowledge_gaps,
    save_qa_result,
    update_conversation_status,
)


class SQLiteRepository:
    backend_name = "sqlite"

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = get_conversations()
        return [self._normalize_conversation(row) for row in rows]

    def get_conversation(self, conversation_id: str | int) -> dict[str, Any] | None:
        conv = get_conversation(int(conversation_id))
        if not conv:
            return None
        messages = [self._normalize_message(m) for m in conv.get("messages", [])]
        normalized = self._normalize_conversation(conv)
        normalized["messages"] = messages
        normalized["ai_runs"] = []
        normalized["knowledge_gaps"] = []
        return normalized

    def find_conversation_by_external_id(self, external_id: str, channel: str = "internal") -> dict[str, Any] | None:
        for conv in self.list_conversations():
            if conv.get("external_conversation_id") == external_id or conv.get("session_id") == external_id:
                return conv
        return None

    def create_conversation(
        self,
        external_id: str,
        customer_name: str = "匿名客户",
        customer_type: str = "未知",
        channel: str = "internal",
        customer_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        conv = create_conversation(external_id, customer_name, customer_type)
        return self._normalize_conversation(conv)

    def update_conversation_status(self, conversation_id: str | int, status: str) -> None:
        sqlite_status = {
            "active": "进行中",
            "ai_replied": "已回复",
            "needs_human": "已转人工",
            "resolved": "已解决",
        }.get(status, status)
        update_conversation_status(int(conversation_id), sqlite_status)

    def update_conversation_operations(self, conversation_id: str | int, payload: dict[str, Any]) -> dict[str, Any]:
        conv = self.get_conversation(conversation_id) or {}
        raw = conv.get("raw_payload") if isinstance(conv.get("raw_payload"), dict) else {}
        ops = {
            "lead_status": payload.get("lead_status", raw.get("lead_status", "new")),
            "next_follow_up_at": payload.get("next_follow_up_at", raw.get("next_follow_up_at")),
            "quotation_status": payload.get("quotation_status", raw.get("quotation_status", "none")),
            "quotation_amount": payload.get("quotation_amount", raw.get("quotation_amount")),
            "conversion_stage": payload.get("conversion_stage", raw.get("conversion_stage", "inquiry")),
        }
        return {**conv, **ops}

    def get_wecom_contact_for_conversation(self, conversation_id: str | int) -> dict[str, Any] | None:
        return None

    def add_message(
        self,
        conversation_id: str | int,
        role: str,
        content: str,
        direction: str = "inbound",
        channel: str = "internal",
        raw_payload: dict[str, Any] | None = None,
        wecom_msg_id: str | None = None,
        dify_message_id: str | None = None,
        delivery_status: str = "stored",
    ) -> str:
        sqlite_role = "assistant" if role in {"assistant", "human"} else role
        return str(add_message(int(conversation_id), sqlite_role, content))

    def update_message_delivery_status(
        self,
        message_id: str | int,
        delivery_status: str,
        delivery_error: str | None = None,
    ) -> None:
        return None

    def get_message(self, message_id: str | int) -> dict[str, Any] | None:
        return None

    def list_failed_deliveries(self, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def get_wecom_runtime_state(self, state_key: str) -> dict[str, Any] | None:
        return None

    def upsert_wecom_runtime_state(
        self,
        state_key: str,
        state_value: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "state_key": state_key,
            "state_value": state_value,
            "metadata": metadata or {},
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def list_wecom_runtime_state(self) -> list[dict[str, Any]]:
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
        return None

    def save_ai_run(
        self,
        conversation_id: str | int,
        trigger_message_id: str | int,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        decision: str,
        status: str = "succeeded",
        error: str | None = None,
        latency_ms: int | None = None,
        dify_conversation_id: str | None = None,
        dify_run_id: str | None = None,
    ) -> str:
        return f"sqlite-ai-run-{trigger_message_id}"

    def save_qa_result(self, message_id: str | int, ai_run_id: str | None, qa: dict[str, Any]) -> None:
        save_qa_result(int(message_id), qa)

    def list_knowledge_gaps(self) -> list[dict[str, Any]]:
        return [self._normalize_gap(g) for g in get_knowledge_gaps()]

    def get_knowledge_gap(self, gap_id: str | int) -> dict[str, Any] | None:
        conn = get_db()
        row = conn.execute("SELECT * FROM knowledge_gaps WHERE id = ?", (gap_id,)).fetchone()
        conn.close()
        return self._normalize_gap(dict(row)) if row else None

    def add_or_increment_knowledge_gap(
        self,
        question: str,
        priority: str = "medium",
        category: str = "",
        suggested_answer: str = "",
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> None:
        from db import add_knowledge_gap

        sqlite_priority = {"high": "紧急", "medium": "中", "low": "低"}.get(priority, priority)
        add_knowledge_gap(question, sqlite_priority)

    def update_knowledge_gap(self, gap_id: str | int, updates: dict[str, Any]) -> dict[str, Any]:
        from db import update_knowledge_gap

        status_map = {
            "open": "待补充",
            "drafted": "待补充",
            "added_to_kb": "已补充",
            "ignored": "忽略",
        }
        payload = dict(updates)
        if payload.get("status") in status_map:
            payload["status"] = status_map[payload["status"]]
        return self._normalize_gap(update_knowledge_gap(int(gap_id), payload))

    def list_knowledge_items(self, item_type: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        conn = get_db()
        sql = "SELECT * FROM knowledge_items WHERE 1=1"
        params: list[Any] = []
        if item_type:
            sql += " AND item_type = ?"
            params.append(item_type)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY updated_at DESC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_knowledge_item(self, item_id: str | int) -> dict[str, Any] | None:
        conn = get_db()
        row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_knowledge_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        conn = get_db()
        keys = list(payload.keys())
        cur = conn.execute(
            f"INSERT INTO knowledge_items ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            [payload[key] for key in keys],
        )
        conn.commit()
        row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (cur.lastrowid,)).fetchone()
        item = dict(row)
        self._save_knowledge_version_sqlite(conn, item, "created")
        conn.commit()
        conn.close()
        return item

    def update_knowledge_item(self, item_id: str | int, payload: dict[str, Any]) -> dict[str, Any]:
        conn = get_db()
        if payload:
            payload = {**payload, "updated_at": datetime.now().isoformat(timespec="seconds")}
            assignments = ", ".join(f"{key} = ?" for key in payload)
            conn.execute(f"UPDATE knowledge_items SET {assignments} WHERE id = ?", list(payload.values()) + [item_id])
            conn.commit()
        row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)).fetchone()
        item = dict(row) if row else {}
        if item:
            self._save_knowledge_version_sqlite(conn, item, "updated")
            conn.commit()
        conn.close()
        return item

    def create_sync_job(self, item_id: str | int, operation: str = "upsert", request_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO knowledge_sync_jobs (knowledge_item_id, operation, request_payload) VALUES (?, ?, ?)",
            (item_id, operation, json.dumps(request_payload or {}, ensure_ascii=False)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM knowledge_sync_jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return dict(row)

    def update_sync_job(self, job_id: str | int, updates: dict[str, Any]) -> dict[str, Any]:
        conn = get_db()
        payload = dict(updates)
        for key in ["request_payload", "response_payload"]:
            if isinstance(payload.get(key), (dict, list)):
                payload[key] = json.dumps(payload[key], ensure_ascii=False)
        if payload:
            assignments = ", ".join(f"{key} = ?" for key in payload)
            conn.execute(f"UPDATE knowledge_sync_jobs SET {assignments} WHERE id = ?", list(payload.values()) + [job_id])
            conn.commit()
        row = conn.execute("SELECT * FROM knowledge_sync_jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else {}

    def list_sync_jobs(self, item_id: str | int | None = None) -> list[dict[str, Any]]:
        conn = get_db()
        if item_id:
            rows = conn.execute("SELECT * FROM knowledge_sync_jobs WHERE knowledge_item_id = ? ORDER BY created_at DESC LIMIT 50", (item_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM knowledge_sync_jobs ORDER BY created_at DESC LIMIT 50").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_knowledge_item_versions(self, item_id: str | int, limit: int = 20) -> list[dict[str, Any]]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM knowledge_item_versions WHERE knowledge_item_id = ? ORDER BY version_number DESC LIMIT ?",
            (item_id, limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def list_audit_logs(
        self,
        *,
        limit: int = 100,
        target_type: str | None = None,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def list_data_governance_policies(self) -> list[dict[str, Any]]:
        return [
            {
                "policy_key": "local_pii_masking",
                "policy_name": "本地敏感信息脱敏",
                "policy_type": "masking",
                "scope": "local",
                "config": {"phone": True, "email": True, "order_id": True},
                "enabled": True,
            }
        ]

    def mark_knowledge_sync(
        self,
        item_id: str | int,
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
        return self.update_knowledge_item(item_id, payload)

    def dashboard(self) -> dict[str, Any]:
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        avg_score = conn.execute("SELECT COALESCE(AVG(overall_score), 0) FROM qa_results").fetchone()[0]
        passed = conn.execute("SELECT COUNT(*) FROM qa_results WHERE passed=1").fetchone()[0]
        total_qa = conn.execute("SELECT COUNT(*) FROM qa_results").fetchone()[0]
        gaps_count = conn.execute("SELECT COUNT(*) FROM knowledge_gaps WHERE status='待补充'").fetchone()[0]
        human_count = conn.execute("SELECT COUNT(*) FROM conversations WHERE status='已转人工'").fetchone()[0]
        dims = conn.execute(
            """SELECT ROUND(AVG(accuracy),2) as accuracy,
                      ROUND(AVG(completeness),2) as completeness,
                      ROUND(AVG(professionalism),2) as professionalism,
                      ROUND(AVG(empathy),2) as empathy,
                      ROUND(AVG(efficiency),2) as efficiency
               FROM qa_results"""
        ).fetchone()
        trend = conn.execute(
            """SELECT DATE(created_at) as date, ROUND(AVG(overall_score),2) as score
               FROM qa_results
               GROUP BY DATE(created_at)
               ORDER BY date DESC
               LIMIT 7"""
        ).fetchall()
        conn.close()
        return {
            "total_conversations": total,
            "wecom_conversations": 0,
            "avg_score": round(avg_score, 2),
            "pass_rate": round(passed / total_qa * 100, 1) if total_qa else 0,
            "auto_reply_rate": round(passed / total_qa * 100, 1) if total_qa else 0,
            "handoff_rate": round(human_count / total * 100, 1) if total else 0,
            "failed_ai_runs": 0,
            "high_risk_qa": 0,
            "knowledge_gaps": gaps_count,
            "knowledge_gap_resolution_rate": 0,
            "top_knowledge_gaps": [],
            "qa_count": total_qa,
            "ai_run_count": 0,
            "dimensions": dict(dims) if dims else {},
            "trend": [dict(t) for t in trend],
            "low_score_cases": [],
            "lead_summary": {
                "lead_statuses": {},
                "quotation_statuses": {},
                "conversion_stages": {},
                "overdue_followups": 0,
                "total_quotation_amount": 0,
            },
        }

    def operations_monitor(self) -> dict[str, Any]:
        jobs = self.list_sync_jobs()
        failed_jobs = [job for job in jobs if job.get("status") == "failed"]
        pending_jobs = [job for job in jobs if job.get("status") in {"pending", "running"}]
        alerts = []
        if failed_jobs:
            alerts.append({"level": "warning", "title": "知识库同步失败", "count": len(failed_jobs), "hint": "本地模式下请查看同步任务错误并重试。"})
        return {
            "summary": {
                "conversations": len(self.list_conversations()),
                "wecom_conversations": 0,
                "messages_sampled": 0,
                "ai_runs_sampled": 0,
                "auto_send_rate": 0,
                "avg_ai_latency_ms": 0,
                "needs_human": 0,
                "failed_ai_runs": 0,
                "failed_deliveries": 0,
                "failed_sync_jobs": len(failed_jobs),
                "pending_sync_items": len(pending_jobs),
                "open_high_gaps": 0,
            },
            "alerts": alerts,
            "failed_ai_runs": [],
            "failed_deliveries": [],
            "failed_sync_jobs": failed_jobs[:10],
            "failed_sync_items": [],
            "pending_sync_items": [],
            "high_open_gaps": [],
            "wecom_runtime": [],
            "recent_audit": [],
        }

    def resolve_current_operation_failures(self, note: str = "", resolved_by: str = "admin") -> dict[str, Any]:
        return {"ok": True, "resolved_count": 0, "skipped_count": 0}

    def _normalize_conversation(self, row: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "进行中": "active",
            "已回复": "ai_replied",
            "已转人工": "needs_human",
            "已解决": "resolved",
        }
        external_id = row.get("session_id") or row.get("external_conversation_id")
        channel = row.get("channel") or ("wecom" if str(external_id or "").startswith("wecom-") else "internal")
        return {
            **row,
            "channel": channel,
            "external_conversation_id": external_id,
            "status_code": status_map.get(row.get("status"), row.get("status", "active")),
            "lead_status": row.get("lead_status", "new"),
            "quotation_status": row.get("quotation_status", "none"),
            "conversion_stage": row.get("conversion_stage", "inquiry"),
        }

    def _normalize_message(self, row: dict[str, Any]) -> dict[str, Any]:
        role = row.get("role", "")
        return {
            **row,
            "direction": "inbound" if role == "customer" else "outbound",
            "channel": row.get("channel", "internal"),
            "created_at": row.get("timestamp") or row.get("created_at"),
        }

    def _normalize_gap(self, row: dict[str, Any]) -> dict[str, Any]:
        priority_map = {"紧急": "high", "中": "medium", "低": "low"}
        status_map = {"待补充": "open", "已补充": "added_to_kb", "忽略": "ignored"}
        return {
            **row,
            "priority_code": priority_map.get(row.get("priority"), row.get("priority", "medium")),
            "status_code": status_map.get(row.get("status"), row.get("status", "open")),
        }

    def _save_knowledge_version_sqlite(self, conn, item: dict[str, Any], change_note: str) -> None:
        row = conn.execute(
            "SELECT version_number FROM knowledge_item_versions WHERE knowledge_item_id = ? ORDER BY version_number DESC LIMIT 1",
            (item["id"],),
        ).fetchone()
        next_version = int(row["version_number"]) + 1 if row else 1
        conn.execute(
            "INSERT INTO knowledge_item_versions (knowledge_item_id, version_number, snapshot, change_note) VALUES (?, ?, ?, ?)",
            (item["id"], next_version, json.dumps(item, ensure_ascii=False), change_note),
        )
