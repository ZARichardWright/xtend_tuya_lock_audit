# Tuya Lock Audit

An unofficial, lock-only Home Assistant integration based on the Tuya cloud
API. This is a small fork/extension derived from the setup and API work in
[Xtend Tuya](https://github.com/azerty9971/xtend_tuya); it is not the official
Xtend Tuya integration and does not replace it.

## What it does

- Configures directly with a Tuya IoT endpoint, Access ID, and Access Secret.
- First filters Tuya devices to the smart-lock category family (`ms` and
  known lock subtypes), then confirms they report `unlock_*` lock functions.
- Polls the lock open-log endpoint once per minute.
- Exposes latest unlock method, user, fingerprint slot, slot name, raw value,
  and record count as Home Assistant sensors.
- Attributes dashboard and app unlock requests to the logged-in Home Assistant
  user while retaining Tuya's original remote-user value in sensor attributes.
- Automatically maintains `/config/tuya_lock/fingerprint_map.json`.
- Exposes a small diagnostic version sensor for troubleshooting.

The original Xtend Tuya integration can remain installed separately for other
devices. This repository intentionally contains only `custom_components/tuya_lock`.

## Installation

Add this public repository to HACS as a custom **Integration** repository:

`https://github.com/ZARichardWright/xtend_tuya_lock_audit`

Install **Tuya Lock Audit**, restart Home Assistant, then add it from Settings
→ Devices & services. Enter the Tuya cloud credentials used by the lock. Leave
Device ID empty to discover lock devices, or provide the lock device ID to use
one device explicitly.

## Fingerprint mapping

The lock API reports fingerprint slots, not people. Edit the generated file:

```json
{
  "slots": {
    "1": "Child 1",
    "2": "Child 2"
  }
}
```

## Status

Audit polling is implemented first. Temporary PIN management and lock control
will be added after the standalone audit path has been tested.

See [CHANGELOG.md](./CHANGELOG.md) for release notes.
