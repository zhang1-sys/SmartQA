from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from config import CUSTOMER_ACCESS_TOKEN_SECRET


TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


def issue_customer_token(*, session_id: str, conversation_id: str, channel: str = "web_customer") -> str:
    payload = {
        "session_id": session_id,
        "conversation_id": str(conversation_id),
        "channel": channel,
        "iat": int(time.time()),
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)
    signature = _sign(payload_b64)
    return f"{payload_b64}.{signature}"


def verify_customer_token(
    token: str,
    *,
    session_id: str | None = None,
    conversation_id: str | None = None,
    channel: str = "web_customer",
) -> tuple[dict[str, Any] | None, str | None]:
    if not token or "." not in token:
        return None, "missing customer token"
    payload_b64, signature = token.rsplit(".", 1)
    expected = _sign(payload_b64)
    if not hmac.compare_digest(signature, expected):
        return None, "invalid customer token"
    try:
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None, "invalid customer token payload"
    if payload.get("channel") != channel:
        return None, "customer token channel mismatch"
    if session_id and payload.get("session_id") != session_id:
        return None, "customer token session mismatch"
    if conversation_id and str(payload.get("conversation_id")) != str(conversation_id):
        return None, "customer token conversation mismatch"
    issued_at = int(payload.get("iat") or 0)
    if not issued_at or int(time.time()) - issued_at > TOKEN_TTL_SECONDS:
        return None, "customer token expired"
    return payload, None


def _sign(payload_b64: str) -> str:
    digest = hmac.new(
        CUSTOMER_ACCESS_TOKEN_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64_encode(digest)


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
