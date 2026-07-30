from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LockCoordinator


class TemporaryPinButton(CoordinatorEntity[LockCoordinator], ButtonEntity):
    def __init__(
        self,
        coordinator: LockCoordinator,
        device_id: str,
        device_name: str,
        action: str,
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self.action = action
        self._attr_name = (
            "Create Temporary PIN"
            if action == "create"
            else "Delete Selected Temporary PIN"
        )
        self._attr_unique_id = f"{device_id}_temporary_pin_{action}"
        self._attr_icon = (
            "mdi:key-plus" if action == "create" else "mdi:key-remove"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Tuya",
            model="Smart Lock",
        )

    async def async_press(self) -> None:
        if self.action == "create":
            name = self.coordinator.temporary_pin_name.get(
                self.device_id, "Guest"
            )
            hours = self.coordinator.temporary_pin_validity_hours.get(
                self.device_id, 24
            )
            await self.coordinator.async_create_temporary_pin(
                self.device_id,
                name,
                max(1, round(hours * 60)),
            )
            return
        password_id = self.coordinator.temporary_pin_selected.get(
            self.device_id
        )
        if not password_id:
            raise HomeAssistantError(
                "Select a temporary PIN before pressing delete"
            )
        await self.coordinator.async_delete_temporary_pin(
            self.device_id, password_id
        )
        self.coordinator.temporary_pin_selected.pop(self.device_id, None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []
    for device_id, device in coordinator.data["devices"].items():
        name = device.get("name", device_id)
        entities.extend(
            (
                TemporaryPinButton(
                    coordinator, device_id, name, "create"
                ),
                TemporaryPinButton(
                    coordinator, device_id, name, "delete"
                ),
            )
        )
    async_add_entities(entities)
