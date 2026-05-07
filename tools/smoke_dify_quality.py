from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin
from unittest.mock import patch

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
REGRESSION_PATH = PROJECT_ROOT / "dify-workflow" / "regression-questions.json"
sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run representative SmartQA Dify quality and latency checks.")
    parser.add_argument("--base-url", default=os.getenv("SMARTQA_BASE_URL", "").strip())
    parser.add_argument("--max-latency-ms", type=int, default=int(os.getenv("SMARTQA_DIFY_QUALITY_MAX_LATENCY_MS", "30000")))
    parser.add_argument("--all", action="store_true", help="Run the full regression set instead of the short smoke subset.")
    parser.add_argument("--cases-file", default=str(REGRESSION_PATH))
    parser.add_argument("--json", action="store_true", help="Print compact JSON only.")
    args = parser.parse_args()
    cases = _load_cases(Path(args.cases_file), smoke_only=not args.all)

    if args.base_url:
        result = _run_remote(args.base_url.rstrip("/"), args.max_latency_ms, cases)
    else:
        result = _run_local(args.max_latency_ms, cases)

    print(json.dumps(result, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if result["ok"] else 1


def _load_cases(path: Path, *, smoke_only: bool) -> list[dict]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    cases = [case for case in raw_cases if case.get("smoke") or not smoke_only]
    for case in cases:
        case["expected_action"] = set(case.get("expected_action") or [])
        case["expected_risk"] = set(case.get("expected_risk") or [])
        case.setdefault("required_terms", [])
    return cases


def _run_local(max_latency_ms: int, cases: list[dict]) -> dict:
    os.environ.setdefault("INTERNAL_AUTH_REQUIRED", "false")
    os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"smartqa-quality-{uuid.uuid4().hex}.db"))
    os.environ["WECOM_KF_POLL_ENABLED"] = "false"
    import auth_service
    import app as smartqa_app
    from services.sqlite_repository import SQLiteRepository

    auth_service.INTERNAL_AUTH_REQUIRED = False
    smartqa_app.WECOM_KF_POLL_ENABLED = False
    sqlite_repo = SQLiteRepository()
    with patch("app.start_wecom_kf_poller"), patch("app.get_repository", return_value=sqlite_repo):
        app = smartqa_app.init_app()
    client = app.test_client()
    prefix = f"quality-{uuid.uuid4().hex[:8]}"

    def post_chat(message: str) -> tuple[int, dict, int]:
        started = time.monotonic()
        with patch("app.get_repository", return_value=sqlite_repo):
            response = client.post(
                "/api/chat",
                json={
                    "session_id": prefix,
                    "customer_name": "\u8d28\u91cf\u590d\u6d4b",
                    "customer_type": "\u56de\u5f52\u6d4b\u8bd5\u5ba2\u6237",
                    "message": message,
                },
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return response.status_code, response.get_json() or {}, elapsed_ms

    return _run_cases(post_chat, max_latency_ms, cases, mode="local")


def _run_remote(base_url: str, max_latency_ms: int, cases: list[dict]) -> dict:
    session_id = f"quality-{uuid.uuid4().hex[:10]}"
    session = _http_session()
    register = session.post(
        urljoin(base_url + "/", "api/customer/register"),
        json={"company": "\u56de\u5f52\u6d4b\u8bd5\u5ba2\u6237", "name": "\u8d28\u91cf\u590d\u6d4b", "session_id": session_id},
        timeout=30,
    )
    try:
        register_body = register.json()
    except ValueError:
        register_body = {"text": register.text[:500]}
    if register.status_code != 200:
        return {"ok": False, "error": "customer_register_failed", "status_code": register.status_code, "body": register_body}

    def post_chat(message: str) -> tuple[int, dict, int]:
        started = time.monotonic()
        payload = {
            "session_id": register_body["session_id"],
            "access_token": register_body["access_token"],
            "channel": "web_customer",
            "source": "customer",
            "customer_name": "\u8d28\u91cf\u590d\u6d4b",
            "customer_type": "\u56de\u5f52\u6d4b\u8bd5\u5ba2\u6237",
            "message": message,
        }
        response = None
        last_error = None
        for attempt in range(2):
            try:
                request_session = _http_session()
                response = request_session.post(urljoin(base_url + "/", "api/chat"), json=payload, timeout=100)
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
        if response is None:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return 0, {"error": "request_failed", "detail": str(last_error)[:500]}, elapsed_ms
        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:500]}
        return response.status_code, body, elapsed_ms

    return _run_cases(post_chat, max_latency_ms, cases, mode="remote", base_url=base_url)


def _http_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _run_cases(post_chat, max_latency_ms: int, test_cases: list[dict], **metadata) -> dict:
    results = []
    failures = []
    for case in test_cases:
        status_code, body, elapsed_ms = post_chat(case["message"])
        qa = body.get("qa") or {}
        decision = body.get("decision") or {}
        answer = body.get("answer") or ""
        action = decision.get("action")
        risk = qa.get("risk_level")
        missing_terms = [term for term in case["required_terms"] if term not in answer]
        case_failures = []
        if status_code != 200:
            case_failures.append(f"status_code={status_code}")
        if action not in case["expected_action"]:
            case_failures.append(f"unexpected_action={action}")
        if risk not in case["expected_risk"]:
            case_failures.append(f"unexpected_risk={risk}")
        if missing_terms:
            case_failures.append(f"missing_terms={missing_terms}")
        if elapsed_ms > max_latency_ms:
            case_failures.append(f"latency_ms={elapsed_ms}>{max_latency_ms}")
        if not qa.get("passed", False) and action == "send":
            case_failures.append("sent_answer_with_failed_qa")

        item = {
            "id": case["id"],
            "status_code": status_code,
            "latency_ms": elapsed_ms,
            "action": action,
            "risk_level": risk,
            "qa_passed": qa.get("passed"),
            "qa_score": qa.get("overall_score"),
            "dify_conversation_present": bool(body.get("dify_conversation_id")),
            "knowledge_gap": bool(body.get("knowledge_gap")),
            "error": body.get("error"),
            "error_detail": body.get("detail"),
            "answer_preview": answer[:120],
            "failures": case_failures,
        }
        results.append(item)
        if case_failures:
            failures.append({"id": case["id"], "failures": case_failures})

    latencies = [case["latency_ms"] for case in results]
    return {
        "ok": not failures,
        **metadata,
        "case_count": len(results),
        "max_latency_ms": max(latencies) if latencies else None,
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
        "failures": failures,
        "cases": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())
