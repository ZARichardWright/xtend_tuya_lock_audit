from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LockCoordinator


def _path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DOMAIN, "fingerprint_map.json"))


def _load(hass: HomeAssistant) -> dict[str, str]:
    try:
        data = json.loads(_path(hass).read_text())
        slots = data.get("slots", data) if isinstance(data, dict) else {}
        return {str(key): str(value) for key, value in slots.items()}
    except (OSError, ValueError, TypeError):
        return {}


def _save(hass: HomeAssistant, slots: dict[str, str]) -> None:
    path = _path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"slots": dict(sorted(slots.items()))}, indent=2) + "\n")


class FingerprintNameText(CoordinatorEntity[LockCoordinator], TextEntity):
    _attr_native_max = 80
    _attr_icon = "mdi:fingerprint"

    def __init__(self, coordinator: LockCoordinator, slot: str, name: str) -> None:
        super().__init__(coordinator)
        self.slot = slot
        self._attr_name = f"Fingerprint Slot {slot} Name"
        self._attr_unique_id = f"tuya_lock_fingerprint_slot_{slot}"
        self._attr_native_value = name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.mapping[self.slot] = value.strip()
        await self.hass.async_add_executor_job(_save, self.hass, self.coordinator.mapping)
        self._attr_native_value = value.strip()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.mapping.update(await hass.async_add_executor_job(_load, hass))
    slots = set(coordinator.mapping)
    for item in (coordinator.data or {}).get("logs", []):
        status: dict[str, Any] = item.get("status") or {}
        if status.get("code") == "unlock_fingerprint_kit" and status.get("value") not in (None, ""):
            slots.add(str(status["value"]))
    mapping = coordinator.mapping
    for slot in slots:
        mapping.setdefault(slot, f"Fingerprint slot {slot}")
    await hass.async_add_executor_job(_save, hass, mapping)
    async_add_entities([FingerprintNameText(coordinator, slot, mapping[slot]) for slot in sorted(slots)])
