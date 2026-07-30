from __future__ import annotations

from datetime import datetime
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import LockCoordinator


class TemporaryPinSelect(CoordinatorEntity[LockCoordinator], SelectEntity):
    _attr_name = "Temporary PIN to Delete"
    _attr_icon = "mdi:key-remove"

    def __init__(
        self,
        coordinator: LockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_temporary_pin_to_delete"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Tuya",
            model="Smart Lock",
        )

    def _option_map(self) -> dict[str, str]:
        options: dict[str, str] = {}
        for item in self.coordinator.temporary_passwords(self.device_id):
            password_id = str(item.get("id", ""))
            if not password_id:
                continue
            name = str(item.get("name") or "Unnamed PIN")
            timestamp = item.get("invalid_time")
            expiry = ""
            if isinstance(timestamp, (int, float)):
                expiry = datetime.fromtimestamp(
                    timestamp, dt_util.DEFAULT_TIME_ZONE
                ).strftime("%Y-%m-%d %H:%M")
            label = f"{name} — expires {expiry} (ID {password_id})"
            options[label] = password_id
        return options

    @property
    def options(self) -> list[str]:
        return list(self._option_map())

    @property
    def current_option(self) -> str | None:
        selected = self.coordinator.temporary_pin_selected.get(self.device_id)
        return next(
            (
                label
                for label, password_id in self._option_map().items()
                if password_id == selected
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        password_id = self._option_map().get(option)
        if password_id is None:
            raise HomeAssistantError("The selected temporary PIN no longer exists")
        self.coordinator.temporary_pin_selected[self.device_id] = password_id
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TemporaryPinSelect(
                coordinator, device_id, device.get("name", device_id)
            )
            for device_id, device in coordinator.data["devices"].items()
        ]
    )
