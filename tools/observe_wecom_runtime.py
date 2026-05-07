from __future__ import annotations

import argparse
import json
import os
import time
from urllib.parse import urljoin

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe SmartQA WeCom runtime state from production monitor.")
    parser.add_argument("--base-url", default="https://smartqa-web.onrender.com")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--token", default=os.getenv("SMARTQA_ADMIN_BEARER_TOKEN", ""))
    args = parser.parse_args()

    if not args.token.strip():
        print(json.dumps({
            "ok": False,
            "error": "SMARTQA_ADMIN_BEARER_TOKEN is required for authenticated monitor observation",
        }, ensure_ascii=False, indent=2))
        return 2

    session = requests.Session()
    session.trust_env = False
    samples = []
    for index in range(max(1, args.samples)):
        sample = _fetch_sample(session, args.base_url.rstrip("/"), args.token.strip(), index + 1)
        samples.append(sample)
        if index < args.samples - 1:
            time.sleep(max(5, args.interval_seconds))

    result = _summarize(samples)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def _fetch_sample(session: requests.Session, base_url: str, token: str, sample_index: int) -> dict:
    started = time.monotonic()
    try:
        response = session.get(
            urljoin(base_url + "/", "api/operations/monitor"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=45,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        runtime = body.get("wecom_runtime") if isinstance(body, dict) else []
        return {
            "sample": sample_index,
            "ok": response.status_code == 200,
            "status_code": response.status_code,
            "latency_ms": elapsed_ms,
            "summary": body.get("summary") if isinstance(body, dict) else {},
            "runtime": runtime if isinstance(runtime, list) else [],
        }
    except Exception as exc:
        return {"sample": sample_index, "ok": False, "error": str(exc)[:500]}


def _summarize(samples: list[dict]) -> dict:
    failed_samples = [sample for sample in samples if not sample.get("ok")]
    latest = next((sample for sample in reversed(samples) if sample.get("ok")), {})
    runtime = latest.get("runtime") or []
    by_key = {item.get("state_key"): item for item in runtime if item.get("state_key")}
    kf_poller = by_key.get("kf_poller") or {}
    retry = by_key.get("message_delivery_retry") or {}
    cursor = by_key.get("kf_sync_cursor") or {}
    issues = []
    if failed_samples:
        issues.append(f"{len(failed_samples)} monitor samples failed")
    if not kf_poller:
        issues.append("kf_poller runtime state missing")
    if not cursor:
        issues.append("kf_sync_cursor runtime state missing")
    if _failures(kf_poller) > 0:
        issues.append(f"kf_poller consecutive failures: {_failures(kf_poller)}")
    if retry and _failures(retry) > 0:
        issues.append(f"message_delivery_retry consecutive failures: {_failures(retry)}")
    return {
        "ok": not issues,
        "issues": issues,
        "sample_count": len(samples),
        "latest_summary": latest.get("summary") or {},
        "runtime_keys": sorted(by_key.keys()),
        "kf_poller": _state_preview(kf_poller),
        "kf_sync_cursor": _state_preview(cursor),
        "message_delivery_retry": _state_preview(retry),
        "samples": [
            {
                "sample": sample.get("sample"),
                "ok": sample.get("ok"),
                "status_code": sample.get("status_code"),
                "latency_ms": sample.get("latency_ms"),
                "error": sample.get("error"),
            }
            for sample in samples
        ],
    }


def _failures(state: dict) -> int:
    try:
        return int(((state or {}).get("metadata") or {}).get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        return 0


def _state_preview(state: dict) -> dict:
    metadata = (state or {}).get("metadata") or {}
    return {
        "present": bool(state),
        "updated_at": (state or {}).get("updated_at"),
        "state_value_present": bool((state or {}).get("state_value")),
        "consecutive_failures": _failures(state),
        "last_success_at": metadata.get("last_success_at"),
        "last_failure_at": metadata.get("last_failure_at"),
        "interval_seconds": metadata.get("interval_seconds"),
        "msg_count": metadata.get("msg_count"),
        "has_more": metadata.get("has_more"),
        "last_error": metadata.get("last_error"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
