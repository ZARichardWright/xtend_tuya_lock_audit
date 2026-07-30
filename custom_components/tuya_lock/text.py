from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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

    def __init__(
        self,
        coordinator: LockCoordinator,
        slot: str,
        name: str,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.slot = slot
        self._attr_name = f"Fingerprint Slot {slot} Name"
        self._attr_unique_id = f"tuya_lock_fingerprint_slot_{slot}"
        self._attr_native_value = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Tuya",
            model="Smart Lock",
        )

    async def async_set_value(self, value: str) -> None:
        self.coordinator.mapping[self.slot] = value.strip()
        await self.hass.async_add_executor_job(_save, self.hass, self.coordinator.mapping)
        self._attr_native_value = value.strip()
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()


class TemporaryPinNameText(CoordinatorEntity[LockCoordinator], TextEntity):
    _attr_native_max = 80
    _attr_icon = "mdi:form-textbox"

    def __init__(
        self,
        coordinator: LockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        coordinator.temporary_pin_name.setdefault(device_id, "Guest")
        self._attr_name = "Temporary PIN Name"
        self._attr_unique_id = f"{device_id}_temporary_pin_name"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Tuya",
            model="Smart Lock",
        )

    @property
    def native_value(self) -> str:
        return self.coordinator.temporary_pin_name[self.device_id]

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if value:
            self.coordinator.temporary_pin_name[self.device_id] = value
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
    devices = (coordinator.data or {}).get("devices", {})
    if not devices:
        return
    device_id, device = next(iter(devices.items()))
    device_name = device.get("name", device_id)
    entities: list[TextEntity] = [
            FingerprintNameText(
                coordinator, slot, mapping[slot], device_id, device_name
            )
            for slot in sorted(slots)
        ]
    entities.append(
        TemporaryPinNameText(coordinator, device_id, device_name)
    )
    async_add_entities(entities)
