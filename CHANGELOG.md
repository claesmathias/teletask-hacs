# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] — Initial release

### Added
- Native TCP connection to Teletask central units (MICROS+, NANOS, PICOS)
- Real-time push state updates — no polling
- Auto-reconnect on connection loss (retries every 30 seconds)
- UI config flow — fully configurable via Settings → Integrations, no YAML needed
- **Light platform** — RELAY (type: light) and DIMMER with brightness 0–100%
- **Switch platform** — RELAY (type: switch), FLAG, TIMEDFNC, LOCMOOD/GENMOOD/TIMEDMOOD (type: switch)
- **Cover platform** — MOTOR with UP/DOWN/STOP and position control 0–100
- **Sensor platform** — TEMPERATURE, HUMIDITY, LIGHT, GAS, PULSECOUNTER
- **Binary sensor platform** — INPUT (digital buttons) and COND (conditions)
- **Scene platform** — LOCMOOD, GENMOOD, TIMEDMOOD, TIMEDFNC (type: scene)
- Same `config.json` format as [jeletask](https://github.com/ridiekel/jeletask) for easy migration

### Not yet supported
- `DISPLAYMESSAGE` — Aurus wall display messages
- `TEMPERATURECONTROL` — HVAC / climate entities
