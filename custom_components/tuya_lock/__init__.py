from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_ID,
    CONF_ENDPOINT,
    DOMAIN,
    VERSION,
)
from .coordinator import LockCoordinator

PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.TEXT]
LOGGER = logging.getLogger(__name__)


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
    LOGGER.info("Tuya Lock Audit platform setup completed")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    LOGGER.debug("Unloading Tuya Lock Audit entry %s", entry.entry_id)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
