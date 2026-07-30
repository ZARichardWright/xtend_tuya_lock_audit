from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from urllib.parse import urlencode
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class TuyaError(Exception):
    pass


class TuyaClient:
    def __init__(self, endpoint: str, access_id: str, access_secret: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.access_id = access_id
        self.access_secret = access_secret
        self.access_token = ""
        self.token_expires = 0.0
        self.uid = ""
        self._request_lock = threading.RLock()

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode(sorted((params or {}).items()), doseq=True)
        request_path = path + (f"?{query}" if query else "")
        timestamp = str(int(time.time() * 1000))
        body_bytes = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        body_hash = hashlib.sha256(body_bytes).hexdigest()
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
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.access_token:
            headers["access_token"] = self.access_token
        LOGGER.debug("Tuya request: %s %s", method.upper(), request_path)
        try:
            response = requests.request(method.upper(), self.endpoint + request_path, headers=headers, data=body_bytes if body is not None else None, timeout=20)
            data = response.json()
        except (requests.RequestException, ValueError) as err:
            raise TuyaError(str(err)) from err
        if response.ok and data.get("success") is True:
            LOGGER.debug(
                "Tuya request succeeded: %s %s (HTTP %s)",
                method.upper(),
                path,
                response.status_code,
            )
            return data
        LOGGER.warning(
            "Tuya request failed: %s %s (HTTP %s, code=%s, message=%s)",
            method.upper(),
            path,
            response.status_code,
            data.get("code"),
            data.get("msg"),
        )
        raise TuyaError(data.get("msg", f"Tuya HTTP {response.status_code}"))

    def authenticate(self) -> None:
        with self._request_lock:
            LOGGER.debug("Authenticating with Tuya endpoint %s", self.endpoint)
            previous_token = self.access_token
            self.access_token = ""
            try:
                result = self._request(
                    "GET",
                    "/v1.0/token",
                    {"grant_type": 1},
                )
            except TuyaError:
                self.access_token = previous_token
                raise
            token_data = result.get("result", {})
            token = token_data.get("access_token")
            if not token:
                raise TuyaError("Tuya did not return an access token")
            self.access_token = token
            self.uid = str(token_data.get("uid", ""))
            self.token_expires = time.time() + float(token_data.get("expire_time", 7200)) - 60
            LOGGER.debug("Tuya authentication succeeded")

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._request_lock:
            if not self.access_token or time.time() >= self.token_expires:
                self.authenticate()
            try:
                return self._request("GET", path, params)
            except TuyaError as err:
                if "token" in str(err).lower() or "sign" in str(err).lower():
                    self.authenticate()
                    return self._request("GET", path, params)
                raise

    def post(
        self, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._request_lock:
            if not self.access_token or time.time() >= self.token_expires:
                self.authenticate()
            return self._request("POST", path, body=body)

    def delete(self, path: str) -> dict[str, Any]:
        with self._request_lock:
            if not self.access_token or time.time() >= self.token_expires:
                self.authenticate()
            return self._request("DELETE", path)
