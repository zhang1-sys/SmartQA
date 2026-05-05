from __future__ import annotations

import time
from typing import Any

import requests

from config import (
    SUPABASE_ENABLED,
    SUPABASE_HTTP_PROXY,
    SUPABASE_HTTPS_PROXY,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)


class SupabaseError(RuntimeError):
    pass


class SupabaseRestClient:
    def __init__(self, url: str, service_role_key: str):
        self.url = url.rstrip("/")
        self.rest_url = f"{self.url}/rest/v1"
        self.session = requests.Session()
        self.session.trust_env = False
        self.proxies = {
            key: value
            for key, value in {
                "http": SUPABASE_HTTP_PROXY,
                "https": SUPABASE_HTTPS_PROXY or SUPABASE_HTTP_PROXY,
            }.items()
            if value
        }
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.timeout = (10, 45)

    def enabled(self) -> bool:
        return bool(self.url and self.headers["apikey"])

    def select(self, table: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"{self.rest_url}/{table}",
            params=params or {},
        )
        return self._json(response)

    def insert(self, table: str, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"{self.rest_url}/{table}",
            json=payload,
        )
        return self._json(response)

    def update(self, table: str, filters: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request(
            "PATCH",
            f"{self.rest_url}/{table}",
            params=filters,
            json=payload,
        )
        return self._json(response)

    def upsert(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        params = {"on_conflict": on_conflict} if on_conflict else {}
        response = self._request(
            "POST",
            f"{self.rest_url}/{table}",
            headers=headers,
            params=params,
            json=payload,
        )
        return self._json(response)

    def rpc(self, function_name: str, payload: dict[str, Any] | None = None) -> Any:
        response = self._request(
            "POST",
            f"{self.url}/rest/v1/rpc/{function_name}",
            json=payload or {},
        )
        return self._json(response)

    def health(self) -> dict[str, Any]:
        if not self.enabled():
            return {"enabled": False, "ok": False, "reason": "Supabase is not configured"}
        try:
            self.select("conversations", {"select": "id", "limit": "1"})
            return {"enabled": True, "ok": True}
        except Exception as exc:
            return {"enabled": True, "ok": False, "reason": str(exc)}

    def _json(self, response: requests.Response) -> Any:
        if not response.ok:
            raise SupabaseError(f"Supabase {response.status_code}: {response.text}")
        if not response.content:
            return []
        return response.json()

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        headers = kwargs.pop("headers", self.headers)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self.session.request(
                    method,
                    url,
                    headers=headers,
                    proxies=self.proxies,
                    timeout=self.timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
                self.session.close()
                self.session = requests.Session()
                self.session.trust_env = False
                if attempt < 2:
                    time.sleep(1 + attempt)
        raise SupabaseError(f"Supabase request failed after retries: {last_error}")


supabase = SupabaseRestClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def is_supabase_enabled() -> bool:
    return SUPABASE_ENABLED and supabase.enabled()
