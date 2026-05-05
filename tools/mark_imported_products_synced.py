from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import DIFY_DATASET_ID
from services.repository import get_repository


def main():
    repo = get_repository()
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for item in repo.list_knowledge_items(item_type="product"):
        if item.get("sync_status") != "pending":
            continue
        repo.mark_knowledge_sync(
            item["id"],
            sync_status="synced",
            dify_dataset_id=DIFY_DATASET_ID,
            dify_document_id=item.get("dify_document_id"),
            last_sync_error=None,
            last_synced_at=now,
        )
        updated += 1
    print(f"products marked synced: {updated}")


if __name__ == "__main__":
    main()
