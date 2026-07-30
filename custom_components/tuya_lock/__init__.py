from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_ID,
    CONF_ENDPOINT,
    DOMAIN,
    SERVICE_CREATE_TEMPORARY_PIN,
    SERVICE_DELETE_TEMPORARY_PIN,
    VERSION,
)
from .coordinator import LockCoordinator

PLATFORMS = [
    Platform.BUTTON,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TEXT,
]
LOGGER = logging.getLogger(__name__)

CREATE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=80)),
        vol.Optional("validity_minutes", default=1440): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=43200)
        ),
        vol.Optional("pin_length", default=6): vol.All(
            vol.Coerce(int), vol.In((6, 7))
        ),
    }
)
DELETE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DEVICE_ID): cv.string,
        vol.Required("password_id"): vol.All(cv.string, vol.Match(r"^\d+$")),
    }
)


def _resolve_coordinator(
    hass: HomeAssistant, requested_device_id: str
) -> tuple[LockCoordinator, str]:
    matches: list[tuple[LockCoordinator, str]] = []
    for coordinator in hass.data.get(DOMAIN, {}).values():
        if not isinstance(coordinator, LockCoordinator):
            continue
        for device_id in coordinator.devices:
            if not requested_device_id or device_id == requested_device_id:
                matches.append((coordinator, device_id))
    if not matches:
        raise HomeAssistantError("No matching Tuya lock was found")
    if len(matches) > 1:
        raise HomeAssistantError(
            "More than one Tuya lock is configured; supply device_id"
        )
    return matches[0]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    async def async_create(call: ServiceCall) -> None:
        coordinator, device_id = _resolve_coordinator(
            hass, call.data.get(CONF_DEVICE_ID, "")
        )
        await coordinator.async_create_temporary_pin(
            device_id,
            call.data["name"].strip(),
            call.data["validity_minutes"],
            call.data["pin_length"],
        )

    async def async_delete(call: ServiceCall) -> None:
        coordinator, device_id = _resolve_coordinator(
            hass, call.data.get(CONF_DEVICE_ID, "")
        )
        await coordinator.async_delete_temporary_pin(
            device_id, call.data["password_id"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_TEMPORARY_PIN,
        async_create,
        schema=CREATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_TEMPORARY_PIN,
        async_delete,
        schema=DELETE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    LOGGER.info(
        "Setting up Tuya Lock Audit %s for entry %s (explicit device: %s)",
        VERSION,
        entry.entry_id,
        bool(entry.data.get(CONF_DEVICE_ID)),
    )
    hass.data.setdefault(DOMAIN, {})
    coordinator = LockCoordinator(
        hass, entry.data[CONF_ENDPOINT], entry.data[CONF_ACCESS_ID], entry.data[CONF_ACCESS_SECRET], entry.data.get(CONF_DEVICE_ID, "")
    )
    coordinator.entry_id = entry.entry_id
    await coordinator.async_load_attributions()
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.data or not coordinator.data.get("devices"):
        LOGGER.error("No Tuya lock devices were available after the first refresh")
        return False
    LOGGER.info(
        "Tuya Lock Audit found %d lock device(s): %s",
        len(coordinator.data["devices"]),
        ", ".join(coordinator.data["devices"]),
    )
    hass.data[DOMAIN][entry.entry_id] = coordinator
    LOGGER.debug("Forwarding config entry to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_push()
    LOGGER.info("Tuya Lock Audit platform setup completed")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    LOGGER.debug("Unloading Tuya Lock Audit entry %s", entry.entry_id)
    coordinator: LockCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        if coordinator is not None:
            await coordinator.async_shutdown()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
