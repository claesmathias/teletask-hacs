# Changelog

## [1.5.1] — 2026-05-30

### Fixed
- **Scene timestamp NaN errors on startup** — after the 1.5.0 fix, scenes with no recorded
  activation started with state `"unknown"`, which the HA frontend's `hui-timestamp-display`
  tried to parse as a date and got `NaN`, throwing `RangeError: number argument must be finite`.
  `async_added_to_hass` now calls `super().async_added_to_hass()` (enabling `RestoreEntity`)
  and restores `_attr_last_activated` from the HA recorder so previously-activated scenes have
  a valid ISO timestamp on startup.

## [1.5.0] — 2026-05-30

### Fixed
- **Scene timestamps invalid in HA UI** — `TeletaskScene` was overriding HA's `@final BaseScene.state`
  property (which returns the ISO datetime of the last activation) with `"ON"`/`"OFF"`/`"unknown"`,
  breaking the timestamp display entirely. The override and `_mood_state` tracking are removed;
  `_async_record_activation()` is now called on every incoming `ON` event so physical keypad
  activations also update the timestamp correctly.
- **README entity-naming examples corrected** — four wrong function-code numbers in the examples
  table (`9 → GENMOOD`, missing GENMOOD entry, `FLAG = 12`, `COND = 63`).

## [1.4.0] — 2026-05-29

### Changed
- **`hatype: button` RELAY entities are now exposed as `switch` instead of `button`**
  — `ButtonEntity` is stateless in HA and only records activity for UI-initiated presses,
  not for physical Teletask panel presses. Changing to `SwitchEntity` (backed by the
  same `TeletaskEntity` base as every other RELAY) means ON/OFF transitions appear in
  the HA activity log identically to lights and switches.
  **Migration:** update any dashboard cards or automations that reference `button.garage_door`
  (or similar) to use `switch.garage_door`. The `teletask_event` bus event on physical
  presses is preserved.

## [1.3.1] — 2026-05-29

### Fixed
- **Button activity not visible in HA logbook** — `_handle_state_update` was setting
  `_attr_state` (ignored on `ButtonEntity`, which is stateless) instead of
  `_attr_last_pressed`. External relay triggers now correctly update the
  `last_pressed` timestamp, making physical activations visible in the HA activity log.

## [1.3.0] — 2026-05-28

### Fixed
- **Physical button/scene activations not visible in HA** — `TeletaskMomentaryButton`
  and `TeletaskScene` were not subscribing to dispatcher signals, so state changes
  triggered from the physical TeleTask panel were silently dropped. Both entities
  now subscribe via `async_added_to_hass` and update the HA state machine.
- **Scene entity history blank** — overrode `state` to return the live mood state
  (`ON`/`OFF`) and call `async_write_ha_state()` on every push event so transitions
  are recorded in HA's history panel.
- **Button entity last-pressed time not updating** — set `_attr_state` to the UTC
  timestamp on external relay triggers (same mechanism HA uses internally), making
  physical activations visible in the entity history.

### Added
- `teletask_event` HA bus event fired on every physical activation of a scene or
  button. Payload: `{function, number, description, state}`. Use in automations via
  `trigger: platform: event / event_type: teletask_event`.
- 47 new unit tests: protocol coverage for TIMEDMOOD, TIMEDFNC, LOCMOOD/COND
  polarity gaps, and a full `TestWatchTvLocmood4` component class; plus 33 entity
  tests for `TeletaskScene` and `TeletaskMomentaryButton` that run without a live
  HA installation.

## [1.1.0] — 2026-05-27

### Added
- **Area support** — components now accept an `area` field in `config.json`;
  the value is passed as `suggested_area` in `DeviceInfo` so HA auto-assigns
  the entity to the correct room.
- **Button entity** — RELAY components with `hatype: button` are now exposed as
  `ButtonEntity` for momentary dry-contact triggers (e.g. garage doors).
  A `pulse_ms` field controls the ON→OFF pulse duration (default 500 ms).

### Fixed
- Scene and button entities were missing `DeviceInfo` (manufacturer, model, area),
  causing them to appear as orphan entities not linked to a device.

## [1.0.1] — 2026-05-24

### Fixed
- **Blocking I/O in event loop** — `open()` call in `config_flow.py` was blocking
  the HA async event loop, causing a warning and potential instability. File reads
  are now offloaded to a thread-pool executor via `loop.run_in_executor()`.
- **"Cannot send: not connected" on startup** — the TCP client now properly invokes
  a disconnect callback when the connection drops, which triggers the hub's reconnect
  loop. Previously the hub only scheduled a reconnect on initial connection failure,
  not on mid-session drops.
- **Reconnect loop guard** — prevented duplicate reconnect tasks from being spawned
  when multiple disconnect events fired in quick succession.

## [1.0.0] — Initial release

### Added
- Native TCP connection to Teletask central units (MICROS+, NANOS, PICOS)
- Real-time push state updates — no polling
- Auto-reconnect on connection loss (retries every 30 seconds)
- UI config flow — two-step setup (connection + config.json file path)
- **Light platform** — RELAY (type: light) and DIMMER with brightness 0–100%
- **Switch platform** — RELAY (type: switch), FLAG, TIMEDFNC, moods (type: switch)
- **Cover platform** — MOTOR with UP/DOWN/STOP and position control 0–100
- **Sensor platform** — TEMPERATURE, HUMIDITY, LIGHT, GAS, PULSECOUNTER
- **Binary sensor platform** — INPUT (digital buttons) and COND (conditions)
- **Scene platform** — LOCMOOD, GENMOOD, TIMEDMOOD, TIMEDFNC (type: scene)
- Options flow — update config.json path via Settings → Integrations → Configure
