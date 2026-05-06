from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DOCS_DIR = PROJECT_ROOT / "dify-workflow" / "aggregate-docs"
REPORT_PATH = DOCS_DIR / "import-report.json"
sys.path.insert(0, str(BACKEND_DIR))

from config import DIFY_API_URL, DIFY_DATASET_API_KEY, DIFY_DATASET_ID  # noqa: E402


class DifyImportError(RuntimeError):
    pass


def main() -> int:
    if not DIFY_DATASET_ID or not DIFY_DATASET_API_KEY:
        raise DifyImportError("DIFY_DATASET_ID and DIFY_DATASET_API_KEY are required")
    docs = sorted(path for path in DOCS_DIR.glob("*.md") if path.name[:2].isdigit())
    if not docs:
        raise DifyImportError(f"No aggregate docs found in {DOCS_DIR}")

    existing = _list_existing_documents()
    desired_names = {_document_name(path) for path in docs}
    if os.getenv("DIFY_IMPORT_DELETE_STALE", "").strip().lower() in {"1", "true", "yes"}:
        _delete_stale_documents(existing, desired_names)
        existing = _list_existing_documents()
    existing_report = _load_report()
    retry_failed_only = os.getenv("DIFY_IMPORT_RETRY_FAILED_ONLY", "").strip().lower() in {"1", "true", "yes"}
    previous_by_file = {row.get("file"): row for row in existing_report if row.get("file")}
    report: list[dict[str, Any]] = []
    for index, path in enumerate(docs, 1):
        relative_file = str(path.relative_to(PROJECT_ROOT))
        previous = previous_by_file.get(relative_file)
        if retry_failed_only and previous and previous.get("ok"):
            report.append(previous)
            continue
        name = _document_name(path)
        text = path.read_text(encoding="utf-8")
        document_id = existing.get(name)
        operation = "update" if document_id else "create"
        print(f"[{index}/{len(docs)}] {operation} {name}")
        try:
            response = _update_document_with_retry(document_id, name, text) if document_id else _create_document(name, text)
            report.append(
                {
                    "file": relative_file,
                    "name": name,
                    "operation": operation,
                    "ok": True,
                    "document_id": _extract_document_id(response) or document_id,
                }
            )
        except Exception as exc:
            message = str(exc)
            print(f"  failed: {message}")
            report.append(
                {
                    "file": relative_file,
                    "name": name,
                    "operation": operation,
                    "ok": False,
                    "error": message,
                }
            )
            if "rate limit" in message.lower() or "403" in message:
                _write_report(report)
                break
        _write_report(report)
        if index < len(docs):
            time.sleep(15)

    ok_count = sum(1 for row in report if row.get("ok"))
    print({"ok": ok_count, "total_attempted": len(report), "report": str(REPORT_PATH.relative_to(PROJECT_ROOT))})
    return 0 if ok_count == len(docs) else 1


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DIFY_DATASET_API_KEY}",
        "Content-Type": "application/json",
    }


def _load_report() -> list[dict[str, Any]]:
    if not REPORT_PATH.exists():
        return []
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write_report(report: list[dict[str, Any]]) -> None:
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _request(method: str, path: str, **kwargs: Any) -> Any:
    response = requests.request(
        method,
        f"{DIFY_API_URL.rstrip('/')}{path}",
        headers=_headers(),
        timeout=120,
        **kwargs,
    )
    if not response.ok:
        raise DifyImportError(f"Dify Dataset {response.status_code}: {response.text}")
    return response.json() if response.content else {}


def _list_existing_documents() -> dict[str, str]:
    documents: dict[str, str] = {}
    page = 1
    while page <= 10:
        data = _request(
            "GET",
            f"/datasets/{DIFY_DATASET_ID}/documents",
            params={"page": page, "limit": 100},
        )
        rows = data.get("data") if isinstance(data, dict) else []
        for row in rows or []:
            name = row.get("name")
            document_id = row.get("id")
            if name and document_id:
                documents[name] = document_id
        if not data.get("has_more"):
            break
        page += 1
    return documents


def _create_document(name: str, text: str) -> Any:
    return _request(
        "POST",
        f"/datasets/{DIFY_DATASET_ID}/document/create-by-text",
        json={
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"},
        },
    )


def _delete_document(document_id: str) -> Any:
    return _request("DELETE", f"/datasets/{DIFY_DATASET_ID}/documents/{document_id}")


def _delete_stale_documents(existing: dict[str, str], desired_names: set[str]) -> None:
    prefix = "SmartQA 聚合知识 - "
    for name, document_id in list(existing.items()):
        if not name.startswith(prefix) or name in desired_names:
            continue
        print(f"[cleanup] delete stale {name}")
        try:
            _delete_document(document_id)
        except Exception as exc:
            print(f"  cleanup failed: {exc}")


def _update_document(document_id: str, name: str, text: str) -> Any:
    return _request(
        "POST",
        f"/datasets/{DIFY_DATASET_ID}/documents/{document_id}/update-by-text",
        json={
            "name": name,
            "text": text,
            "process_rule": {"mode": "automatic"},
        },
    )


def _update_document_with_retry(document_id: str, name: str, text: str) -> Any:
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            return _update_document(document_id, name, text)
        except DifyImportError as exc:
            message = str(exc)
            if "Document is not available" not in message or attempt == attempts:
                raise
            wait_seconds = 45 * attempt
            print(f"  document is still indexing; retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
    raise DifyImportError("unreachable retry state")


def _document_name(path: Path) -> str:
    title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("#").strip()
    return f"SmartQA 聚合知识 - {path.stem} - {title}"


def _extract_document_id(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    document = response.get("document") or response.get("data") or response
    return document.get("id", "") if isinstance(document, dict) else ""


if __name__ == "__main__":
    raise SystemExit(main())
