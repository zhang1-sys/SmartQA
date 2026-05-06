from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "dify-workflow" / "aggregate-docs"
REPORT_PATH = DOCS_DIR / "import-report.json"


def main() -> int:
    docs = sorted(path for path in DOCS_DIR.glob("*.md") if path.name[:2].isdigit())
    failures: list[str] = []
    if len(docs) < 6:
        failures.append(f"expected at least 6 aggregate docs, found {len(docs)}")
    for path in docs:
        text = path.read_text(encoding="utf-8")
        if "## 使用边界" not in text:
            failures.append(f"{path.name} missing usage boundary")
        if "检索关键词" not in text:
            failures.append(f"{path.name} missing retrieval keywords")
        if "客户常见问法" not in text:
            failures.append(f"{path.name} missing customer question variants")
        if len(text) < 800:
            failures.append(f"{path.name} is too small for high-quality retrieval")

    if not REPORT_PATH.exists():
        failures.append("import-report.json missing")
    else:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        ok_rows = [row for row in report if row.get("ok")]
        if len(ok_rows) < len(docs):
            failures.append(f"Dify import report only has {len(ok_rows)}/{len(docs)} successful rows")
        missing_ids = [row.get("file") for row in ok_rows if not row.get("document_id")]
        if missing_ids:
            failures.append(f"Dify import report rows missing document_id: {missing_ids}")

    result = {
        "ok": not failures,
        "documents": len(docs),
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
