# Changelog

## [1.8.0] — 2026-11-14

Checked against the protocol documents in `docs/`: TDS LIBRARY V3.4 and V3.7
(classic protocol, what a PICOS/MICROS+ speaks) and TDS15132 DoIP API (2026).
Where they disagree, the library documents win.

### Fixed
- **Timed functions sent key presses.** `TIMEDFNC` used function code 52,
  which is the push-button function (`FNC_TPKEY`): switching a timed function
  simulated a key press. It now uses 5.
- **Push buttons (`INPUT`) never reported.** They used function code 62,
  which doesn't exist; they now use 52. A short press no longer leaves the
  binary sensor on forever: it shows on for one second.
- Existing `INPUT` and `TIMEDFNC` entities and devices are moved to the new
  codes on update (config entry migration); entity IDs stay the same.
- **Humidity, light, gas and pulse-counter sensors were decoded as
  temperatures.** Each sensor type now has its own conversion (humidity in %,
  logarithmic lux, analog range for gas, pulse counter real-time value).
  Sensor error values show as unknown. `decimals` now sets the display
  precision.

### Added
- **Display messages** (`DISPLAYMESSAGE`): a
  `notify` entity per set of touch panels. `notify.send_message` spreads the
  text over both lines (a title becomes line 1); the new
  `teletask.send_display_message` action also sets message/alarm, beeps and
  the character set.
- **Climate zones**: a `SENSOR` with `type: TEMPERATURECONTROL` gets a
  `climate` entity (target, day/night/standby/frost presets, heat/cool/auto
  and more modes, optional fan speeds, on/off) and `number` entities for the
  preset temperatures.
- **Audio zones** (`AUDIO`) as `media_player`: power, volume steps, mute,
  named sources, next/previous preset, now-playing text.
- **Push-button events**: an `event` entity per `INPUT` with `short_press`,
  `long_press` and `release`.
- **Process and service functions** (`PROCES`, `SERVICE`) as switches.
- **Motors**: optional slat tilt (`"tilt": true`) and sun protection switch
  (`"sun_protection": true`); sun/wind protection, requested position and
  time to finish as attributes.
- **Pulse counter totals**: with `pulses_per_unit`, a *… total* sensor.
- **DoIP-only types** (PROSOFT 5, not yet tried on a real central):
  `DIMMERGRP`, `MOTORGRP`, `RGB`/`RGBGRP`, `TW`/`TWGRP` (tunable white),
  `ALARM`, `DIGITALINPUT` and `ACCESS` (badge reader events).
- The component editor knows all new types and their fields.
- `tests/ha`: setup tests in a real Home Assistant against a fake central.

### Changed
- The offline test suite no longer waits 2 seconds per test; only the live
  central tests do (5 minutes → under a second).

## [1.7.0] — 2026-11-07

### Added
- **Reload picks up `config.json` changes.** The config file path is now
  remembered, and the file is re-read on every load. After editing the file,
  the integration's normal **Reload** (or an HA restart) is enough.
- **Configure menu** with four options:
  - **Edit components**: a menu of component types with counts, each opening
    Home Assistant's native list editor. Every component is edited in a form
    with a number box, name, `hatype` dropdown (only the values valid for that
    type), area dropdown and type-specific fields (relay pulse length, sensor
    type, decimals and unit). Add and remove components, edit several types,
    then save once.
  - **Edit as YAML (advanced)**: the full configuration in HA's code editor.
    If the file is broken, it opens the last loaded version for repair.
  - **Reload from file**: path pre-filled; enter a new path to link another file.
  - **Settings**: debug logging.
  Saving validates the configuration, writes it to the linked file as JSON with
  one component per line (keeping the previous version as `.bak`) and reloads.
  Keys the forms don't show are preserved.
- **Config validation** with readable errors: JSON syntax errors give line and
  column, and structure problems are named (unknown component type, duplicate
  or missing `number`, non-text `description`).
- **`Connection` diagnostic sensor** on the central device: shows whether the
  TCP control connection is up, updated on connect and disconnect (no polling).
  Until now an outage was only visible in the log.
- **`Last event` diagnostic sensor**: when the central last reported a state
  change. The first event after a start or reload is shown immediately; after
  that it's throttled to one write per minute so resubscribe bursts don't
  flood the recorder.
- **Repairs entry when the central is unreachable**: after 5 minutes
  disconnected, *Teletask central unit unreachable* appears under Settings →
  System → Repairs, with since when, the host and port, and the last error. It
  clears itself on reconnect; shorter blips never raise it.

### Changed
- **Requires Home Assistant 2025.7 or newer** (was 2023.1). The component
  editor uses the object selector's form fields, added in 2025.7; HACS won't
  offer this version on older installations.
- If the linked file is missing or invalid at load, the integration keeps
  running on the last successfully loaded configuration and shows a
  notification, instead of silently using a stale copy.
- Relative paths resolve against HA's configuration folder instead of a
  hard-coded `/config`.
- **Ready for HA 2027.8.** Component devices now link to the central with
  `via_device_id`; HA 2026.11 deprecates the old `via_device` link (and logs a
  warning per platform) and removes it in 2027.8. Older HA versions keep using
  `via_device`.
- **Local dev setup**: `docker-compose.dev.yml` (Home Assistant on
  http://localhost:8124) and `tools/fake_central.py` (a fake central speaking
  the Teletask protocol and serving the support page) to test the integration,
  including outages, without touching a real installation. See README → Local
  development.
- **Less log noise during outages.** A failed reconnect no longer logs an error
  every 30 seconds. The log now gets one warning when the outage starts (with
  the reason) and one when it ends, with the duration and number of attempts.
  Individual retries are logged at debug level.
- Entries created before 1.7.0 have no remembered path; link it once via
  **Configure → Reload from file**.


### Fixed
- **Scenes are now "Connected via" the central** like every other component.
  Mood and timed-function devices were missing the link and showed up as
  separate, unrelated devices. Existing devices are updated in place; entity
  IDs don't change.

## [1.6.0] — 2026-11-05

_Not released separately; included in 1.7.0._

### Added
- **Central unit device** — the central now appears as its own device, filled in
  from its built-in support web page (`/cgi-bin/serial.cgi`): model (e.g. PICOS),
  serial number, MAC address, PROSOFT version (firmware), disk version
  (hardware), and a link to the web page. All component devices now show
  "Connected via" the central.
- **Diagnostic sensors** on the central device, read every 5 minutes:
  `Clock` (the central's clock from `/cgi-bin/time.cgi`), `Clock offset`
  (seconds of drift against Home Assistant), and `Project file` (the loaded
  PROSOFT `.nbt` project, with its owner as an attribute).
- If the web page can't be reached, setup isn't blocked; the sensors are
  unavailable until a read succeeds.

## [1.5.6] — 2026-07-24

### Added
- **`docs/` folder** — local copies of the official Teletask reference PDFs
  (`TDS LIBRARY V3.7.pdf` and `TELETASK Technical Handbook_EN_2019.01.24.pdf`).
- **`test-license/` folder** — a TDS15132 test-mode activation file for
  unlocking the TCP API in TELETASK PROSOFT without a paid licence, for
  development/testing purposes.
- **README** — new "Documentation & test license" section documenting the
  above and the steps to import the test license in PROSOFT
  (Extra → Licenses → import `.act` → save `.NBT` → transmit to central unit).

## [1.5.4] — 2026-05-30

### Fixed
- **Scene `insertBefore` NaN error not covered by 1.5.3** — 1.5.3 moved the
  `async_write_ha_state()` call to the start of `async_added_to_hass`, but still
  after `await super().async_added_to_hass()`. That `await` is a yield point: the
  event loop can flush the `"unknown"` WebSocket state-change event to the browser
  before our valid ISO timestamp overwrites it, causing Lovelace to re-render
  (lit-html `insertBefore`) with an invalid datetime. Two changes:
  - `_attr_last_activated` is now seeded to `dt_util.utcnow()` in `__init__` so
    `entity.state` never returns `"unknown"` even before `async_added_to_hass` runs.
  - `async_write_ha_state()` is called as the very first line of
    `async_added_to_hass` (before `await super()`), eliminating the yield-point
    race entirely.

## [1.5.3] — 2026-05-30

### Fixed
- **Scene timestamp NaN errors during startup window** — `hub.async_setup()` was awaiting
  `_subscribe_all()` (1.5+ second wait) before `async_forward_entry_setups` was called,
  leaving HA's `core.restore_state` snapshot of `"unknown"` visible to the frontend
  for the entire duration. Subscription is now started as a background task so entity
  platforms are set up immediately and entities write a valid ISO timestamp to the state
  machine before any page render can race the window.
- **Two-phase scene state write** — `async_added_to_hass` now writes `dt_util.utcnow()`
  immediately (overwriting the stale snapshot entry at the earliest possible moment),
  then refines with the recorder value (`last_state.last_changed` fallback) once the
  `async_get_last_state()` await returns.

## [1.5.2] — 2026-05-30

### Fixed
- **Scene timestamp NaN errors persist when recorder has `"unknown"` state** — the 1.5.1 fix
  only handled the case where the recorder held a valid ISO timestamp; when the stored state
  was `"unknown"` (written by 1.5.0) or any other non-ISO string, `dt_util.parse_datetime`
  returned `None` and `_attr_last_activated` stayed `None`, causing the same
  `RangeError: number argument must be finite` on the next page load. The fallback chain is
  now: ISO timestamp → `last_state.last_changed` → `dt_util.utcnow()`, ensuring
  `_attr_last_activated` is always a valid datetime.

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
