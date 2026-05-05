from __future__ import annotations

import time
from typing import Any

import requests

from config import WECOM_AGENT_ID, WECOM_CORP_ID, WECOM_KF_SECRET, WECOM_SECRET


class WeComClient:
    def __init__(self):
        self._access_token = ""
        self._expires_at = 0.0
        self.session = requests.Session()
        self.session.trust_env = False

    def enabled(self) -> bool:
        return bool(WECOM_CORP_ID and WECOM_SECRET and WECOM_AGENT_ID)

    def health(self) -> dict[str, Any]:
        if not self.enabled():
            return {"enabled": False, "ok": False, "reason": "WeCom is not configured"}
        try:
            token = self.get_access_token()
            return {"enabled": True, "ok": bool(token)}
        except Exception as exc:
            return {"enabled": True, "ok": False, "reason": _redact_secret(str(exc))}

    def get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._expires_at - 60:
            return self._access_token
        try:
            response = self.session.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": WECOM_CORP_ID, "corpsecret": WECOM_SECRET},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"WeCom gettoken request failed: {_redact_secret(str(exc))}") from exc
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom gettoken failed: {data}")
        self._access_token = data["access_token"]
        self._expires_at = now + int(data.get("expires_in", 7200))
        return self._access_token

    def send_text(self, user_id: str, content: str) -> dict[str, Any]:
        token = self.get_access_token()
        try:
            response = self.session.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": int(WECOM_AGENT_ID),
                    "text": {"content": content},
                    "safe": 0,
                    "enable_id_trans": 0,
                    "enable_duplicate_check": 1,
                    "duplicate_check_interval": 1800,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"WeCom send_text request failed: {_redact_secret(str(exc))}") from exc
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom send_text failed: {data}")
        return data

    def send_text_to_users(self, user_ids: list[str], content: str) -> dict[str, Any]:
        targets = [item.strip() for item in user_ids if item and item.strip()]
        if not targets:
            return {"errcode": 0, "errmsg": "no recipients"}
        return self.send_text("|".join(targets), content)

    def customer_service_enabled(self) -> bool:
        return bool(WECOM_CORP_ID and (WECOM_KF_SECRET or WECOM_SECRET))

    def get_customer_service_access_token(self) -> str:
        return self._get_access_token_for_secret(WECOM_KF_SECRET or WECOM_SECRET)

    def sync_customer_service_messages(
        self,
        *,
        cursor: str = "",
        token: str = "",
        limit: int = 1000,
        voice_format: int = 0,
        open_kfid: str = "",
    ) -> dict[str, Any]:
        access_token = self.get_customer_service_access_token()
        payload: dict[str, Any] = {
            "cursor": cursor,
            "token": token,
            "limit": limit,
            "voice_format": voice_format,
        }
        if open_kfid:
            payload["open_kfid"] = open_kfid
        try:
            response = self.session.post(
                "https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg",
                params={"access_token": access_token},
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"WeCom KF sync_msg request failed: {_redact_secret(str(exc))}") from exc
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom KF sync_msg failed: {_redact_secret(str(data))}")
        return data

    def send_customer_service_text(self, *, open_kfid: str, external_userid: str, content: str) -> dict[str, Any]:
        access_token = self.get_customer_service_access_token()
        try:
            response = self.session.post(
                "https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg",
                params={"access_token": access_token},
                json={
                    "touser": external_userid,
                    "open_kfid": open_kfid,
                    "msgtype": "text",
                    "text": {"content": content},
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"WeCom KF send_msg request failed: {_redact_secret(str(exc))}") from exc
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom KF send_msg failed: {_redact_secret(str(data))}")
        return data

    def _get_access_token_for_secret(self, secret: str) -> str:
        now = time.time()
        cache_key = f"_access_token_{secret[:6]}"
        expires_key = f"_expires_at_{secret[:6]}"
        cached_token = getattr(self, cache_key, "")
        expires_at = getattr(self, expires_key, 0.0)
        if cached_token and now < expires_at - 60:
            return cached_token
        try:
            response = self.session.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": WECOM_CORP_ID, "corpsecret": secret},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"WeCom gettoken request failed: {_redact_secret(str(exc))}") from exc
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom gettoken failed: {_redact_secret(str(data))}")
        setattr(self, cache_key, data["access_token"])
        setattr(self, expires_key, now + int(data.get("expires_in", 7200)))
        return data["access_token"]


def _redact_secret(value: str) -> str:
    redacted = value
    for secret in (WECOM_SECRET, WECOM_KF_SECRET):
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


wecom_client = WeComClient()
