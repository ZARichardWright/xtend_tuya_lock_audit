from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import TuyaClient, TuyaError


class LockCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, endpoint: str, access_id: str, access_secret: str, device_id: str = "") -> None:
        self.entry_id = ""
        self.mapping: dict[str, str] = {}
        self.client = TuyaClient(endpoint, access_id, access_secret)
        self.requested_device_id = device_id
        self.devices: dict[str, dict[str, Any]] = {}
        super().__init__(hass, logging.getLogger(__name__), name="tuya_lock_audit", update_interval=timedelta(seconds=60))

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            device_ids = [self.requested_device_id] if self.requested_device_id else await self._discover_ids()
            result: dict[str, Any] = {"devices": {}, "logs": []}
            end = int(dt_util.utcnow().timestamp() * 1000)
            start = end - 30 * 24 * 60 * 60 * 1000
            for device_id in device_ids:
                logs = self.client.get(
                    f"/v1.1/devices/{device_id}/door-lock/open-logs",
                    {"page_no": 1, "page_size": 100, "start_time": start, "end_time": end},
                ).get("result", {}).get("logs", [])
                device = self.devices.setdefault(device_id, {"id": device_id, "name": device_id})
                result["devices"][device_id] = device
                for record in logs if isinstance(logs, list) else []:
                    item = dict(record)
                    item["device_id"] = device_id
                    item["device_name"] = device["name"]
                    result["logs"].append(item)
            result["logs"].sort(key=lambda item: item.get("update_time", 0), reverse=True)
            return result
        except TuyaError as err:
            raise UpdateFailed(str(err)) from err

    async def _discover_ids(self) -> list[str]:
        token = self.client.get("/v1.0/token", {"grant_type": 1}).get("result", {})
        self.client.access_token = token.get("access_token", "")
        self.client.token_expires = __import__("time").time() + float(token.get("expire_time", 7200)) - 60
        uid = token.get("uid")
        if not uid:
            raise TuyaError("Tuya token response did not contain a user ID")
        devices = self.client.get(f"/v1.0/users/{uid}/devices").get("result", [])
        lock_ids: list[str] = []
        for item in devices if isinstance(devices, list) else []:
            device_id = item.get("id")
            if not device_id:
                continue
            status = self.client.get(f"/v1.0/iot-03/devices/{device_id}/status").get("result", [])
            codes = {str(row.get("code", "")) for row in status if isinstance(row, dict)}
            if any(code.startswith("unlock_") for code in codes):
                self.devices[device_id] = {"id": device_id, "name": item.get("name") or device_id}
                lock_ids.append(device_id)
        return lock_ids
