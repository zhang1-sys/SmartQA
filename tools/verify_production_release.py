from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "https://smartqa-web.onrender.com").rstrip("/")
    session = requests.Session()
    session.trust_env = False
    checks = []

    checks.append(_get(session, base_url, "/api/system/health", public=True))
    checks.append(_public_chat_invoice(session, base_url))
    checks.append(_non_text_probe(session, base_url))
    checks.append(_protected_endpoint_probe(session, base_url, "/api/conversations"))
    checks.append(_protected_endpoint_probe(session, base_url, "/api/operations/monitor"))
    admin_token = os.getenv("SMARTQA_ADMIN_BEARER_TOKEN", "").strip()
    if admin_token:
        checks.append(_authenticated_monitor_probe(session, base_url, admin_token))

    result = {
        "ok": all(check.get("ok") for check in checks),
        "base_url": base_url,
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def _get(session: requests.Session, base_url: str, path: str, public: bool = False) -> dict:
    try:
        response = session.get(urljoin(base_url + "/", path.lstrip("/")), timeout=45)
        ok = response.status_code == 200
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        return {"name": path, "ok": ok, "status_code": response.status_code, "body_preview": _preview(body)}
    except Exception as exc:
        return {"name": path, "ok": False, "error": str(exc)[:500]}


def _public_chat_invoice(session: requests.Session, base_url: str) -> dict:
    session_id = f"release-{int(time.time())}"
    try:
        register = session.post(
            urljoin(base_url + "/", "api/customer/register"),
            json={"company": "发布验证客户", "name": "发布验证", "session_id": session_id},
            timeout=45,
        )
        try:
            register_body = register.json()
        except ValueError:
            return {"name": "invoice_public_chat", "ok": False, "status_code": register.status_code, "body_preview": register.text[:300]}
        if register.status_code != 200:
            return {"name": "invoice_public_chat", "ok": False, "status_code": register.status_code, "body_preview": _preview(register_body)}
        started = time.monotonic()
        chat = session.post(
            urljoin(base_url + "/", "api/chat"),
            json={
                "session_id": register_body["session_id"],
                "access_token": register_body["access_token"],
                "channel": "web_customer",
                "source": "customer",
                "customer_name": "发布验证",
                "customer_type": "发布验证客户",
                "message": "能开发票吗？支付方式有哪些？",
            },
            timeout=100,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            body = chat.json()
        except ValueError:
            return {"name": "invoice_public_chat", "ok": False, "status_code": chat.status_code, "latency_ms": elapsed_ms, "body_preview": chat.text[:300]}
        ok = (
            chat.status_code == 200
            and body.get("decision", {}).get("action") == "send"
            and "发票" in (body.get("answer") or "")
            and not body.get("dify_conversation_id")
            and elapsed_ms < 10000
        )
        return {
            "name": "invoice_public_chat",
            "ok": ok,
            "status_code": chat.status_code,
            "latency_ms": elapsed_ms,
            "dify_conversation_present": bool(body.get("dify_conversation_id")),
            "answer_preview": (body.get("answer") or "")[:160],
        }
    except Exception as exc:
        return {"name": "invoice_public_chat", "ok": False, "error": str(exc)[:500]}


def _non_text_probe(session: requests.Session, base_url: str) -> dict:
    try:
        response = session.post(
            urljoin(base_url + "/", "api/non-text/transcribe"),
            files={"file": ("probe.png", b"probe", "image/png")},
            data={"kind": "image"},
            timeout=45,
        )
        body = response.json()
        ok = (
            response.status_code == 401
            or (response.status_code in {400, 500} and bool(body.get("error")))
        )
        return {"name": "non_text_endpoint", "ok": ok, "status_code": response.status_code, "error": body.get("error")}
    except Exception as exc:
        return {"name": "non_text_endpoint", "ok": False, "error": str(exc)[:500]}


def _protected_endpoint_probe(session: requests.Session, base_url: str, path: str) -> dict:
    try:
        response = session.get(urljoin(base_url + "/", path.lstrip("/")), timeout=45)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        ok = response.status_code == 401 and body.get("error") == "unauthorized"
        return {"name": f"protected:{path}", "ok": ok, "status_code": response.status_code, "error": body.get("error")}
    except Exception as exc:
        return {"name": f"protected:{path}", "ok": False, "error": str(exc)[:500]}


def _authenticated_monitor_probe(session: requests.Session, base_url: str, token: str) -> dict:
    try:
        response = session.get(
            urljoin(base_url + "/", "api/operations/monitor"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=45,
        )
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        summary = body.get("summary") if isinstance(body, dict) else None
        runtime = body.get("wecom_runtime") if isinstance(body, dict) else None
        ok = response.status_code == 200 and isinstance(summary, dict) and isinstance(runtime, list)
        runtime_keys = [item.get("state_key") for item in runtime[:10]] if isinstance(runtime, list) else []
        return {
            "name": "authenticated_operations_monitor",
            "ok": ok,
            "status_code": response.status_code,
            "summary_keys": sorted(summary.keys())[:10] if isinstance(summary, dict) else [],
            "runtime_keys": runtime_keys,
        }
    except Exception as exc:
        return {"name": "authenticated_operations_monitor", "ok": False, "error": str(exc)[:500]}


def _preview(body: dict) -> dict:
    if not isinstance(body, dict):
        return {}
    keys = ["ok", "data_backend", "config", "error", "reason"]
    return {key: body.get(key) for key in keys if key in body}


if __name__ == "__main__":
    raise SystemExit(main())
