# Tuya Lock Audit

An unofficial, lock-only Home Assistant integration based on the Tuya cloud
API. This is a small fork/extension derived from the setup and API work in
[Xtend Tuya](https://github.com/azerty9971/xtend_tuya); it is not the official
Xtend Tuya integration and does not replace it.

## What it does

- Configures directly with a Tuya IoT endpoint, Access ID, and Access Secret.
- First filters Tuya devices to the smart-lock category family (`ms` and
  known lock subtypes), then confirms they report `unlock_*` lock functions.
- Uses Tuya Open Hub MQTT push events to refresh lock state and audit data
  quickly, with a fifteen-minute REST poll as a fallback.
- Exposes latest unlock method, user, fingerprint slot, slot name, raw value,
  and record count as Home Assistant sensors.
- Attributes dashboard and app unlock requests to the logged-in Home Assistant
  user while retaining Tuya's original remote-user value in sensor attributes.
- Automatically maintains `/config/tuya_lock/fingerprint_map.json`.
- Creates and deletes temporary PINs through native entities or Home Assistant
  actions. Generated PINs are shown in persistent notifications and are not
  stored in entity state.
- Exposes a small diagnostic version sensor for troubleshooting.

The original Xtend Tuya integration can remain installed separately for other
devices. This repository intentionally contains only `custom_components/tuya_lock`.

If Tuya Open Hub is unavailable for the configured cloud project, the
integration logs a warning, reconnects with bounded backoff, and continues to
refresh through the fallback poll.

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

## Temporary PINs

Each discovered lock receives these entities:

- **Temporary PIN Name**
- **Temporary PIN Validity**
- **Create Temporary PIN**
- **Temporary PIN to Delete**
- **Delete Selected Temporary PIN**
- **Temporary PIN Count**

Set the name and validity, then press **Create Temporary PIN**. Home Assistant
shows the generated PIN and delivery progress in a persistent notification.
Dismiss that notification after securely sharing the PIN.

For dashboards, add the entities above to an Entities card. Add a confirmation
dialog to the delete button card to prevent accidental deletion.

Automations and scripts can use:

```yaml
action: tuya_lock.create_temporary_pin
data:
  name: Cleaner
  validity_minutes: 480
  pin_length: 6
```

When exactly one lock is configured, `device_id` is optional. Delete an
existing credential with `tuya_lock.delete_temporary_pin` and its numeric
`password_id`. IDs and current credential metadata are available on the
**Temporary PIN Count** sensor.

## Status

Audit history, fingerprint mapping, Home Assistant user attribution, lock
control, event-driven refresh, and temporary PIN management are implemented.

See [CHANGELOG.md](./CHANGELOG.md) for release notes.

## Acknowledgements

- Based on API and setup work from
  [Xtend Tuya](https://github.com/azerty9971/xtend_tuya).
- Designed and implemented collaboratively with
  [OpenAI Codex](https://openai.com/codex/).
