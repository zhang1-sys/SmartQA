from __future__ import annotations

from typing import Any

import requests
from flask import Request

from config import INTERNAL_AUTH_REQUIRED, SUPABASE_ANON_KEY, SUPABASE_HTTPS_PROXY, SUPABASE_HTTP_PROXY, SUPABASE_URL


PUBLIC_API_PATHS = {
    "/api/system/health",
    "/api/auth/session",
    "/api/customer/register",
    "/api/customer/history",
}


def api_auth_required(path: str) -> bool:
    if not INTERNAL_AUTH_REQUIRED:
        return False
    if not path.startswith("/api/"):
        return False
    return path not in PUBLIC_API_PATHS


def is_public_customer_chat(request: Request) -> bool:
    if request.path != "/api/chat" or request.method != "POST":
        return False
    data = request.get_json(silent=True) or {}
    return data.get("channel") == "web_customer" or data.get("source") == "customer"


def verify_request(request: Request) -> tuple[dict[str, Any] | None, str | None]:
    token = _bearer_token(request)
    if not token:
        return None, "missing bearer token"
    if not SUPABASE_URL:
        return None, "SUPABASE_URL is not configured"
    try:
        session = requests.Session()
        session.trust_env = False
        proxies = {
            key: value
            for key, value in {
                "http": SUPABASE_HTTP_PROXY,
                "https": SUPABASE_HTTPS_PROXY or SUPABASE_HTTP_PROXY,
            }.items()
            if value
        }
        response = session.get(
            f"{SUPABASE_URL.rstrip('/')}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            proxies=proxies,
            timeout=20,
        )
    except requests.RequestException as exc:
        return None, f"auth verification failed: {exc}"
    if not response.ok:
        return None, f"invalid token: {response.status_code}"
    user = response.json()
    return user, None


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return ""
