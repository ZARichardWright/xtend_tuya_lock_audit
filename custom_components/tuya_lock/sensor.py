from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import LockCoordinator


def _map_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN, "fingerprint_map.json"))


def _mapping(hass: HomeAssistant) -> dict[str, str]:
    try:
        data = json.loads(_map_path(hass).read_text())
        return {str(key): str(value) for key, value in (data.get("slots", data) if isinstance(data, dict) else {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def _save_mapping(hass: HomeAssistant, mapping: dict[str, str]) -> None:
    path = _map_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"slots": dict(sorted(mapping.items()))}, indent=2) + "\n")


def _record(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    status = raw.get("status") or {}
    code = str(status.get("code", "unknown"))
    value = status.get("value", "")
    slot = str(value) if code == "unlock_fingerprint_kit" and value != "" else ""
    if slot and slot not in mapping:
        mapping[slot] = f"Fingerprint slot {slot}"
    timestamp = raw.get("update_time", 0)
    timestamp = float(timestamp) / 1000 if float(timestamp or 0) > 10_000_000_000 else float(timestamp or 0)
    return {
        "time": datetime.fromtimestamp(timestamp, dt_util.DEFAULT_TIME_ZONE).isoformat() if timestamp else "",
        "method": code.removeprefix("unlock_").removesuffix("_kit").replace("_", " ").title(),
        "method_code": code,
        "slot": slot,
        "slot_name": mapping.get(slot, "") if slot else "",
        "user": raw.get("nick_name") or raw.get("unlock_name") or "",
        "user_id": raw.get("user_id", ""),
        "value": value,
        "device_id": raw.get("device_id", ""),
        "device_name": raw.get("device_name", ""),
    }


class LockAuditSensor(CoordinatorEntity[LockCoordinator], SensorEntity):
    def __init__(self, coordinator: LockCoordinator, device_id: str, kind: str, name: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self.kind = kind
        self._attr_name = f"{name} Last Unlock {kind.replace('_', ' ').title()}"
        self._attr_unique_id = f"{device_id}_lock_audit_{kind}"
        self._attr_icon = "mdi:lock-clock"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)}, name=name, manufacturer="Tuya")

    @property
    def _records(self) -> list[dict[str, Any]]:
        before = dict(self.coordinator.mapping)
        records = [_record(item, self.coordinator.mapping) for item in (self.coordinator.data or {}).get("logs", []) if item.get("device_id") == self.device_id]
        if before != self.coordinator.mapping:
            _save_mapping(self.hass, self.coordinator.mapping)
        return records

    @property
    def native_value(self) -> Any:
        records = self._records
        if self.kind == "count":
            return len(records)
        return records[0].get(self.kind) if records else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = self._records
        return {"latest": records[0] if records else {}, "records": records[:20]}


class LockAuditMarkdownSensor(CoordinatorEntity[LockCoordinator], SensorEntity):
    """Ready-to-render Markdown summary for a Lovelace Markdown card."""

    def __init__(self, coordinator: LockCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Tuya Lock Audit Markdown"
        self._attr_unique_id = "tuya_lock_audit_markdown"
        self._attr_icon = "mdi:format-list-text"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("logs", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mapping = self.coordinator.mapping
        records = [_record(item, mapping) for item in (self.coordinator.data or {}).get("logs", [])]
        markdown = [
            "## Tuya Lock Audit",
            "",
            "| Time | Device | Method | User | Slot |",
            "|---|---|---|---|---|",
        ]
        for item in records[:20]:
            values = (
                item.get("time", "")[:19].replace("T", " "),
                item.get("device_name", "").replace("|", "\\|"),
                item.get("method", "").replace("|", "\\|"),
                item.get("user", "") or "-",
                (f"{item.get('slot')} — {item.get('slot_name')}" if item.get("slot") else "-"),
            )
            markdown.append("| " + " | ".join(values) + " |")
        if not records:
            markdown.append("| No unlock records found |  |  |  |  |")
        return {"markdown": "\n".join(markdown), "record_count": len(records)}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    mapping = _mapping(hass)
    coordinator.mapping = mapping
    entities: list[LockAuditSensor] = []
    for device_id, device in coordinator.data.get("devices", {}).items():
        name = device.get("name", device_id)
        for kind in ("time", "method", "user", "slot", "slot_name", "value", "count"):
            entities.append(LockAuditSensor(coordinator, device_id, kind, name))
    entities.append(LockAuditMarkdownSensor(coordinator))
    _save_mapping(hass, mapping)
    async_add_entities(entities)
