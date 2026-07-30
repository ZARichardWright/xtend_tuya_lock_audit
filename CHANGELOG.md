# Tuya Lock Audit release notes

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
