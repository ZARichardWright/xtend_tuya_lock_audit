from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from .client import TuyaClient, TuyaError

LOGGER = logging.getLogger(__name__)

MQTT_CONFIG_PATH = "/v1.0/iot-03/open-hub/access-config"
GCM_TAG_LENGTH = 16


@dataclass(frozen=True, slots=True)
class TuyaPushEvent:
    """Sanitized Tuya push event passed from MQTT to Home Assistant."""

    device_id: str
    codes: frozenset[str]
    protocol: str
    expects_audit: bool


class TuyaPushListener(threading.Thread):
    """Minimal Tuya Open Hub MQTT listener for configured lock devices."""

    def __init__(
        self,
        client: TuyaClient,
        device_ids: set[str],
        event_callback: Callable[[TuyaPushEvent], None],
    ) -> None:
        super().__init__(name="tuya-lock-open-hub", daemon=True)
        self._api = client
        self._device_ids = device_ids
        self._event_callback = event_callback
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._mqtt_client: mqtt.Client | None = None
        self._config: dict[str, Any] = {}
        self._link_id = f"tuya-lock-audit.{uuid.uuid4()}"

    def run(self) -> None:
        """Maintain the Tuya MQTT connection with bounded backoff."""
        backoff = 1
        while not self._stop_event.is_set():
            try:
                if not self._connection_is_valid():
                    self._disconnect()
                    self._config = self._get_mqtt_config()
                    self._connect()
                    LOGGER.info("Tuya Open Hub push listener connected")
                backoff = 1
                self._stop_event.wait(1)
            except (OSError, ValueError, KeyError, TuyaError) as err:
                LOGGER.warning(
                    "Tuya Open Hub push listener unavailable; retrying in %d seconds: %s",
                    backoff,
                    err,
                )
                self._disconnect()
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 300)
            except Exception:
                LOGGER.exception(
                    "Unexpected Tuya Open Hub listener failure; retrying in %d seconds",
                    backoff,
                )
                self._disconnect()
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 300)
        self._disconnect()

    def stop(self) -> None:
        """Stop MQTT and wait briefly for the listener thread."""
        self._stop_event.set()
        self._disconnect()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=10)

    def _connection_is_valid(self) -> bool:
        if self._mqtt_client is None or not self._mqtt_client.is_connected():
            return False
        valid_until = int(self._config.get("valid_until", 0))
        return valid_until > int(time.time() * 1000) + 5 * 60 * 1000

    def _get_mqtt_config(self) -> dict[str, Any]:
        if not self._api.uid:
            self._api.authenticate()
        response = self._api.post(
            MQTT_CONFIG_PATH,
            {
                "uid": self._api.uid,
                "link_id": self._link_id,
                "link_type": "mqtt",
                "topics": "device",
                "msg_encrypted_version": "2.0",
            },
        )
        result = response.get("result") or {}
        required = ("url", "client_id", "username", "password", "source_topic")
        missing = [key for key in required if not result.get(key)]
        if missing:
            raise ValueError(
                "Tuya Open Hub response omitted " + ", ".join(missing)
            )
        expires = int(result.get("expire_time", 0))
        return {
            **result,
            "valid_until": int(response.get("t", time.time() * 1000))
            + expires * 1000,
        }

    def _connect(self) -> None:
        self._connected_event.clear()
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=str(self._config["client_id"]),
        )
        client.username_pw_set(
            str(self._config["username"]),
            str(self._config["password"]),
        )
        client.user_data_set({"password": str(self._config["password"])})
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        parsed = urlsplit(str(self._config["url"]))
        if parsed.hostname is None or parsed.port is None:
            raise ValueError("Tuya Open Hub returned an invalid MQTT URL")
        if parsed.scheme == "ssl":
            client.tls_set()
        self._mqtt_client = client
        result = client.connect(parsed.hostname, parsed.port, keepalive=60)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise OSError(f"MQTT connect returned {result}")
        client.loop_start()
        if not self._connected_event.wait(timeout=15):
            raise OSError("Timed out waiting for Tuya MQTT connection")

    def _disconnect(self) -> None:
        client = self._mqtt_client
        self._mqtt_client = None
        self._connected_event.clear()
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            LOGGER.debug("Ignoring Tuya MQTT disconnect failure", exc_info=True)
        try:
            client.loop_stop()
        except Exception:
            LOGGER.debug("Ignoring Tuya MQTT loop-stop failure", exc_info=True)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            LOGGER.warning("Tuya MQTT connection rejected: %s", reason_code)
            return
        topics = self._config.get("source_topic", {})
        topic_values = topics.values() if isinstance(topics, dict) else topics
        for topic in topic_values:
            client.subscribe(str(topic), qos=0)
        self._connected_event.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        self._connected_event.clear()
        if not self._stop_event.is_set() and reason_code != 0:
            LOGGER.warning("Tuya MQTT disconnected unexpectedly: %s", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: dict[str, Any],
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            envelope = json.loads(message.payload.decode("utf-8"))
            timestamp = str(envelope.get("t", ""))
            decrypted = self._decrypt_message(
                str(envelope["data"]),
                str(userdata["password"]),
                timestamp,
            )
            event = self._parse_event(
                {
                    "protocol": envelope.get("protocol", ""),
                    "data": decrypted,
                }
            )
            if event is None or event.device_id not in self._device_ids:
                return
            LOGGER.debug(
                "Tuya lock push event: device=%s protocol=%s codes=%s",
                event.device_id,
                event.protocol,
                sorted(event.codes),
            )
            self._event_callback(event)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            LOGGER.warning("Could not decode a Tuya Open Hub message", exc_info=True)
        except Exception:
            LOGGER.exception("Unexpected failure while processing Tuya push message")

    @staticmethod
    def _decrypt_message(
        encoded: str,
        password: str,
        timestamp: str,
    ) -> dict[str, Any]:
        encrypted = base64.b64decode(encoded)
        iv_length = int.from_bytes(encrypted[:4], byteorder="big")
        iv_end = 4 + iv_length
        iv = encrypted[4:iv_end]
        ciphertext_and_tag = encrypted[iv_end:]
        if len(ciphertext_and_tag) <= GCM_TAG_LENGTH:
            raise ValueError("Encrypted Tuya message is too short")
        key = password[8:24].encode("utf-8")
        plaintext = AESGCM(key).decrypt(
            iv,
            ciphertext_and_tag,
            timestamp.encode("utf-8"),
        )
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Tuya MQTT payload was not an object")
        return decoded

    @staticmethod
    def _parse_event(message: dict[str, Any]) -> TuyaPushEvent | None:
        data = message.get("data") or {}
        if not isinstance(data, dict):
            return None
        nested = data.get("data") if isinstance(data.get("data"), dict) else {}
        biz_data = (
            data.get("bizData") if isinstance(data.get("bizData"), dict) else {}
        )
        containers = (data, nested, biz_data)
        device_id = next(
            (
                str(container[key])
                for container in containers
                for key in ("devId", "deviceId", "device_id")
                if container.get(key)
            ),
            "",
        )
        if not device_id:
            return None
        status = next(
            (
                container.get("status")
                for container in containers
                if isinstance(container.get("status"), list)
            ),
            [],
        )
        codes = frozenset(
            str(item.get("code", item.get("dpId", "")))
            for item in status
            if isinstance(item, dict)
            and item.get("code", item.get("dpId")) not in (None, "")
        )
        biz_code = str(data.get("bizCode", ""))
        expects_audit = any(code.startswith("unlock_") for code in codes) or (
            biz_code == "event_notify"
        )
        return TuyaPushEvent(
            device_id=device_id,
            codes=codes,
            protocol=str(message.get("protocol", "")),
            expects_audit=expects_audit,
        )
