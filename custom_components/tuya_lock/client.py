from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from typing import Any

import requests


class TuyaError(Exception):
    pass


class TuyaClient:
    def __init__(self, endpoint: str, access_id: str, access_secret: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_id = access_id
        self.access_secret = access_secret
        self.access_token = ""
        self.token_expires = 0.0

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode(sorted((params or {}).items()), doseq=True)
        request_path = path + (f"?{query}" if query else "")
        timestamp = str(int(time.time() * 1000))
        body_hash = hashlib.sha256(b"").hexdigest()
        to_sign = f"{method.upper()}\n{body_hash}\n\n{request_path}"
        message = self.access_id + self.access_token + timestamp + to_sign
        sign = hmac.new(self.access_secret.encode(), message.encode(), hashlib.sha256).hexdigest().upper()
        headers = {
            "client_id": self.access_id,
            "t": timestamp,
            "sign_method": "HMAC-SHA256",
            "sign": sign,
            "lang": "en",
        }
        if self.access_token:
            headers["access_token"] = self.access_token
        try:
            response = requests.get(self.endpoint + request_path, headers=headers, timeout=20)
            data = response.json()
        except (requests.RequestException, ValueError) as err:
            raise TuyaError(str(err)) from err
        if response.ok and data.get("success") is True:
            return data
        raise TuyaError(data.get("msg", f"Tuya HTTP {response.status_code}"))

    def authenticate(self) -> None:
        result = self._request("GET", "/v1.0/token", {"grant_type": 1})
        token = result.get("result", {}).get("access_token")
        if not token:
            raise TuyaError("Tuya did not return an access token")
        self.access_token = token
        self.token_expires = time.time() + float(result.get("result", {}).get("expire_time", 7200)) - 60

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.access_token or time.time() >= self.token_expires:
            self.authenticate()
        try:
            return self._request("GET", path, params)
        except TuyaError as err:
            if "token" in str(err).lower() or "sign" in str(err).lower():
                self.authenticate()
                return self._request("GET", path, params)
            raise

