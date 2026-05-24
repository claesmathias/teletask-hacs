# Changelog

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
