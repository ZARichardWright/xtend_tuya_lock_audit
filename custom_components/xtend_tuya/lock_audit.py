"""Lock audit entities backed by Tuya's lock open-log API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER
from .multi_manager.shared.shared_classes import XTConfigEntry

AUDIT_WINDOW_DAYS = 30
AUDIT_LIMIT = 100
AUDIT_REFRESH = timedelta(seconds=60)
AUDIT_MAP_FILENAME = "fingerprint_map.json"


def _slot_map_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN, AUDIT_MAP_FILENAME))


def _load_slot_map(hass: HomeAssistant) -> dict[str, str]:
    path = _slot_map_path(hass)
    try:
        return {str(k): str(v) for k, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError, TypeError):
        return {}


def _save_slot_map(hass: HomeAssistant, mapping: dict[str, str]) -> None:
    path = _slot_map_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(mapping.items())), indent=2) + "\n")


def _method(code: str) -> str:
    names = {
        "unlock_fingerprint_kit": "Fingerprint",
        "unlock_temporary_kit": "Temporary PIN",
        "unlock_phone_remote_kit": "Phone / remote",
        "unlock_password_kit": "Password",
        "unlock_card_kit": "Card",
        "unlock_face_kit": "Face",
        "unlock_key": "Key",
    }
    return names.get(code, code.replace("unlock_", "").replace("_kit", "").replace("_", " ").title())


def _normalise(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    status = raw.get("status") or {}
    code = str(status.get("code", "unknown"))
    value = status.get("value")
    slot = str(value) if code == "unlock_fingerprint_kit" and value not in (None, "") else ""
    if slot and slot not in mapping:
        mapping[slot] = ""
    timestamp = raw.get("update_time")
    if isinstance(timestamp, str) and timestamp.isdigit():
        timestamp = int(timestamp)
    if isinstance(timestamp, (int, float)):
        timestamp = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
        when = datetime.fromtimestamp(timestamp, dt_util.DEFAULT_TIME_ZONE)
    else:
        when = None
    return {
        "time": when.isoformat() if when else "",
        "timestamp": timestamp,
        "method": _method(code),
        "method_code": code,
        "slot": slot,
        "slot_name": mapping.get(slot, "") if slot else "",
        "user": raw.get("nick_name") or raw.get("unlock_name") or "",
        "user_id": raw.get("user_id", ""),
        "value": value,
    }


class LockAuditCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Poll lock open logs through Xtend's already-authenticated API."""

    def __init__(self, hass: HomeAssistant, entry: XTConfigEntry) -> None:
        self.entry = entry
        self.multi_manager = entry.runtime_data.multi_manager
        self.mapping = _load_slot_map(hass)
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_lock_audit_{entry.entry_id}",
            update_interval=AUDIT_REFRESH,
        )

    async def _async_update_data(self) -> list[dict[str, Any]]:
        if self.multi_manager is None:
            raise UpdateFailed("Xtend Tuya manager is not ready")
        account = self.multi_manager.get_account_by_name("tuya_iot")
        if account is None or account.iot_account is None:
            raise UpdateFailed("Tuya cloud API is not configured")

        end = dt_util.utcnow()
        start = end - timedelta(days=AUDIT_WINDOW_DAYS)
        params = {
            "page_no": 1,
            "page_size": AUDIT_LIMIT,
            "start_time": int(start.timestamp() * 1000),
            "end_time": int(end.timestamp() * 1000),
        }

        async def fetch(device_id: str) -> dict[str, Any]:
            api = account.iot_account.device_manager.api
            return await self.hass.async_add_executor_job(
                api.get, f"/v1.1/devices/{device_id}/door-lock/open-logs", params
            )

        records: list[dict[str, Any]] = []
        for device in self.multi_manager.device_map.values():
            if not any(str(code).startswith("unlock_") for code in device.status):
                continue
            response = await fetch(device.id)
            if response.get("success") is False:
                raise UpdateFailed(response.get("msg", "Tuya lock audit request failed"))
            result = response.get("result") or {}
            for raw in result.get("logs", []) if isinstance(result, dict) else []:
                record = _normalise(raw, self.mapping)
                record["device_id"] = device.id
                record["device_name"] = device.name
                records.append(record)
        _save_slot_map(self.hass, self.mapping)
        records.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
        return records[:AUDIT_LIMIT]


class LockAuditSensor(CoordinatorEntity[LockAuditCoordinator], SensorEntity):
    """A compact latest-audit sensor with the full record in attributes."""

    _attr_should_poll = False

    def __init__(self, coordinator: LockAuditCoordinator, device: Any, kind: str) -> None:
        super().__init__(coordinator)
        self.device = device
        self.kind = kind
        self._attr_unique_id = f"{device.id}_lock_audit_{kind}"
        self._attr_name = f"{device.name} Last Unlock {kind.replace('_', ' ').title()}"
        self._attr_icon = "mdi:lock-clock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)}, name=device.name, manufacturer="Tuya"
        )

    @property
    def native_value(self) -> Any:
        record = self._record
        if not record:
            return None
        if self.kind == "time":
            return record.get("time")
        if self.kind == "count":
            return len(self._device_records)
        return record.get(self.kind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"record": self._record, "records": self._device_records[:20]}

    @property
    def _device_records(self) -> list[dict[str, Any]]:
        return [r for r in (self.coordinator.data or []) if r.get("device_id") == self.device.id]

    @property
    def _record(self) -> dict[str, Any] | None:
        records = self._device_records
        return records[0] if records else None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create richer lock audit sensors for lock devices."""
    if entry.runtime_data is None or entry.runtime_data.multi_manager is None:
        return
    coordinator = hass.data.setdefault(DOMAIN, {}).get(f"audit_{entry.entry_id}")
    if coordinator is None:
        coordinator = LockAuditCoordinator(hass, entry)
        hass.data[DOMAIN][f"audit_{entry.entry_id}"] = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as err:
        LOGGER.warning("Lock audit unavailable: %s", err)
    entities: list[LockAuditSensor] = []
    for device in entry.runtime_data.multi_manager.device_map.values():
        if not any(str(code).startswith("unlock_") for code in device.status):
            continue
        for kind in ("time", "method", "user", "slot", "slot_name", "value", "count"):
            entities.append(LockAuditSensor(coordinator, device, kind))
    async_add_entities(entities)
