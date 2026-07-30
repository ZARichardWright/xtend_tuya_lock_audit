from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LockCoordinator


class TemporaryPinValidityNumber(
    CoordinatorEntity[LockCoordinator], NumberEntity
):
    _attr_name = "Temporary PIN Validity"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 720
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    def __init__(
        self,
        coordinator: LockCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        coordinator.temporary_pin_validity_hours.setdefault(device_id, 24)
        self._attr_unique_id = f"{device_id}_temporary_pin_validity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Tuya",
            model="Smart Lock",
        )

    @property
    def native_value(self) -> float:
        return self.coordinator.temporary_pin_validity_hours[self.device_id]

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.temporary_pin_validity_hours[self.device_id] = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TemporaryPinValidityNumber(
                coordinator, device_id, device.get("name", device_id)
            )
            for device_id, device in coordinator.data["devices"].items()
        ]
    )
