from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402
from supabase_client import supabase  # noqa: E402
from wecom_client import wecom_client  # noqa: E402


def _present(value: str) -> bool:
    return bool(str(value or "").strip())


def _check(name: str, ok: bool, severity: str, detail: str) -> dict:
    return {"name": name, "ok": ok, "severity": severity, "detail": detail}


def main() -> int:
    checks = [
        _check("APP_ENV", config.APP_ENV in {"staging", "production"}, "warning", f"当前为 {config.APP_ENV}；生产建议使用 production 或 staging。"),
        _check("FLASK_DEBUG", not config.FLASK_DEBUG, "critical", "生产必须关闭 Flask debug。"),
        _check("Supabase service role", config.SUPABASE_ENABLED, "critical", "生产数据层必须启用 Supabase。"),
        _check("Supabase anon key", _present(config.SUPABASE_ANON_KEY), "critical", "内部登录需要 Supabase anon key。"),
        _check("Internal auth", config.INTERNAL_AUTH_REQUIRED, "critical", "内部工作台 API 必须开启登录保护。"),
        _check("Customer token secret", _present(config.CUSTOMER_ACCESS_TOKEN_SECRET) and config.CUSTOMER_ACCESS_TOKEN_SECRET != "smartqa-local-customer-token", "warning", "客户网页入口 token 需要独立长随机密钥。"),
        _check("Dify workflow", config.DIFY_ENABLED and not config.MOCK_AI_ENABLED, "critical", "生产必须使用 Dify，不应使用本地降级 AI。"),
        _check("Dify dataset", _present(config.DIFY_DATASET_ID) and _present(config.DIFY_DATASET_API_KEY), "warning", "知识库同步需要 Dataset ID 和 Dataset API Key。"),
        _check("WeCom callback URL", config.WECOM_PUBLIC_BASE_URL.startswith("https://"), "critical", "企业微信生产回调必须是稳定 HTTPS 域名。"),
        _check("WeCom app", config.WECOM_ENABLED, "critical", "企业微信自建应用配置必须完整。"),
        _check("WeCom customer service", config.WECOM_KF_ENABLED and _present(config.WECOM_KF_OPEN_KFID), "critical", "微信客服 open_kfid 和 Secret 必须完整。"),
        _check("WeCom encryption", _present(config.WECOM_ENCODING_AES_KEY), "critical", "企业微信回调必须启用 EncodingAESKey。"),
        _check("WeCom poll interval", config.WECOM_KF_POLL_INTERVAL_SECONDS >= 15, "warning", "轮询兜底间隔建议 >=15 秒，避免频率限制。"),
    ]

    try:
        supabase_health = supabase.health()
        checks.append(_check("Supabase health", bool(supabase_health.get("ok")), "critical", supabase_health.get("reason") or "Supabase REST 可访问。"))
    except Exception as exc:
        checks.append(_check("Supabase health", False, "critical", str(exc)))

    try:
        wecom_health = wecom_client.health() if config.WECOM_ENABLED else {"ok": False, "reason": "WeCom not enabled"}
        checks.append(_check("WeCom token health", bool(wecom_health.get("ok")), "warning", wecom_health.get("reason") or "企业微信 token 可获取。"))
    except Exception as exc:
        checks.append(_check("WeCom token health", False, "warning", str(exc)))

    checks.append(_check(
        "Azure Speech",
        _present(config.AZURE_SPEECH_REGION) and _present(config.AZURE_SPEECH_KEY),
        "warning",
        "Audio transcription requires AZURE_SPEECH_REGION and AZURE_SPEECH_KEY.",
    ))

    critical_failed = [item for item in checks if item["severity"] == "critical" and not item["ok"]]
    warning_failed = [item for item in checks if item["severity"] == "warning" and not item["ok"]]
    result = {
        "ok": not critical_failed,
        "critical_failed": len(critical_failed),
        "warning_failed": len(warning_failed),
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if critical_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
