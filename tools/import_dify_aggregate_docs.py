from __future__ import annotations

import json
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
    docs = sorted(path for path in DOCS_DIR.glob("*.md") if path.name != "manifest.md")
    if not docs:
        raise DifyImportError(f"No aggregate docs found in {DOCS_DIR}")

    existing = _list_existing_documents()
    report: list[dict[str, Any]] = []
    for index, path in enumerate(docs, 1):
        name = _document_name(path)
        text = path.read_text(encoding="utf-8")
        document_id = existing.get(name)
        operation = "update" if document_id else "create"
        print(f"[{index}/{len(docs)}] {operation} {name}")
        try:
            response = _update_document(document_id, name, text) if document_id else _create_document(name, text)
            report.append(
                {
                    "file": str(path.relative_to(PROJECT_ROOT)),
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
                    "file": str(path.relative_to(PROJECT_ROOT)),
                    "name": name,
                    "operation": operation,
                    "ok": False,
                    "error": message,
                }
            )
            if "rate limit" in message.lower() or "403" in message:
                break
        if index < len(docs):
            time.sleep(15)

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_count = sum(1 for row in report if row.get("ok"))
    print({"ok": ok_count, "total_attempted": len(report), "report": str(REPORT_PATH.relative_to(PROJECT_ROOT))})
    return 0 if ok_count == len(docs) else 1


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DIFY_DATASET_API_KEY}",
        "Content-Type": "application/json",
    }


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
