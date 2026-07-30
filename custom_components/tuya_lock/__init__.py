from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import CONF_ACCESS_ID, CONF_ACCESS_SECRET, CONF_DEVICE_ID, CONF_ENDPOINT, DOMAIN
from .coordinator import LockCoordinator

PLATFORMS = [Platform.SENSOR]
LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = LockCoordinator(
        hass, entry.data[CONF_ENDPOINT], entry.data[CONF_ACCESS_ID], entry.data[CONF_ACCESS_SECRET], entry.data.get(CONF_DEVICE_ID, "")
    )
    coordinator.entry_id = entry.entry_id
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.data or not coordinator.data.get("devices"):
        return False
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
