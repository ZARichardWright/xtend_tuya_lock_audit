from __future__ import annotations

import logging
import voluptuous as vol
from typing import Any
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .client import TuyaClient, TuyaError
from .const import CONF_ACCESS_ID, CONF_ACCESS_SECRET, CONF_DEVICE_ID, CONF_ENDPOINT, DEFAULT_ENDPOINT, DOMAIN

LOGGER = logging.getLogger(__name__)


class TuyaLockConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            LOGGER.debug(
                "Validating Tuya Lock Audit configuration (endpoint=%s, explicit_device=%s)",
                user_input[CONF_ENDPOINT],
                bool(user_input.get(CONF_DEVICE_ID)),
            )
            try:
                client = TuyaClient(user_input[CONF_ENDPOINT], user_input[CONF_ACCESS_ID], user_input[CONF_ACCESS_SECRET])
                await self.hass.async_add_executor_job(client.authenticate)
                if user_input.get(CONF_DEVICE_ID):
                    await self.hass.async_add_executor_job(client.get, f"/v1.0/iot-03/devices/{user_input[CONF_DEVICE_ID]}/status")
                LOGGER.info("Tuya Lock Audit configuration validation succeeded")
                return self.async_create_entry(title="Tuya Lock Audit", data=user_input)
            except TuyaError as err:
                LOGGER.warning("Tuya Lock Audit configuration validation failed: %s", err)
                errors["base"] = "cannot_connect"
                if "not found" in str(err).lower():
                    errors["base"] = "not_a_lock"
            except Exception:
                LOGGER.exception("Unexpected Tuya Lock Audit config flow error")
                errors["base"] = "unknown"
        schema = vol.Schema({
            vol.Required(CONF_ENDPOINT, default=DEFAULT_ENDPOINT): str,
            vol.Required(CONF_ACCESS_ID): str,
            vol.Required(CONF_ACCESS_SECRET): str,
            vol.Optional(CONF_DEVICE_ID, default=""): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
