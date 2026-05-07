from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGRESSION_PATH = PROJECT_ROOT / "dify-workflow" / "regression-questions.json"
REQUIRED_CATEGORIES = {
    "product",
    "construction",
    "store_contact",
    "logistics",
    "price",
    "invoice_payment",
    "aftersales",
    "refund",
    "complaint",
    "unknown_knowledge",
}


def main() -> int:
    cases = json.loads(REGRESSION_PATH.read_text(encoding="utf-8"))
    failures = []
    ids = [case.get("id") for case in cases]
    if len(cases) < 20:
        failures.append(f"expected at least 20 cases, found {len(cases)}")
    duplicate_ids = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicate_ids:
        failures.append(f"duplicate ids: {duplicate_ids}")
    categories = {case.get("category") for case in cases}
    missing_categories = sorted(REQUIRED_CATEGORIES - categories)
    if missing_categories:
        failures.append(f"missing categories: {missing_categories}")
    smoke_count = len([case for case in cases if case.get("smoke")])
    if smoke_count < 5:
        failures.append(f"expected at least 5 smoke cases, found {smoke_count}")
    for case in cases:
        for field in ["id", "category", "message", "expected_action", "expected_risk", "required_terms"]:
            if field not in case:
                failures.append(f"{case.get('id', '<missing-id>')} missing {field}")
        if not isinstance(case.get("expected_action"), list) or not case.get("expected_action"):
            failures.append(f"{case.get('id')} expected_action must be a non-empty list")
        if not isinstance(case.get("expected_risk"), list) or not case.get("expected_risk"):
            failures.append(f"{case.get('id')} expected_risk must be a non-empty list")
        if not isinstance(case.get("required_terms"), list):
            failures.append(f"{case.get('id')} required_terms must be a list")

    result = {
        "ok": not failures,
        "cases": len(cases),
        "smoke_cases": smoke_count,
        "categories": sorted(categories),
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
