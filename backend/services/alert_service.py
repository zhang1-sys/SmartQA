from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import (
    OPERATIONS_ALERT_MIN_SEVERITY,
    OPERATIONS_ALERT_RECIPIENTS,
    OPERATIONS_ALERTS_ENABLED,
)
from wecom_client import wecom_client


SEVERITY_RANK = {"info": 1, "warning": 2, "critical": 3}


class OperationsAlertService:
    def __init__(self, repository):
        self.repository = repository

    def send_monitor_alerts(self, monitor: dict[str, Any] | None = None, *, force: bool = False) -> dict[str, Any]:
        if not (OPERATIONS_ALERTS_ENABLED or force):
            return {"ok": False, "reason": "alerts disabled"}
        recipients = _parse_recipients()
        if not recipients:
            return {"ok": False, "reason": "no alert recipients"}
        if not wecom_client.enabled():
            return {"ok": False, "reason": "wecom app not enabled"}
        if monitor is None:
            if not hasattr(self.repository, "operations_monitor"):
                return {"ok": False, "reason": "monitor not supported"}
            monitor = self.repository.operations_monitor()

        min_rank = SEVERITY_RANK.get(OPERATIONS_ALERT_MIN_SEVERITY, 2)
        alerts = [
            alert for alert in monitor.get("alerts", [])
            if SEVERITY_RANK.get(alert.get("level"), 2) >= min_rank
        ]
        if not alerts:
            return {"ok": True, "sent": False, "reason": "no alerts"}

        content = _format_alert_message(alerts, monitor.get("summary") or {})
        result = wecom_client.send_text_to_users(recipients, content)
        if hasattr(self.repository, "add_audit_log"):
            self.repository.add_audit_log(
                actor_type="system",
                action="operations.alert_sent",
                target_type="message",
                metadata={
                    "recipients_count": len(recipients),
                    "alert_count": len(alerts),
                    "result": result,
                },
            )
        return {"ok": True, "sent": True, "alert_count": len(alerts), "result": result}


def _parse_recipients() -> list[str]:
    return [
        item.strip()
        for item in OPERATIONS_ALERT_RECIPIENTS.replace(",", "|").split("|")
        if item.strip()
    ]


def _format_alert_message(alerts: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "SmartQA 运行告警",
        f"时间：{now}",
        f"待人工：{summary.get('needs_human', 0)} | AI失败：{summary.get('failed_ai_runs', 0)} | 投递失败：{summary.get('failed_deliveries', 0)} | 同步失败：{summary.get('failed_sync_jobs', 0)}",
        "",
    ]
    for alert in alerts[:8]:
        lines.append(f"- [{alert.get('level', 'warning')}] {alert.get('title')}：{alert.get('count', 0)}")
        if alert.get("hint"):
            lines.append(f"  处理建议：{alert.get('hint')}")
    lines.append("")
    lines.append("请登录 SmartQA 运行监控页处理。")
    return "\n".join(lines)
