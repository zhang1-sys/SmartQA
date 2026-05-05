from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    checks = [
        ("py_compile", [sys.executable, "-m", "py_compile",
            "backend/app.py",
            "backend/services/ai_orchestration_service.py",
            "backend/services/customer_memory_service.py",
            "backend/services/supabase_repository.py",
            "backend/wecom_kf_gateway.py",
            "backend/wecom_kf_poller.py",
        ]),
        ("auth_smoke", [sys.executable, "backend/tests/smoke_internal_auth.py"]),
    ]

    failed = False
    for name, command in checks:
        print(f"[{name}] running")
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            print(f"[{name}] failed: exit {result.returncode}")
            failed = True
        else:
            print(f"[{name}] ok")

    health_ok = check_http_health()
    if not health_ok:
        failed = True

    return 1 if failed else 0


def check_http_health() -> bool:
    url = "http://127.0.0.1:5001/api/system/health"
    print("[system_health] running")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[system_health] failed: {exc}")
        return False

    required = [
        ("ok", body.get("ok") is True),
        ("supabase.ok", (body.get("supabase") or {}).get("ok") is True),
        ("config.internal_auth_required", (body.get("config") or {}).get("internal_auth_required") is True),
        ("config.mock_ai_enabled_false", (body.get("config") or {}).get("mock_ai_enabled") is False),
    ]
    for label, passed in required:
        print(f"[system_health] {label}: {'ok' if passed else 'failed'}")
    return all(passed for _, passed in required)


if __name__ == "__main__":
    raise SystemExit(main())
