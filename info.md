# Teletask — Native Home Assistant Integration

Control your **Teletask domotics** system directly from Home Assistant — no MQTT broker, no Java bridge, no Docker container required.

This integration connects over TCP directly to your Teletask central unit (MICROS+, NANOS, PICOS) using the same binary protocol as the popular [jeletask](https://github.com/ridiekel/jeletask) project, but entirely natively inside Home Assistant.

---

## What you get

- 🔦 **Lights** — relays and dimmers with full brightness control
- 🪟 **Covers** — motors/blinds with position, UP/DOWN/STOP
- 🎭 **Scenes** — local moods, general moods, timed moods
- 🌡️ **Sensors** — temperature, humidity, light, gas, pulse counter
- 🔘 **Switches** — relays, flags, timed functions
- 🔲 **Binary sensors** — digital inputs (buttons), conditions
- ⚡ **Real-time push updates** — no polling, instant state changes
- 🔌 **Auto-reconnect** — recovers automatically from network drops

---

## Requirements

- A Teletask **MICROS+**, NANOS, or PICOS central unit
- The **TDS15132 TCP licence** from Teletask (required for TCP access)
- Home Assistant 2023.1 or newer

---

## Quick setup

After installing via HACS and restarting Home Assistant:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Teletask**
3. Enter your central unit IP, port (`55957`), a name, and paste your component JSON config

No YAML configuration needed.
