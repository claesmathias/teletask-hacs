# Teletask — Native Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **native** Home Assistant custom integration for [Teletask](https://www.teletask.be/) domotics central units.  
Connects directly over TCP — **no MQTT broker, no Java bridge, no Docker container required**.

> Inspired by the excellent [jeletask](https://github.com/ridiekel/jeletask) project, this integration implements the same Teletask binary TCP protocol natively inside Home Assistant.

---

## Supported platforms

| Teletask component | HA platform | `hatype` value | Notes |
|---|---|---|---|
| `RELAY` | `light` | `light` | On/off relay — default when `hatype` is omitted |
| `RELAY` | `switch` | `switch` | On/off relay as a switch |
| `RELAY` | `button` | `button` | Momentary dry-contact pulse; configure duration with `pulse_ms` |
| `DIMMER` | `light` | *(always light)* | Brightness 0–100% |
| `MOTOR` | `cover` | *(always cover)* | UP / DOWN / STOP + set position 0–100 |
| `LOCMOOD` | `scene` | `scene` | Activate only |
| `LOCMOOD` | `switch` | `switch` | On/off toggle |
| `GENMOOD` | `scene` | `scene` | Activate only |
| `GENMOOD` | `switch` | `switch` | On/off toggle |
| `TIMEDMOOD` | `scene` | `scene` | Activate only |
| `TIMEDMOOD` | `switch` | `switch` | On/off toggle |
| `FLAG` | `switch` | `switch` or `input_boolean` | Boolean flag |
| `SENSOR` | `sensor` | *(always sensor)* | Temperature, humidity, light, gas, pulse counter |
| `COND` | `binary_sensor` | *(always binary sensor)* | Teletask condition |
| `INPUT` | `binary_sensor` | *(always binary sensor)* | Digital inputs / buttons with press-type attributes |
| `TIMEDFNC` | `switch` | `switch` | On/off toggle |
| `TIMEDFNC` | `scene` | `scene` | Activate only (pulse/trigger) |

---

## Requirements

- Teletask **MICROS+** (tested), NANOS or PICOS
- **TDS15132 TCP licence** from Teletask — required for TCP API access
- Home Assistant **2023.1** or newer

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

Setup is split into two steps:

### Step 1 — Connection

| Field | Description | Default |
|---|---|---|
| **IP Address** | IP of your Teletask central unit | — |
| **Port** | TCP port of the central unit | `55957` |
| **Central Unit ID** | A unique name for this unit (used in entity IDs) | `my_teletask` |

The integration tests the TCP connection before proceeding. If the hostname cannot be resolved or the TCP handshake fails, you will see a specific error message.

### Step 2 — Configuration file

| Field | Description |
|---|---|
| **Path to config.json** | Absolute or relative path to your component config file on the HA server |

Place your `config.json` somewhere inside your HA `/config/` directory, for example:

```
/config/teletask/config.json
```

Relative paths (e.g. `teletask/config.json`) are resolved from `/config/` automatically. Paths outside `/config/` are rejected for security.

> **Tip:** Use the **File Editor** or **Studio Code Server** add-on to create and edit the file directly in the HA UI.

### Updating the config after setup

Go to **Settings → Devices & Services → Teletask → Configure** to:

- Point to a different or updated `config.json`
- Toggle **debug logging** (verbose TCP protocol output in the HA log)

After saving, the integration reloads and picks up the new config immediately — no restart needed.

---

## config.json reference

The file follows the same structure as [jeletask](https://github.com/ridiekel/jeletask).

### Top-level structure

```json
{
  "type": "PICOS",
  "componentsTypes": {
    "RELAY":    [ ... ],
    "DIMMER":   [ ... ],
    "MOTOR":    [ ... ],
    "SENSOR":   [ ... ],
    "LOCMOOD":  [ ... ],
    "GENMOOD":  [ ... ],
    "TIMEDMOOD":[ ... ],
    "FLAG":     [ ... ],
    "INPUT":    [ ... ],
    "TIMEDFNC": [ ... ],
    "COND":     [ ... ]
  }
}
```

**`type`** — your central unit model: `MICROS_PLUS`, `NANOS`, or `PICOS`. Informational only.

Every entry inside a component list shares these common fields:

| Field | Required | Description |
|---|---|---|
| `number` | Yes | Teletask component number |
| `description` | Yes | Friendly name shown in HA |
| `hatype` | Depends | HA platform to use (see per-type details below) |
| `area` | No | HA area to assign this device to on first registration |

---

### RELAY

Relays can be mapped to three different HA platforms depending on the wiring purpose.

#### Light (default)

```json
{ "number": 1, "description": "Living Room Ceiling", "hatype": "light", "area": "Living Room" }
```

Omitting `hatype` defaults to `light`.

#### Switch

```json
{ "number": 8, "description": "Garden Shed Socket", "hatype": "switch", "area": "Garden" }
```

#### Button (momentary dry-contact)

Use this for relays wired to devices that expect a brief contact closure — garage doors, electric strikes, doorbells, etc.

```json
{ "number": 16, "description": "Garage Door", "hatype": "button", "pulse_ms": 500, "area": "Garage" }
```

| Field | Default | Description |
|---|---|---|
| `pulse_ms` | `500` | How long (in milliseconds) the relay stays closed when the button is pressed |

Pressing the button in HA closes the relay for `pulse_ms` milliseconds then opens it automatically — no manual off command needed.

---

### DIMMER

All dimmers become HA `light` entities with full brightness control.

```json
{ "number": 1, "description": "Living Room", "hatype": "light", "area": "Living Room" }
```

- Brightness is scaled between Teletask 0–100% and HA 0–255.
- Turning on without specifying brightness restores the **previous brightness level** (Teletask PREVIOUS_STATE).

---

### MOTOR

All motors become HA `cover` entities (device class: blind).

```json
{ "number": 1, "description": "Living Room Blinds", "area": "Living Room" }
```

Supported features:
- **Open** (UP)
- **Close** (DOWN)
- **Stop**
- **Set position** 0–100 (100 = fully open)

---

### LOCMOOD / GENMOOD / TIMEDMOOD

Moods can be either a `scene` (activate only) or a `switch` (on/off toggle).

```json
"LOCMOOD": [
  { "number": 1, "description": "Watch TV",     "hatype": "scene"  },
  { "number": 2, "description": "Reading Mode", "hatype": "switch" }
],
"GENMOOD": [
  { "number": 1, "description": "All Off",      "hatype": "scene"  },
  { "number": 2, "description": "Away Mode",    "hatype": "switch" }
]
```

Use `scene` when you only ever want to trigger/activate the mood (the typical case). Use `switch` if you need to be able to explicitly turn it off as well.

---

### FLAG

Flags are boolean states on the central unit, useful for logic or presence simulation.

```json
{ "number": 4, "description": "Holiday Mode",   "hatype": "switch"        },
{ "number": 5, "description": "Astro Timer",    "hatype": "input_boolean" }
```

Both `switch` and `input_boolean` map to the same HA `switch` entity — use whichever label makes more sense for your use case.

---

### SENSOR

Sensors require a `type` field to select the correct device class and unit.

```json
"SENSOR": [
  {
    "number": 3,
    "description": "Living Room Temperature",
    "type": "TEMPERATURE",
    "decimals": "1",
    "ha_unit_of_measurement": "°C",
    "area": "Living Room"
  },
  { "number": 1, "description": "Daylight Sensor", "type": "LIGHT",    "area": "Garden"  },
  { "number": 2, "description": "Humidity",        "type": "HUMIDITY", "area": "Bathroom" }
]
```

| `type` value | HA device class | Unit |
|---|---|---|
| `TEMPERATURE` | `temperature` | `°C` |
| `HUMIDITY` | `humidity` | `%` |
| `LIGHT` | `illuminance` | `lx` |
| `GAS` | *(none)* | *(none)* |
| `PULSECOUNTER` | `energy` | *(none)* |
| `TEMPERATURECONTROL` | `temperature` | `°C` |

| Field | Description |
|---|---|
| `decimals` | Number of decimal places the central sends (informational, used by some central types) |
| `ha_unit_of_measurement` | Override the default unit shown in HA (e.g. `"°C"`, `"%"`) |

---

### INPUT

Digital inputs (buttons, door contacts, motion detectors) become `binary_sensor` entities.

```json
{ "number": 42, "description": "Front Doorbell",   "area": "Entry Hall" },
{ "number": 43, "description": "Front Door Contact","area": "Entry Hall" }
```

The sensor is `on` when the input is active (CLOSED, SHORT_PRESS, or LONG_PRESS). Two extra state attributes are available for automations:

| Attribute | Description |
|---|---|
| `raw_state` | Raw state string: `OPEN`, `CLOSED`, `SHORT_PRESS`, `LONG_PRESS` |
| `press_duration_millis` | Duration of the press in milliseconds (when available) |

**Example — react differently to short vs long press:**

```yaml
alias: Staircase light — short/long press
triggers:
  - trigger: state
    entity_id: binary_sensor.teletask_my_teletask_62_42
    to: "on"
actions:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ trigger.to_state.attributes.raw_state == 'SHORT_PRESS' }}"
        sequence:
          - service: light.toggle
            target:
              entity_id: light.staircase
      - conditions:
          - condition: template
            value_template: "{{ trigger.to_state.attributes.raw_state == 'LONG_PRESS' }}"
        sequence:
          - service: scene.turn_on
            target:
              entity_id: scene.all_off
```

---

### COND

Conditions become `binary_sensor` entities. They are `on` when the condition is active.

```json
{ "number": 1, "description": "Alarm Active" }
```

---

### TIMEDFNC

Timed functions can be `switch` (on/off) or `scene` (activate/pulse only).

```json
{ "number": 3, "description": "Staircase Timer", "hatype": "switch" },
{ "number": 4, "description": "Hallway Pulse",   "hatype": "scene"  }
```

---

### Area assignment

Add an `"area"` field to any component to automatically place the device in an HA area when it is first registered:

```json
{ "number": 5, "description": "Dining Table", "hatype": "light", "area": "Dining Room" }
```

- The area is created automatically in HA if it does not exist yet.
- `area` only takes effect on **first registration**. If you later move a device to a different area via the HA UI, HA respects that choice — the config value will not override it again.
- To force re-assignment after an initial registration without an area: delete the device from **Settings → Devices & Services → [device] → Delete**, then restart HA so it re-registers with the area.

---

## Complete config.json example

```json
{
  "type": "PICOS",
  "componentsTypes": {
    "RELAY": [
      { "number": 1,  "description": "Garage Light",          "hatype": "light",  "area": "Garage"    },
      { "number": 5,  "description": "Dining Table Light",    "hatype": "light",  "area": "Dining Room" },
      { "number": 8,  "description": "Living Room Outlet",    "hatype": "switch", "area": "Living Room" },
      { "number": 16, "description": "Garage Door",           "hatype": "button", "pulse_ms": 500, "area": "Garage" }
    ],
    "DIMMER": [
      { "number": 1, "description": "Living Room",    "hatype": "light", "area": "Living Room" },
      { "number": 4, "description": "Master Bedroom", "hatype": "light", "area": "Master Bedroom" }
    ],
    "MOTOR": [
      { "number": 1, "description": "Living Room Blinds", "area": "Living Room" },
      { "number": 2, "description": "Bedroom Blinds",     "area": "Master Bedroom" }
    ],
    "SENSOR": [
      {
        "number": 3,
        "description": "Living Room Temperature",
        "type": "TEMPERATURE",
        "decimals": "1",
        "ha_unit_of_measurement": "°C",
        "area": "Living Room"
      }
    ],
    "LOCMOOD": [
      { "number": 1, "description": "Watch TV",        "hatype": "scene"  },
      { "number": 2, "description": "Romantic Dinner", "hatype": "scene"  }
    ],
    "GENMOOD": [
      { "number": 1, "description": "All Off",         "hatype": "scene"  },
      { "number": 2, "description": "Away Mode",       "hatype": "switch" }
    ],
    "FLAG": [
      { "number": 4, "description": "Holiday Mode",    "hatype": "switch" }
    ],
    "INPUT": [
      { "number": 42, "description": "Front Doorbell",    "area": "Entry Hall" },
      { "number": 43, "description": "Front Door Contact","area": "Entry Hall" }
    ],
    "TIMEDFNC": [
      { "number": 3, "description": "Staircase Timer", "hatype": "switch" }
    ],
    "COND": [
      { "number": 1, "description": "Alarm Active" }
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
light.teletask_my_teletask_1_1           → RELAY #1 (light)
light.teletask_my_teletask_2_1           → DIMMER #1
switch.teletask_my_teletask_1_8          → RELAY #8 (switch)
button.teletask_my_teletask_1_16         → RELAY #16 (button)
cover.teletask_my_teletask_6_1           → MOTOR #1
scene.teletask_my_teletask_8_1           → LOCMOOD #1
scene.teletask_my_teletask_9_1           → TIMEDMOOD #1
scene.teletask_my_teletask_10_1          → GENMOOD #1
switch.teletask_my_teletask_15_4         → FLAG #4
sensor.teletask_my_teletask_20_3         → SENSOR #3
binary_sensor.teletask_my_teletask_62_42 → INPUT #42
binary_sensor.teletask_my_teletask_60_1  → COND #1
```

The **friendly name** shown in the HA UI comes from the `description` field in your `config.json`.

---

## Automation examples

### Toggle a light

```yaml
service: light.turn_on
target:
  entity_id: light.teletask_my_teletask_1_1
```

### Set dimmer brightness

```yaml
service: light.turn_on
target:
  entity_id: light.teletask_my_teletask_2_1
data:
  brightness_pct: 60
```

### Activate a scene/mood

```yaml
service: scene.turn_on
target:
  entity_id: scene.teletask_my_teletask_8_1
```

### Trigger a momentary button (garage door)

```yaml
service: button.press
target:
  entity_id: button.teletask_my_teletask_1_16
```

### Set blind position

```yaml
service: cover.set_cover_position
target:
  entity_id: cover.teletask_my_teletask_6_1
data:
  position: 50
```

### React to a doorbell press

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

### Toggle holiday mode flag

```yaml
service: switch.turn_on
target:
  entity_id: switch.teletask_my_teletask_12_4
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

The integration maintains a **persistent TCP connection** and receives real-time push updates from the central unit whenever a component state changes — there is no polling. State is reflected in HA instantly.

On disconnect, the integration automatically reconnects every **30 seconds** and re-subscribes to all components.

Outgoing commands (turn on/off, set brightness, etc.) use **optimistic updates**: the local state is updated immediately so the HA UI responds without waiting for a push confirmation from the central.

---

## Comparison with jeletask

| Feature | jeletask (MQTT bridge) | This integration |
|---|---|---|
| MQTT broker required | Yes | No |
| Java / Docker required | Yes | No |
| HACS installable | Via custom repo | Yes |
| Auto-discovery in HA | Via MQTT discovery | Native config flow |
| Real-time updates | Yes (via MQTT) | Yes (direct TCP) |
| Admin web interface | Yes | No (use HA UI) |
| Config via file | `config.json` mounted in Docker | `/config/teletask/config.json` |
| Area assignment | No | Yes (`"area"` field in config) |
| Momentary relay button | No | Yes (`hatype: button` + `pulse_ms`) |
| DISPLAYMESSAGE | Yes | Not yet |
| TEMPERATURECONTROL (HVAC) | Yes | Not yet |

---

## Contributing

Pull requests are welcome. To add support for `DISPLAYMESSAGE` or `TEMPERATURECONTROL (HVAC)`, the relevant protocol bytes are documented in [jeletask's MESSAGES.md](https://github.com/ridiekel/jeletask/blob/master/MESSAGES.md) and the [Teletask TDS15132 PDF](https://teletask.be/media/3109/tds15132-library.pdf).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
