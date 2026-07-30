from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import TuyaError
from .const import DOMAIN
from .coordinator import LockCoordinator


class TuyaLockEntity(CoordinatorEntity[LockCoordinator], LockEntity):
    def __init__(self, coordinator: LockCoordinator, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_lock"
        self._attr_icon = "mdi:lock"

    @property
    def is_locked(self) -> bool | None:
        status = (self.coordinator.data or {}).get("devices", {}).get(self.device_id, {}).get("status", {})
        if isinstance(status.get("lock_motor_state"), bool):
            return not status["lock_motor_state"]
        for code in ("open_close", "closed_opened", "closed_opened_kit"):
            value = str(status.get(code, "")).lower()
            if value in {"closed", "close", "aqac"}:
                return True
            if value in {"open", "opened", "aqab"}:
                return False
        return None

    def lock(self, **kwargs: Any) -> None:
        self.hass.async_create_task(self._async_operate(True))

    def unlock(self, **kwargs: Any) -> None:
        self.hass.async_create_task(self._async_operate(False))

    async def _async_operate(self, lock: bool) -> None:
        try:
            await self.hass.async_add_executor_job(self._operate_sync, lock)
            await self.coordinator.async_request_refresh()
        except TuyaError as err:
            logging.getLogger(__name__).error("Lock command failed for %s: %s", self.device_id, err)

    def _operate_sync(self, lock: bool) -> None:
        client = self.coordinator.client
        ticket = client.post(f"/v1.0/devices/{self.device_id}/door-lock/password-ticket")
        ticket_id = (ticket.get("result") or {}).get("ticket_id")
        if not ticket_id:
            raise TuyaError("Tuya did not return a lock operation ticket")
        result = client.post(
            f"/v1.0/smart-lock/devices/{self.device_id}/password-free/door-operate",
            {"ticket_id": ticket_id, "open": "false" if lock else "true"},
        )
        if result.get("success") is not True:
            raise TuyaError(result.get("msg", "Tuya rejected the lock command"))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: LockCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TuyaLockEntity(coordinator, device_id, device.get("name", device_id))
        for device_id, device in coordinator.data.get("devices", {}).items()
    ])
