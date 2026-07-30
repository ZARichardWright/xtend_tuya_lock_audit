from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .client import TuyaError
from .const import DOMAIN
from .coordinator import LockCoordinator

LOGGER = logging.getLogger(__name__)


class TuyaLockEntity(CoordinatorEntity[LockCoordinator], LockEntity):
    def __init__(self, coordinator: LockCoordinator, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{device_id}_lock"
        self._attr_icon = "mdi:lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Tuya",
            model="Smart Lock",
        )
        LOGGER.info("Created Home Assistant lock entity for %s (%s)", name, device_id)

    @property
    def is_locked(self) -> bool | None:
        status = (self.coordinator.data or {}).get("devices", {}).get(self.device_id, {}).get("status", {})
        if isinstance(status.get("lock_motor_state"), bool):
            locked = not status["lock_motor_state"]
            LOGGER.debug(
                "Lock %s state from lock_motor_state=%s -> locked=%s",
                self.device_id,
                status["lock_motor_state"],
                locked,
            )
            return locked
        for code in ("open_close", "closed_opened", "closed_opened_kit"):
            value = str(status.get(code, "")).lower()
            if value in {"closed", "close", "aqac"}:
                LOGGER.debug("Lock %s state from %s=%s -> locked", self.device_id, code, value)
                return True
            if value in {"open", "opened", "aqab"}:
                LOGGER.debug("Lock %s state from %s=%s -> unlocked", self.device_id, code, value)
                return False
        LOGGER.warning(
            "Could not determine lock state for %s; available status codes: %s",
            self.device_id,
            sorted(status),
        )
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        await self._async_operate(True, self._context)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._async_operate(False, self._context)

    async def _async_operate(self, lock: bool, context: Context | None) -> None:
        requested_at = int(dt_util.utcnow().timestamp() * 1000)
        LOGGER.info("Requesting %s operation for lock %s", "lock" if lock else "unlock", self.device_id)
        try:
            await self.hass.async_add_executor_job(self._operate_sync, lock)
            if not lock:
                await self.coordinator.async_register_remote_unlock(
                    self.device_id,
                    context,
                    requested_at,
                )
            await self.coordinator.async_request_refresh()
            LOGGER.info("%s operation accepted for lock %s", "Lock" if lock else "Unlock", self.device_id)
        except TuyaError as err:
            LOGGER.error("Lock command failed for %s: %s", self.device_id, err)

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
    entities = [
        TuyaLockEntity(coordinator, device_id, device.get("name", device_id))
        for device_id, device in coordinator.data.get("devices", {}).items()
    ]
    LOGGER.info("Lock platform adding %d entity/entities", len(entities))
    async_add_entities(entities)
