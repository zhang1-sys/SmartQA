from __future__ import annotations

import re
from typing import Any


PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
ORDER_RE = re.compile(r"(?i)\b(order|订单|单号)[:：\s-]*([A-Z0-9-]{6,})")


def mask_sensitive_text(text: str, *, show_last_digits: int = 4) -> str:
    value = str(text or "")

    def phone_mask(match: re.Match) -> str:
        phone = match.group(1)
        return phone[:3] + "****" + phone[-show_last_digits:]

    value = PHONE_RE.sub(phone_mask, value)
    value = EMAIL_RE.sub(lambda m: m.group(1) + "***" + m.group(2), value)
    value = ORDER_RE.sub(lambda m: f"{m.group(1)}：***{m.group(2)[-4:]}", value)
    return value


def mask_json(value: Any) -> Any:
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if isinstance(value, list):
        return [mask_json(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_json(item) for key, item in value.items()}
    return value
