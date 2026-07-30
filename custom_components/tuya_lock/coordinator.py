from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import json
import secrets
import string
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.components import persistent_notification
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import TuyaClient, TuyaError
from .const import DOMAIN, LOCK_CATEGORIES
from .push import TuyaPushEvent, TuyaPushListener
from .temporary_pin import encrypt_pin

LOGGER = logging.getLogger(__name__)

ATTRIBUTION_STORE_VERSION = 1
REMOTE_UNLOCK_CODE = "unlock_phone_remote_kit"
PENDING_ATTRIBUTION_TTL_MS = 30 * 60 * 1000
ATTRIBUTION_MATCH_WINDOW_MS = 10 * 60 * 1000
MATCHED_ATTRIBUTION_TTL_MS = 45 * 24 * 60 * 60 * 1000
PUSH_REFRESH_DELAYS = (3, 10, 30)
TEMPORARY_PASSWORD_TERMINAL_PHASES = {3, 4, 5, 17}


def _is_current_temporary_password(
    item: dict[str, Any], now: int
) -> bool:
    try:
        invalid_time = int(item.get("invalid_time") or 0)
    except (TypeError, ValueError):
        return False
    return (
        invalid_time > now
        and item.get("phase") not in TEMPORARY_PASSWORD_TERMINAL_PHASES
    )


class LockCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, endpoint: str, access_id: str, access_secret: str, device_id: str = "") -> None:
        self.entry_id = ""
        self.mapping: dict[str, str] = {}
        self.pending_attributions: list[dict[str, Any]] = []
        self.matched_attributions: dict[str, dict[str, Any]] = {}
        self._attribution_store: Store[dict[str, Any]] | None = None
        self._push_listener: TuyaPushListener | None = None
        self._push_refresh_task: asyncio.Task[None] | None = None
        self._push_expects_audit = False
        self._push_codes: set[str] = set()
        self._pin_monitor_tasks: set[asyncio.Task[None]] = set()
        self.temporary_pin_name: dict[str, str] = {}
        self.temporary_pin_validity_hours: dict[str, float] = {}
        self.temporary_pin_selected: dict[str, str] = {}
        self.client = TuyaClient(endpoint, access_id, access_secret)
        self.requested_device_id = device_id
        self.devices: dict[str, dict[str, Any]] = {}
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name="tuya_lock_audit",
            update_interval=timedelta(minutes=15),
        )

    @callback
    def async_start_push(self) -> None:
        """Start Tuya Open Hub without blocking Home Assistant."""
        if self._push_listener is not None:
            return
        self._push_listener = TuyaPushListener(
            self.client,
            set(self.devices),
            self._handle_push_from_thread,
        )
        self._push_listener.start()
        LOGGER.info(
            "Started Tuya Open Hub listener for %d lock device(s); "
            "fallback polling interval is 15 minutes",
            len(self.devices),
        )

    def _handle_push_from_thread(self, event: TuyaPushEvent) -> None:
        """Hand a Paho callback safely to the Home Assistant event loop."""
        try:
            self.hass.loop.call_soon_threadsafe(
                self._async_handle_push_event,
                event,
            )
        except RuntimeError:
            LOGGER.debug("Home Assistant stopped before push event delivery")

    @callback
    def _async_handle_push_event(self, event: TuyaPushEvent) -> None:
        if event.device_id not in self.devices:
            return
        self._push_codes.update(event.codes)
        self._push_expects_audit |= event.expects_audit
        if self._push_refresh_task and not self._push_refresh_task.done():
            LOGGER.debug(
                "Coalesced Tuya push event for %s into pending refresh",
                event.device_id,
            )
            return
        self._push_refresh_task = self.hass.async_create_task(
            self._async_refresh_after_push(),
            "Tuya lock audit refresh after push",
        )

    async def _async_refresh_after_push(self) -> None:
        baseline = max(
            (
                int(item.get("update_time", 0))
                for item in (self.data or {}).get("logs", [])
            ),
            default=0,
        )
        previous_delay = 0
        try:
            for delay in PUSH_REFRESH_DELAYS:
                await asyncio.sleep(delay - previous_delay)
                previous_delay = delay
                LOGGER.debug(
                    "Refreshing Tuya lock data after push; codes=%s attempt=%ss",
                    sorted(self._push_codes),
                    delay,
                )
                await self.async_request_refresh()
                latest = max(
                    (
                        int(item.get("update_time", 0))
                        for item in (self.data or {}).get("logs", [])
                    ),
                    default=0,
                )
                if latest > baseline or not self._push_expects_audit:
                    break
        finally:
            self._push_codes.clear()
            self._push_expects_audit = False

    async def async_shutdown(self) -> None:
        """Stop push tasks and the MQTT network thread."""
        if self._push_refresh_task and not self._push_refresh_task.done():
            self._push_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._push_refresh_task
        for task in self._pin_monitor_tasks:
            task.cancel()
        if self._pin_monitor_tasks:
            await asyncio.gather(
                *self._pin_monitor_tasks, return_exceptions=True
            )
        self._pin_monitor_tasks.clear()
        listener = self._push_listener
        self._push_listener = None
        if listener is not None:
            await self.hass.async_add_executor_job(listener.stop)
            LOGGER.info("Stopped Tuya Open Hub push listener")

    async def async_load_attributions(self) -> None:
        """Load pending and matched Home Assistant unlock attribution."""
        self._attribution_store = Store(
            self.hass,
            ATTRIBUTION_STORE_VERSION,
            f"{DOMAIN}.{self.entry_id}.remote_unlock_attribution",
        )
        stored = await self._attribution_store.async_load() or {}
        pending = stored.get("pending", [])
        matched = stored.get("matched", {})
        self.pending_attributions = [
            dict(item) for item in pending if isinstance(item, dict)
        ]
        self.matched_attributions = {
            str(key): dict(value)
            for key, value in matched.items()
            if isinstance(value, dict)
        }
        LOGGER.debug(
            "Loaded %d pending and %d matched remote-unlock attribution record(s)",
            len(self.pending_attributions),
            len(self.matched_attributions),
        )

    async def async_register_remote_unlock(
        self,
        device_id: str,
        context: Context | None,
        requested_at: int,
    ) -> None:
        """Remember who requested an unlock until its Tuya audit row appears."""
        user_id = context.user_id if context else None
        user_name = "Home Assistant automation"
        if user_id:
            user = await self.hass.auth.async_get_user(user_id)
            user_name = user.name if user and user.name else user_id
        self.pending_attributions.append(
            {
                "device_id": device_id,
                "requested_at": requested_at,
                "ha_user_id": user_id or "",
                "ha_user_name": user_name,
                "ha_context_id": context.id if context else "",
            }
        )
        await self._async_save_attributions()
        LOGGER.info(
            "Registered remote unlock attribution for %s to Home Assistant user %s",
            device_id,
            user_name,
        )

    def temporary_password_records(
        self, device_id: str
    ) -> list[dict[str, Any]]:
        """Return every temporary-password record retained by Tuya."""
        device = (self.data or {}).get("devices", {}).get(device_id, {})
        passwords = device.get("temporary_passwords", [])
        return passwords if isinstance(passwords, list) else []

    def temporary_passwords(self, device_id: str) -> list[dict[str, Any]]:
        """Return credentials that can still be current on the lock."""
        now = int(dt_util.utcnow().timestamp())
        return [
            item
            for item in self.temporary_password_records(device_id)
            if _is_current_temporary_password(item, now)
        ]

    async def async_create_temporary_pin(
        self,
        device_id: str,
        name: str,
        validity_minutes: int,
        pin_length: int = 6,
    ) -> dict[str, Any]:
        """Create a PIN and monitor its delivery without storing the PIN in state."""
        result = await self.hass.async_add_executor_job(
            self._create_temporary_pin_sync,
            device_id,
            name,
            validity_minutes,
            pin_length,
        )
        password_id = str(result["password_id"])
        notification_id = f"{DOMAIN}_temporary_pin_{password_id}"
        persistent_notification.async_create(
            self.hass,
            self._pin_notification_message(result, "Configuring on lock"),
            title="Tuya temporary PIN created",
            notification_id=notification_id,
        )
        task = self.hass.async_create_task(
            self._async_monitor_temporary_pin(result),
            f"Tuya temporary PIN delivery {password_id}",
        )
        self._pin_monitor_tasks.add(task)
        task.add_done_callback(self._pin_monitor_tasks.discard)
        await self.async_request_refresh()
        return result

    def _create_temporary_pin_sync(
        self,
        device_id: str,
        name: str,
        validity_minutes: int,
        pin_length: int,
    ) -> dict[str, Any]:
        pin = "".join(secrets.choice(string.digits) for _ in range(pin_length))
        effective = dt_util.now() + timedelta(seconds=30)
        invalid = effective + timedelta(minutes=validity_minutes)
        ticket = self.client.post(
            f"/v1.0/devices/{device_id}/door-lock/password-ticket"
        ).get("result", {})
        ticket_id = ticket.get("ticket_id")
        ticket_key = ticket.get("ticket_key")
        if not ticket_id or not ticket_key:
            raise TuyaError(
                "Password ticket response lacked ticket_id or ticket_key"
            )
        created = self.client.post(
            f"/v1.0/devices/{device_id}/door-lock/temp-password",
            {
                "name": name,
                "password": encrypt_pin(
                    pin, str(ticket_key), self.client.access_secret
                ),
                "effective_time": int(effective.timestamp()),
                "invalid_time": int(invalid.timestamp()),
                "password_type": "ticket",
                "ticket_id": ticket_id,
                "type": 0,
                "time_zone": str(dt_util.DEFAULT_TIME_ZONE),
            },
        )
        password_id = created.get("result", {}).get("id")
        if password_id is None:
            raise TuyaError("Create response lacked a password ID")
        LOGGER.info(
            "Created temporary password %s for %s; awaiting lock delivery",
            password_id,
            device_id,
        )
        return {
            "device_id": device_id,
            "password_id": str(password_id),
            "name": name,
            "pin": pin,
            "effective_time": effective,
            "invalid_time": invalid,
        }

    @staticmethod
    def _pin_notification_message(
        created: dict[str, Any], delivery: str
    ) -> str:
        effective = created["effective_time"].strftime("%Y-%m-%d %H:%M:%S")
        invalid = created["invalid_time"].strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"**Name:** {created['name']}\n\n"
            f"**PIN:** `{created['pin']}`\n\n"
            f"**Valid:** {effective} to {invalid}\n\n"
            f"**Delivery:** {delivery}\n\n"
            f"**Password ID:** {created['password_id']}\n\n"
            "Dismiss this notification after securely sharing the PIN."
        )

    async def _async_monitor_temporary_pin(
        self, created: dict[str, Any]
    ) -> None:
        password_id = created["password_id"]
        notification_id = f"{DOMAIN}_temporary_pin_{password_id}"
        delivery = "Delivery status timed out; check the lock or Tuya app"
        try:
            for _attempt in range(12):
                await asyncio.sleep(10)
                details = await self.hass.async_add_executor_job(
                    self.client.get,
                    (
                        f"/v1.0/devices/{created['device_id']}/door-lock/"
                        f"temp-password/{password_id}"
                    ),
                )
                status = details.get("result", {})
                phase = status.get("phase")
                serial_number = status.get("sn")
                delivery_status = status.get("delivery_status")
                if (
                    phase == 12
                    and isinstance(serial_number, int)
                    and serial_number >= 0
                ):
                    delivery = f"Installed successfully in lock slot {serial_number}"
                    break
                if delivery_status == 2:
                    delivery = "Tuya reported successful delivery"
                    break
                if phase in (3, 4, 5) or delivery_status in (3, 4, 5):
                    delivery = (
                        f"Stopped with phase {phase}, "
                        f"delivery status {delivery_status}"
                    )
                    break
        except asyncio.CancelledError:
            raise
        except TuyaError:
            LOGGER.exception(
                "Temporary PIN %s delivery monitoring failed", password_id
            )
            delivery = "Delivery check failed; inspect the Home Assistant log"
        persistent_notification.async_create(
            self.hass,
            self._pin_notification_message(created, delivery),
            title="Tuya temporary PIN",
            notification_id=notification_id,
        )
        await self.async_request_refresh()

    async def async_delete_temporary_pin(
        self, device_id: str, password_id: str
    ) -> None:
        await self.hass.async_add_executor_job(
            self.client.delete,
            (
                f"/v1.0/devices/{device_id}/door-lock/"
                f"temp-passwords/{password_id}"
            ),
        )
        persistent_notification.async_dismiss(
            self.hass, f"{DOMAIN}_temporary_pin_{password_id}"
        )
        LOGGER.info(
            "Deleted temporary password %s from %s", password_id, device_id
        )
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        LOGGER.debug("Starting Tuya lock coordinator refresh")
        try:
            data = await self.hass.async_add_executor_job(self._update_sync)
            if self._apply_remote_unlock_attributions(data):
                await self._async_save_attributions()
            LOGGER.debug(
                "Coordinator refresh completed with %d device(s) and %d audit record(s)",
                len(data.get("devices", {})),
                len(data.get("logs", [])),
            )
            return data
        except TuyaError as err:
            LOGGER.error("Tuya lock coordinator refresh failed: %s", err)
            raise UpdateFailed(str(err)) from err

    async def _async_save_attributions(self) -> None:
        if self._attribution_store is None:
            return
        await self._attribution_store.async_save(
            {
                "pending": self.pending_attributions,
                "matched": self.matched_attributions,
            }
        )

    @staticmethod
    def _attribution_key(record: dict[str, Any]) -> str:
        status = record.get("status") or {}
        return "|".join(
            (
                str(record.get("device_id", "")),
                str(record.get("update_time", "")),
                str(status.get("code", "")),
            )
        )

    def _apply_remote_unlock_attributions(self, data: dict[str, Any]) -> bool:
        """Attach HA users to matching Tuya Phone Remote audit records."""
        now_ms = int(dt_util.utcnow().timestamp() * 1000)
        changed = False
        logs = data.get("logs", [])
        remote_logs = [
            item
            for item in logs
            if (item.get("status") or {}).get("code") == REMOTE_UNLOCK_CODE
        ]

        for record in remote_logs:
            attribution = self.matched_attributions.get(
                self._attribution_key(record)
            )
            if attribution:
                record.update(attribution)

        remaining: list[dict[str, Any]] = []
        claimed_keys = set(self.matched_attributions)
        for pending in sorted(
            self.pending_attributions,
            key=lambda item: int(item.get("requested_at", 0)),
        ):
            requested_at = int(pending.get("requested_at", 0))
            if now_ms - requested_at > PENDING_ATTRIBUTION_TTL_MS:
                LOGGER.warning(
                    "Expired unmatched remote unlock attribution for %s (%s)",
                    pending.get("device_id"),
                    pending.get("ha_user_name"),
                )
                changed = True
                continue
            candidates = [
                record
                for record in remote_logs
                if record.get("device_id") == pending.get("device_id")
                and self._attribution_key(record) not in claimed_keys
                and requested_at - 3_000
                <= int(record.get("update_time", 0))
                <= requested_at + ATTRIBUTION_MATCH_WINDOW_MS
            ]
            if not candidates:
                remaining.append(pending)
                continue
            record = min(
                candidates,
                key=lambda item: abs(
                    int(item.get("update_time", 0)) - requested_at
                ),
            )
            key = self._attribution_key(record)
            attribution = {
                "ha_user_id": pending.get("ha_user_id", ""),
                "ha_user_name": pending.get("ha_user_name", ""),
                "ha_context_id": pending.get("ha_context_id", ""),
                "ha_requested_at": requested_at,
                "ha_event_time": int(record.get("update_time", 0)),
            }
            self.matched_attributions[key] = attribution
            claimed_keys.add(key)
            record.update(attribution)
            changed = True
            LOGGER.info(
                "Matched Tuya remote unlock at %s to Home Assistant user %s",
                record.get("update_time"),
                attribution["ha_user_name"],
            )
        self.pending_attributions = remaining

        expired_keys = [
            key
            for key, attribution in self.matched_attributions.items()
            if now_ms - int(attribution.get("ha_event_time", 0))
            > MATCHED_ATTRIBUTION_TTL_MS
        ]
        for key in expired_keys:
            self.matched_attributions.pop(key, None)
            changed = True
        return changed

    def _update_sync(self) -> dict[str, Any]:
        try:
            mapping = self._load_mapping()
            device_ids = [self.requested_device_id] if self.requested_device_id else self._discover_ids()
            LOGGER.debug("Refreshing lock device IDs: %s", device_ids)
            result: dict[str, Any] = {"devices": {}, "logs": []}
            end = int(dt_util.utcnow().timestamp() * 1000)
            start = end - 30 * 24 * 60 * 60 * 1000
            for device_id in device_ids:
                device = self.devices.get(device_id)
                if device is None or device.get("name") in (None, "", device_id):
                    device_info = self.client.get(f"/v1.0/devices/{device_id}").get(
                        "result", {}
                    )
                    device = {
                        "id": device_id,
                        "name": device_info.get("name") or device_id,
                        "category": device_info.get("category"),
                        "product_name": device_info.get("product_name"),
                    }
                    self.devices[device_id] = device
                    LOGGER.info(
                        "Loaded Tuya device metadata for %s: name=%s, category=%s, product=%s",
                        device_id,
                        device["name"],
                        device.get("category"),
                        device.get("product_name"),
                    )
                status_rows = self.client.get(f"/v1.0/iot-03/devices/{device_id}/status").get("result", [])
                status = {str(row.get("code")): row.get("value") for row in status_rows if isinstance(row, dict)}
                LOGGER.debug(
                    "Device %s returned status codes: %s",
                    device_id,
                    sorted(status),
                )
                logs = self.client.get(
                    f"/v1.1/devices/{device_id}/door-lock/open-logs",
                    {"page_no": 1, "page_size": 100, "start_time": start, "end_time": end},
                ).get("result", {}).get("logs", [])
                passwords = self.client.get(
                    f"/v1.0/devices/{device_id}/door-lock/temp-passwords"
                ).get("result", [])
                device["status"] = status
                device["temporary_passwords"] = (
                    passwords if isinstance(passwords, list) else []
                )
                result["devices"][device_id] = device
                now = int(dt_util.utcnow().timestamp())
                current_passwords = [
                    item
                    for item in device["temporary_passwords"]
                    if _is_current_temporary_password(item, now)
                ]
                LOGGER.debug(
                    "Device %s returned %d current temporary PIN(s) "
                    "from %d cloud record(s)",
                    device_id,
                    len(current_passwords),
                    len(device["temporary_passwords"]),
                )
                LOGGER.debug(
                    "Device %s (%s) returned %d audit record(s)",
                    device_id,
                    device.get("name", device_id),
                    len(logs) if isinstance(logs, list) else 0,
                )
                for record in logs if isinstance(logs, list) else []:
                    item = dict(record)
                    item["device_id"] = device_id
                    item["device_name"] = device["name"]
                    result["logs"].append(item)
                    status = item.get("status") or {}
                    if status.get("code") == "unlock_fingerprint_kit" and status.get("value") not in (None, ""):
                        slot = str(status["value"])
                        mapping.setdefault(slot, f"Fingerprint slot {slot}")
            result["logs"].sort(key=lambda item: item.get("update_time", 0), reverse=True)
            self.mapping = mapping
            self._save_mapping(mapping)
            return result
        except TuyaError:
            raise

    def _discover_ids(self) -> list[str]:
        self.client.authenticate()
        uid = self.client.uid
        if not uid:
            raise TuyaError("Tuya token response did not contain a user ID")
        devices = self.client.get(f"/v1.0/users/{uid}/devices").get("result", [])
        LOGGER.debug(
            "Tuya account returned %d total device(s)",
            len(devices) if isinstance(devices, list) else 0,
        )
        lock_ids: list[str] = []
        for item in devices if isinstance(devices, list) else []:
            device_id = item.get("id")
            if not device_id:
                continue
            if str(item.get("category", "")).lower() not in LOCK_CATEGORIES:
                LOGGER.debug(
                    "Skipping device %s (%s): category %s is not a lock category",
                    device_id,
                    item.get("name", device_id),
                    item.get("category"),
                )
                continue
            status = self.client.get(f"/v1.0/iot-03/devices/{device_id}/status").get("result", [])
            codes = {str(row.get("code", "")) for row in status if isinstance(row, dict)}
            if any(code.startswith("unlock_") for code in codes):
                self.devices[device_id] = {"id": device_id, "name": item.get("name") or device_id}
                lock_ids.append(device_id)
                LOGGER.info(
                    "Discovered Tuya lock %s (%s), category=%s, status_codes=%s",
                    item.get("name") or device_id,
                    device_id,
                    item.get("category"),
                    sorted(codes),
                )
            else:
                LOGGER.debug(
                    "Skipping category-matched device %s: no unlock_* status codes (%s)",
                    device_id,
                    sorted(codes),
                )
        LOGGER.info("Tuya lock discovery selected %d device(s)", len(lock_ids))
        return lock_ids

    def _mapping_path(self) -> Path:
        return Path(self.hass.config.path("tuya_lock", "fingerprint_map.json"))

    def _load_mapping(self) -> dict[str, str]:
        try:
            data = json.loads(self._mapping_path().read_text())
            slots = data.get("slots", data) if isinstance(data, dict) else {}
            return {str(key): str(value) for key, value in slots.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_mapping(self, mapping: dict[str, str]) -> None:
        path = self._mapping_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slots": dict(sorted(mapping.items()))}, indent=2) + "\n")
