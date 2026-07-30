from __future__ import annotations

import logging
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import TuyaClient, TuyaError
from .const import LOCK_CATEGORIES

LOGGER = logging.getLogger(__name__)


class LockCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, endpoint: str, access_id: str, access_secret: str, device_id: str = "") -> None:
        self.entry_id = ""
        self.mapping: dict[str, str] = {}
        self.client = TuyaClient(endpoint, access_id, access_secret)
        self.requested_device_id = device_id
        self.devices: dict[str, dict[str, Any]] = {}
        super().__init__(hass, logging.getLogger(__name__), name="tuya_lock_audit", update_interval=timedelta(seconds=60))

    async def _async_update_data(self) -> dict[str, Any]:
        LOGGER.debug("Starting Tuya lock coordinator refresh")
        try:
            data = await self.hass.async_add_executor_job(self._update_sync)
            LOGGER.debug(
                "Coordinator refresh completed with %d device(s) and %d audit record(s)",
                len(data.get("devices", {})),
                len(data.get("logs", [])),
            )
            return data
        except TuyaError as err:
            LOGGER.error("Tuya lock coordinator refresh failed: %s", err)
            raise UpdateFailed(str(err)) from err

    def _update_sync(self) -> dict[str, Any]:
        try:
            mapping = self._load_mapping()
            device_ids = [self.requested_device_id] if self.requested_device_id else self._discover_ids()
            LOGGER.debug("Refreshing lock device IDs: %s", device_ids)
            result: dict[str, Any] = {"devices": {}, "logs": []}
            end = int(dt_util.utcnow().timestamp() * 1000)
            start = end - 30 * 24 * 60 * 60 * 1000
            for device_id in device_ids:
                device = self.devices.get(device_id)
                if device is None or device.get("name") in (None, "", device_id):
                    device_info = self.client.get(f"/v1.0/devices/{device_id}").get(
                        "result", {}
                    )
                    device = {
                        "id": device_id,
                        "name": device_info.get("name") or device_id,
                        "category": device_info.get("category"),
                        "product_name": device_info.get("product_name"),
                    }
                    self.devices[device_id] = device
                    LOGGER.info(
                        "Loaded Tuya device metadata for %s: name=%s, category=%s, product=%s",
                        device_id,
                        device["name"],
                        device.get("category"),
                        device.get("product_name"),
                    )
                status_rows = self.client.get(f"/v1.0/iot-03/devices/{device_id}/status").get("result", [])
                status = {str(row.get("code")): row.get("value") for row in status_rows if isinstance(row, dict)}
                LOGGER.debug(
                    "Device %s returned status codes: %s",
                    device_id,
                    sorted(status),
                )
                logs = self.client.get(
                    f"/v1.1/devices/{device_id}/door-lock/open-logs",
                    {"page_no": 1, "page_size": 100, "start_time": start, "end_time": end},
                ).get("result", {}).get("logs", [])
                device["status"] = status
                result["devices"][device_id] = device
                LOGGER.debug(
                    "Device %s (%s) returned %d audit record(s)",
                    device_id,
                    device.get("name", device_id),
                    len(logs) if isinstance(logs, list) else 0,
                )
                for record in logs if isinstance(logs, list) else []:
                    item = dict(record)
                    item["device_id"] = device_id
                    item["device_name"] = device["name"]
                    result["logs"].append(item)
                    status = item.get("status") or {}
                    if status.get("code") == "unlock_fingerprint_kit" and status.get("value") not in (None, ""):
                        slot = str(status["value"])
                        mapping.setdefault(slot, f"Fingerprint slot {slot}")
            result["logs"].sort(key=lambda item: item.get("update_time", 0), reverse=True)
            self.mapping = mapping
            self._save_mapping(mapping)
            return result
        except TuyaError:
            raise

    def _discover_ids(self) -> list[str]:
        token = self.client.get("/v1.0/token", {"grant_type": 1}).get("result", {})
        self.client.access_token = token.get("access_token", "")
        self.client.token_expires = __import__("time").time() + float(token.get("expire_time", 7200)) - 60
        uid = token.get("uid")
        if not uid:
            raise TuyaError("Tuya token response did not contain a user ID")
        devices = self.client.get(f"/v1.0/users/{uid}/devices").get("result", [])
        LOGGER.debug(
            "Tuya account returned %d total device(s)",
            len(devices) if isinstance(devices, list) else 0,
        )
        lock_ids: list[str] = []
        for item in devices if isinstance(devices, list) else []:
            device_id = item.get("id")
            if not device_id:
                continue
            if str(item.get("category", "")).lower() not in LOCK_CATEGORIES:
                LOGGER.debug(
                    "Skipping device %s (%s): category %s is not a lock category",
                    device_id,
                    item.get("name", device_id),
                    item.get("category"),
                )
                continue
            status = self.client.get(f"/v1.0/iot-03/devices/{device_id}/status").get("result", [])
            codes = {str(row.get("code", "")) for row in status if isinstance(row, dict)}
            if any(code.startswith("unlock_") for code in codes):
                self.devices[device_id] = {"id": device_id, "name": item.get("name") or device_id}
                lock_ids.append(device_id)
                LOGGER.info(
                    "Discovered Tuya lock %s (%s), category=%s, status_codes=%s",
                    item.get("name") or device_id,
                    device_id,
                    item.get("category"),
                    sorted(codes),
                )
            else:
                LOGGER.debug(
                    "Skipping category-matched device %s: no unlock_* status codes (%s)",
                    device_id,
                    sorted(codes),
                )
        LOGGER.info("Tuya lock discovery selected %d device(s)", len(lock_ids))
        return lock_ids

    def _mapping_path(self) -> Path:
        return Path(self.hass.config.path("tuya_lock", "fingerprint_map.json"))

    def _load_mapping(self) -> dict[str, str]:
        try:
            data = json.loads(self._mapping_path().read_text())
            slots = data.get("slots", data) if isinstance(data, dict) else {}
            return {str(key): str(value) for key, value in slots.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_mapping(self, mapping: dict[str, str]) -> None:
        path = self._mapping_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slots": dict(sorted(mapping.items()))}, indent=2) + "\n")
