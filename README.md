# Teletask — Native Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **native** Home Assistant custom integration for [Teletask](https://www.teletask.be/) domotics central units.  
Connects directly over TCP — **no MQTT broker, no Java bridge, no Docker container required**.

> Inspired by the excellent [jeletask](https://github.com/ridiekel/jeletask) project, this integration implements the same Teletask binary TCP protocol natively inside Home Assistant.

---

## Supported platforms

| Teletask component | HA platform | Notes |
|---|---|---|
| `RELAY` (type: light) | `light` | On/off, default for relays |
| `RELAY` (type: switch) | `switch` | Set `"type": "switch"` in config |
| `DIMMER` | `light` | Brightness 0–100% |
| `MOTOR` | `cover` | UP / DOWN / STOP + position 0–100 |
| `LOCMOOD` | `switch` or `scene` | Set `"type": "scene"` to activate only |
| `GENMOOD` | `switch` or `scene` | Same |
| `TIMEDMOOD` | `switch` or `scene` | Same |
| `FLAG` | `switch` | |
| `SENSOR` | `sensor` | Temperature, humidity, light, gas, pulse |
| `COND` | `binary_sensor` | |
| `INPUT` | `binary_sensor` | Digital inputs / buttons |
| `TIMEDFNC` | `switch` or `scene` | Set `"type": "scene"` for pulse/activate |

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Click the **three-dot menu** (⋮) → **Custom repositories**
3. Add `https://github.com/claesmathias/teletask-hacs` with category **Integration**
4. Search for **Teletask** in HACS → Integrations → **Download**
5. Restart Home Assistant

### Manual

Copy the `custom_components/teletask` folder into your HA config directory:

```
<config>/
└── custom_components/
    └── teletask/
        ├── __init__.py
        ├── manifest.json
        └── ...
```

Restart Home Assistant.

---

## Configuration

Go to **Settings → Devices & Services → Add Integration → Teletask**.

| Field | Description | Default |
|---|---|---|
| **IP Address** | IP of your Teletask central unit | — |
| **Port** | TCP port of the central unit | `55957` |
| **Central Unit ID** | A unique name for this unit | `my_teletask` |
| **Config JSON** | Component definitions (see below) | `{}` |

### Config JSON format

Use the same `config.json` format as jeletask:

```json
{
  "type": "MICROS_PLUS",
  "componentsTypes": {
    "RELAY": [
      { "number": 1,  "description": "Power outlet",          "type": "switch" },
      { "number": 23, "description": "Living Room - Closet",  "type": "light"  },
      { "number": 36, "description": "Living room - Ceiling", "type": "light"  }
    ],
    "DIMMER": [
      { "number": 1, "description": "Spots" }
    ],
    "MOTOR": [
      { "number": 1, "description": "Blinds" }
    ],
    "SENSOR": [
      { "number": 3, "description": "Temperature Sensor", "type": "TEMPERATURE", "ha_unit_of_measurement": "°C" },
      { "number": 1, "description": "Light Sensor",       "type": "LIGHT" },
      { "number": 2, "description": "Humidity",           "type": "HUMIDITY" }
    ],
    "LOCMOOD": [
      { "number": 1, "description": "Watch TV",        "type": "scene" },
      { "number": 2, "description": "Romantic Dinner", "type": "scene" }
    ],
    "GENMOOD": [
      { "number": 1, "description": "All off",       "type": "scene" },
      { "number": 2, "description": "Downstairs off","type": "scene" }
    ],
    "TIMEDMOOD": [
      { "number": 1, "description": "Outdoor light", "type": "scene" }
    ],
    "FLAG": [
      { "number": 6, "description": "Holiday mode" }
    ],
    "INPUT": [
      { "number": 42, "description": "Doorbell button" },
      { "number": 43, "description": "Front door contact" }
    ],
    "TIMEDFNC": [
      { "number": 3, "description": "Garage door pulse", "type": "scene" }
    ],
    "COND": [
      { "number": 1, "description": "Alarm condition" }
    ]
  }
}
```

---

## Entity naming

Entity IDs follow this pattern:

```
<platform>.teletask_<central_id>_<function_code>_<number>
```

Examples:
```
light.teletask_my_teletask_1_23      → RELAY #23 (light)
light.teletask_my_teletask_2_1       → DIMMER #1
cover.teletask_my_teletask_6_1       → MOTOR #1 (blind)
scene.teletask_my_teletask_8_1       → LOCMOOD #1
sensor.teletask_my_teletask_20_3     → SENSOR #3
binary_sensor.teletask_my_teletask_62_42 → INPUT #42
```

The **friendly name** shown in the UI comes from the `description` field in your config JSON.

---

## Automation examples

### Toggle a light

```yaml
service: light.turn_on
target:
  entity_id: light.teletask_my_teletask_1_23
```

### Activate a mood/scene

```yaml
service: scene.turn_on
target:
  entity_id: scene.teletask_my_teletask_8_1
```

### React to a button press

```yaml
alias: Doorbell notification
triggers:
  - trigger: state
    entity_id: binary_sensor.teletask_my_teletask_62_42
    to: "on"
actions:
  - service: notify.mobile_app_your_phone
    data:
      message: "Someone is at the door!"
```

### Close blinds at sunset

```yaml
alias: Close blinds at sunset
triggers:
  - trigger: sun
    event: sunset
actions:
  - service: cover.close_cover
    target:
      entity_id: cover.teletask_my_teletask_6_1
```

---

## Architecture

```
Home Assistant
     │
     │  TCP (binary protocol, port 55957)
     ▼
Teletask Central Unit
(MICROS+ / NANOS / PICOS)
```

The integration maintains a persistent TCP connection and receives **real-time push updates** from the central unit whenever a component state changes. There is no polling. On disconnect, it automatically reconnects every 30 seconds.

---

## Comparison with jeletask

| Feature | jeletask (MQTT bridge) | This integration |
|---|---|---|
| MQTT broker required | ✅ Yes | ❌ No |
| Java / Docker required | ✅ Yes | ❌ No |
| HACS installable | Via custom repo | ✅ Yes |
| Auto-discovery in HA | Via MQTT discovery | ✅ Native config flow |
| Real-time updates | ✅ Yes (via MQTT) | ✅ Yes (direct TCP) |
| Admin web interface | ✅ Yes | ❌ No (use HA UI) |
| DISPLAYMESSAGE | ✅ Yes | 🚧 Not yet |
| TEMPERATURECONTROL | ✅ Yes | 🚧 Not yet |
| Config format | `config.json` file | Same JSON, pasted in UI |

---

## Requirements

- Teletask **MICROS+** (tested), NANOS or PICOS (untested, should work)
- **TDS15132 TCP licence** from Teletask — required for TCP API access
- Home Assistant **2023.1** or newer

---

## Contributing

Pull requests are welcome. To add support for `DISPLAYMESSAGE` or `TEMPERATURECONTROL (HVAC)`, the relevant protocol bytes are documented in [jeletask's MESSAGES.md](https://github.com/ridiekel/jeletask/blob/master/MESSAGES.md) and [Teletask's TDS15132 PDF](https://teletask.be/media/3109/tds15132-library.pdf).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
