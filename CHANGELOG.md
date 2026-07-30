# Tuya Lock Audit release notes

## 0.4.1 — 2026-07-30

- Filters expired and terminal-phase records from the current temporary-PIN
  count and deletion selector.
- Retains Tuya's unfiltered historical record count as the diagnostic
  `cloud_record_count` sensor attribute.
- Prevents old cloud records from appearing as usable PINs after each API poll.

## 0.4.0 — 2026-07-30

- Added native entities for temporary PIN management: name, validity, PIN
  selection, create/delete buttons, and active PIN count.
- Added `tuya_lock.create_temporary_pin` and
  `tuya_lock.delete_temporary_pin` services for scripts and automations.
- Generates six- or seven-digit PINs securely and keeps them out of entity
  state and recorder history. New PINs are shown in a persistent notification.
- Added asynchronous ten-second delivery checks for Tuya lock families that
  report installed credentials as phase 12 and expose the assigned lock slot.
- Added temporary-PIN inventory to coordinator refreshes and immediate refreshes
  after create/delete operations.
- Kept all Tuya HTTP calls, ticket decryption, PIN encryption, and blocking
  work in Home Assistant's executor.

## 0.3.0 — 2026-07-30

- Added a standalone Tuya Open Hub MQTT listener based on the push transport
  used by Xtend Tuya.
- Lock push events now trigger a debounced status and audit refresh after three
  seconds; unlock events retry at ten and thirty seconds while waiting for the
  cloud audit row.
- Reduced periodic REST polling from once per minute to once every fifteen
  minutes as a fallback when push delivery is unavailable.
- Added thread-safe handoff from Paho MQTT callbacks to Home Assistant's event
  loop, clean listener shutdown, reconnect backoff, and concurrent Tuya client
  request protection.

## 0.2.7 — 2026-07-30

- Added the PNG brand asset required by HACS repository validation.
- Added HACS-compatible GitHub repository description and topics.

## 0.2.6 — 2026-07-30

- Attributes Home Assistant remote unlocks to the logged-in Home Assistant user
  who requested them.
- Persists pending and matched attribution records across Home Assistant
  restarts and overlays the Home Assistant user on Tuya `Phone Remote` events.
- Adds a Markdown render revision and immediately notifies audit sensors when a
  fingerprint Text entity changes, so dashboard Markdown refreshes without
  waiting for the next cloud poll.
- Adds the issue tracker and correct manifest key ordering required by current
  HACS and hassfest validation.

## 0.2.5 — 2026-07-30

- Fixed lock/unlock operations failing because the password-ticket POST request
  correctly has no JSON body.

## 0.2.4 — 2026-07-30

- Removed the device-ID column from the Markdown audit table.
- Combined user and fingerprint slot information into one User column.
- Fingerprint events show the mapped name when available, otherwise their slot
  number; code and card events use Tuya's reported user name.

## 0.2.3 — 2026-07-30

- Replaced threaded lock callbacks with Home Assistant-native async lock and
  unlock methods.
- Fetches the real Tuya device name and product metadata when an explicit
  device ID is configured.
- Groups the lock entity, audit sensors, Markdown sensor, version sensor, and
  fingerprint-name text entities under the same Home Assistant device.

## 0.2.2 — 2026-07-30

- Added safe debug logging for config setup, cloud requests, device discovery,
  returned lock status codes, platform forwarding, lock-entity creation, state
  interpretation, and lock/unlock operations.
- Sensitive credentials, tokens, ticket IDs, and PIN values are not logged.

## 0.2.1 — 2026-07-30

- Updated the config flow to the current Home Assistant typed flow pattern.
- Added an explicit user-facing unknown-error message for flow validation failures.

## 0.2.0 — 2026-07-30

- Restored the basic Home Assistant lock entity.
- Added live lock-state polling from lock status DPs.
- Added lock and unlock controls using Tuya's password-free door-operation API.
- Ported the original Xtend Tuya lock operation sequence, including operation tickets.

## 0.1.3 — 2026-07-30

- Moved all Tuya network requests into Home Assistant's executor.
- Moved fingerprint mapping file reads and writes into the executor.
- Prevented blocking-call errors during authentication, polling, and mapping updates.

## 0.1.2 — 2026-07-30

- Bumped the version so HACS can clearly identify the event-loop-safe build.

## 0.1.1 — 2026-07-30

- Added a diagnostic version sensor.
- Added a lock-themed integration icon.
- Added frontend-editable fingerprint slot name entities.

## 0.1.0 — 2026-07-30

- Converted the prototype into the standalone `tuya_lock` integration.
- Added independent Tuya cloud configuration.
- Added lock-category discovery for `ms` and known lock subtypes.
- Added unlock audit polling through the Tuya `open-logs` endpoint.
- Added fingerprint slot mapping and a ready-to-render Markdown audit sensor.
- Added HACS and README documentation.
