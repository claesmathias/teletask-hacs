# Teletask — Native Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.7%2B-blue.svg)](https://www.home-assistant.io/)
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
- Home Assistant **2025.7** or newer

---

## Documentation & test license

- [`docs/TDS LIBRARY V3.7.pdf`](<docs/TDS LIBRARY V3.7.pdf>) — the official Teletask TDS protocol library reference, included locally in this repo for convenience.
- [`docs/TELETASK Technical Handbook_EN_2019.01.24.pdf`](<docs/TELETASK Technical Handbook_EN_2019.01.24.pdf>) — the general TELETASK technical handbook.
- [`test-license/TT15132-TEST MODE LICENTIE.act`](<test-license/TT15132-TEST MODE LICENTIE.act>) — a TDS15132 **test mode** activation file. It unlocks the TCP API in TELETASK PROSOFT without a paid licence, for development/testing purposes only.

### Installing the test license in PROSOFT

1. Start the **TELETASK PROSOFT** software and open your project's `.NBT` file.
2. Navigate to the top menu and select **Extra → Licenses**.
3. Import the `TT15132-TEST MODE LICENTIE.act` file into the project.
4. Save the `.NBT` file and transmit the updated configuration to your central unit.

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

### Automatic discovery

Home Assistant discovers Teletask central units on your network through DHCP.
A discovered central appears under **Settings → Devices & Services** as
**Discovered**; click **Add** to start the setup below with its IP address
already filled in.

- Discovery recognises Teletask's registered MAC address ranges
  (`00:50:C2:6A:4x:xx`, `70:B3:D5:C5:6x:xx`, `E4:1E:0A:Cx:xx:xx`). Other
  Teletask products with a network port (touch screens, gateways) are ignored:
  only a device that answers on the control port (`55957`) is offered.
- The central must request its address by DHCP (the factory default,
  *Dynamic* in PROSOFT). A central with a static IP address is found when Home
  Assistant sees it on the network, or you can add it manually as before.
- Once a central is set up, a new DHCP address is picked up automatically and
  the integration reloads with it. If you entered a hostname instead of an IP
  address, the hostname is kept.
- Discovery requires Home Assistant's `dhcp` integration, which is part of
  `default_config`.

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

Relative paths (e.g. `teletask/config.json`) are resolved from your HA configuration folder (`/config/` inside the HA container) automatically. Paths outside it are rejected for security.

> **Docker users:** `/config` is whatever host folder you mount there. If you mount `~/homeassistant` to `/config` and keep the file in `~/homeassistant/config/teletask/`, the path is `/config/config/teletask/config.json`.

The path is remembered. The file is re-read every time the integration loads.

### Updating the config after setup

**Edited the file?** Just reload: **Settings → Devices & Services → Teletask → ⋮ → Reload** (or restart HA). The integration re-reads the linked `config.json`.

If the file is missing or invalid, the integration keeps running on the **last successfully loaded** configuration and shows a notification explaining what's wrong. Fix the file and reload again.

**Settings → Devices & Services → Teletask → Configure** opens a menu:

| Option | What it does |
|---|---|
| **Edit components** | Pick a component type (e.g. *Relays (24)*) to get Home Assistant's list editor: click a component to edit it in a form, **Add** a new one, or delete one. The form has a number box, name, a dropdown with only the valid `hatype` values for that type, an area dropdown (your HA areas, or type a new one), and type-specific fields such as the relay button's pulse length or the sensor type. Edit several types, then choose **Save changes and reload**. |
| **Edit as YAML (advanced)** | The full configuration in Home Assistant's code editor (YAML, syntax highlighting). If the file has an error, it opens the last successfully loaded version so you can repair it here. |
| **Reload from file** | Re-reads `config.json` (path pre-filled) and reloads. Enter a different path to link another file. |
| **Settings** | Toggle **debug logging** (verbose TCP protocol output in the HA log). |

Both editors check the configuration before saving, write it to the linked
file as JSON with one component per line (the previous version is kept as
`config.json.bak`), and reload. No file editor add-on needed. Keys the forms
don't show are preserved.

Every load checks the configuration first. JSON syntax errors are reported with line and column. Structure problems are named, e.g. an unknown type such as `LOCMOD`, a duplicate `number`, or a missing `number`.

> **Entity IDs are kept** across reloads and edits as long as a component keeps its **type** (e.g. `LOCMOOD`) and **number**. Renaming a `description` changes only the display name. Changing a component's type, number or `hatype` creates a new entity, which breaks HomeKit/Alexa references to the old one.

> **Upgrading from 1.6 or earlier:** existing installs don't have a remembered path yet. Run **Configure → Reload from file** once with your file's path to link it.

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

## Central unit device

The integration creates a device for the central unit itself. Every component
device is linked to it ("Connected via"). Its details come from the central's
built-in support web page (`http://<host>/cgi-bin/serial.cgi` and `time.cgi`),
which is read every 5 minutes:

| Device field | Source |
|---|---|
| Model | unit type (e.g. `PICOS`) |
| Serial number | serial number |
| Firmware | installed PROSOFT version |
| Hardware | disk version |
| MAC (connection) | MAC address |
| Visit link | `http://<host>/` |

It also exposes these **diagnostic** entities:

| Entity | Source | Description |
|---|---|---|
| `Connection` | control connection | **Connected** / **Disconnected**: whether the TCP connection that switches outputs and receives state changes (port 55957) is up. While disconnected, the integration retries every 30 s. Attributes: `host`, `port`. |
| `Last event` | control connection | When the central last reported a state change (any output, input, mood, …). The first event after a start or reload shows immediately; after that it updates at most once a minute, so it can lag by up to 60 s. |
| `Clock` | web page | The central's own clock (timestamp) |
| `Clock offset` | web page | Seconds the central's clock runs ahead (+) or behind (−) Home Assistant. Timed functions run on this clock, so watch it for drift. |
| `Project file` | web page | PROSOFT `.nbt` project currently loaded; attributes include the owner, type code and OS date |

`Connection` and `Last event` follow the control connection directly. The web
page sensors are a separate service on port 80, polled every 5 minutes: they can
look fine while control is down, and the reverse.

### When the connection is lost

- The integration retries every **30 seconds**, indefinitely.
- After **5 minutes** without a connection, a **Repairs** entry appears
  (**Settings → System → Repairs**: *Teletask central unit unreachable*). It
  shows since when, the host and port, and the last error. It **clears itself**
  on reconnect. Shorter blips, such as a central reboot, never raise it.
- The log gets **one warning when the outage starts and one when it ends**,
  e.g. `Reconnected to Teletask central at 192.168.11.73:55957 after 12m 5s (24
  reconnect attempts)`. Individual retries are only logged with debug logging on.

Repairs entries don't send push notifications. For a phone alert, use the
`Connection` sensor in an automation:

```yaml
automation:
  - alias: Teletask central disconnected
    triggers:
      - trigger: state
        entity_id: binary_sensor.teletask_picos_my_teletask_connection  # check yours
        to: "off"
        for: "00:05:00"
    actions:
      - action: notify.notify
        data:
          title: Teletask
          message: Lost connection to the central unit for 5 minutes.
```

The central prints its time without a usable timezone, so it is read in Home
Assistant's configured timezone. If the web page can't be reached, setup still
continues and the web page sensors show as unavailable.

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

### Local development

Run the integration in a throwaway Home Assistant in Docker, against a fake
central, without touching your real installation:

```bash
# 1. Fake central (Teletask protocol on 55957, support web page on 80)
python3 tools/fake_central.py

# 2. Dev Home Assistant on http://localhost:8124 (separate terminal)
mkdir -p .ha-dev/config/teletask && cp config.json .ha-dev/config/teletask/
docker compose -f docker-compose.dev.yml up -d
```

Open http://localhost:8124, create a user, then add the **Teletask**
integration with host `host.docker.internal`, port `55957`, and config file
`teletask/config.json`.

- The integration code is mounted from `custom_components/teletask`. After a
  code change: `docker compose -f docker-compose.dev.yml restart`.
- Simulate an outage by stopping the fake central (Ctrl+C) and start it again
  to reconnect. The Repairs entry appears after 5 minutes.
- To test against the real central, use its IP instead. That HA instance
  then controls your real outputs.
- Logs: `docker compose -f docker-compose.dev.yml logs -f`
- Everything lives in `.ha-dev/` (git-ignored); delete it to start over.

Offline unit tests (no HA or central needed):

```bash
pytest tests/test_configfile.py tests/test_entities.py tests/test_webinfo.py
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
