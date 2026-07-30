# Lock audit

Xtend Tuya adds audit sensors for supported Tuya locks. The lock API is polled
once per minute through Xtend's existing authenticated Tuya IOT client.

For a fingerprint lock, the API reports the fingerprint slot rather than a
person. Edit `/config/xtend_tuya/fingerprint_map.json` as slots are identified:

```json
{
  "1": "Child 1",
  "2": "Child 2"
}
```

If a new slot appears, Xtend adds it with an empty value so it is ready to be
named. The latest record and the most recent 20 records are exposed in the
audit sensor attributes.

The entities are created only for devices that expose an `unlock_*` status,
and include latest time, method, user, slot, mapped slot name, raw value, and
record count.
