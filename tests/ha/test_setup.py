"""Set the integration up in a real Home Assistant against a fake central.

Needs pytest-homeassistant-custom-component (Python 3.13) and must run in its
own session, because tests/test_entities.py replaces homeassistant with stubs:

    pytest tests/ha
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

DOMAIN = "teletask"
CID = "test"

CONFIG = {
    "componentsTypes": {
        "RELAY": [{"number": 1, "description": "Hall"}],
        "SENSOR": [
            {"number": 2, "description": "Living", "type": "TEMPERATURECONTROL", "fan": True},
            {"number": 3, "description": "Bathroom humidity", "type": "HUMIDITY"},
        ],
        "DISPLAYMESSAGE": [{
            "number": 1000, "description": "Panels", "bus_numbers": "1,1", "address_numbers": "13,5",
            "message_type": "message", "message_beeps": 2,
        }],
        "INPUT": [{"number": 4, "description": "Door button"}],
        "TIMEDFNC": [{"number": 5, "description": "Garden timer"}],
        "AUDIO": [{"number": 1, "description": "Kitchen audio", "sources": "Radio, Spotify"}],
        "RGB": [{"number": 6, "description": "Strip"}],
        "TW": [{"number": 7, "description": "Office"}],
        "MOTOR": [{"number": 1, "description": "Blind", "tilt": True, "sun_protection": True}],
        "PROCES": [{"number": 8, "description": "Pump"}],
        "ACCESS": [{"number": 1, "description": "Front reader"}],
    }
}

# State bytes the fake central reports per (function, number).
CLIMATE = bytes([0x0B, 0x86, 0x0B, 0x9A, 0x0B, 0xA4, 0x0B, 0x72, 30, 26, 95, 98, 255, 0, 8, 0, 0x0B, 0xB8])
STATES = {
    (20, 2): CLIMATE,
    (20, 3): bytes([0x00, 53]),
    (52, 4): bytes([3]),
    (5, 5): bytes([0xFF]),
    (31, 1): bytes([39, 40, 0]),
    (217, 6): bytes([255, 0, 0]),
    (220, 7): bytes([0x0A, 0x8C, 0x19, 0x64, 0x0F, 0xA0, 50]),
    (6, 1): bytes([1, 0, 0x14, 50, 50]),
    (3, 8): bytes([0]),
}


def _frame(payload: bytes) -> bytes:
    msg = bytes([0x02, len(payload) + 2]) + payload
    return msg + bytes([sum(msg) & 0xFF])


def _event(fn: int, num: int, state: bytes) -> bytes:
    return _frame(bytes([0x10, 1, fn, num >> 8, num & 0xFF, 0]) + state)


class FakeCentral:
    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.server: asyncio.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self.writers:
            writer.close()
        self.server.close()
        await self.server.wait_closed()

    def push(self, data: bytes) -> None:
        for writer in self.writers:
            writer.write(data)

    def frames(self, command: int) -> list[bytes]:
        return [f for f in self.received if f[2] == command]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        buf = b""
        while data := await reader.read(1024):
            buf += data
            while len(buf) >= 2 and len(buf) >= buf[1] + 1:
                total = buf[1] + 1
                frame, buf = buf[:total], buf[total:]
                self.received.append(frame)
                writer.write(b"\x0a")
                cmd, body = frame[2], frame[3:-1]
                if cmd == 0x06:
                    key = (body[1], (body[2] << 8) | body[3])
                    if key in STATES:
                        writer.write(_event(*key, STATES[key]))
                elif cmd == 0x09:
                    fn = body[1]
                    for i in range(2, len(body) - 1, 2):
                        key = (fn, (body[i] << 8) | body[i + 1])
                        if key in STATES:
                            writer.write(_event(*key, STATES[key]))
            await writer.drain()


@pytest.fixture
async def central(socket_enabled):
    fake = FakeCentral()
    port = await fake.start()
    fake.port = port
    yield fake
    await fake.stop()


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def _no_web_page():
    async def fail(self):
        raise UpdateFailed("no web page in tests")

    with patch("custom_components.teletask.hub.TeletaskHub._async_fetch_web", fail):
        yield


def _entry(port: int, minor_version: int = 2) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=CID,
        version=1,
        minor_version=minor_version,
        data={
            "host": "127.0.0.1", "port": port, "central_id": CID,
            "config_json": json.dumps(CONFIG),
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(2)  # the hub's subscribe waits 1.5 s for replies
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"no {domain} entity with unique id {unique_id}"
    return entity_id


async def test_setup_creates_all_entities(hass: HomeAssistant, central) -> None:
    await _setup(hass, _entry(central.port))

    climate = hass.states.get(_entity_id(hass, "climate", f"teletask_{CID}_20_2"))
    assert climate.state == "heat"
    assert climate.attributes["current_temperature"] == 22.0
    assert climate.attributes["temperature"] == 24.0
    assert climate.attributes["preset_mode"] == "day"
    assert climate.attributes["fan_mode"] == "medium"
    assert climate.attributes["hvac_action"] == "heating"

    day = hass.states.get(_entity_id(hass, "number", f"teletask_{CID}_20_2_day_preset"))
    assert float(day.state) == 25.0

    humidity = hass.states.get(_entity_id(hass, "sensor", f"teletask_{CID}_20_3"))
    assert float(humidity.state) == 53  # not decoded as a temperature

    timed = hass.states.get(_entity_id(hass, "switch", f"teletask_{CID}_5_5"))
    assert timed.state == "on"

    audio = hass.states.get(_entity_id(hass, "media_player", f"teletask_{CID}_31_1"))
    assert audio.state == "on"
    assert audio.attributes["source"] == "Spotify"
    assert audio.attributes["source_list"] == ["Radio", "Spotify"]
    assert audio.attributes["volume_level"] == 0.4

    rgb = hass.states.get(_entity_id(hass, "light", f"teletask_{CID}_217_6"))
    assert rgb.state == "on"
    assert rgb.attributes["rgb_color"] == (255, 0, 0)

    tw = hass.states.get(_entity_id(hass, "light", f"teletask_{CID}_220_7"))
    assert tw.attributes["color_temp_kelvin"] == 4000
    assert tw.attributes["min_color_temp_kelvin"] == 2700

    cover = hass.states.get(_entity_id(hass, "cover", f"teletask_{CID}_6_1"))
    assert cover.attributes["current_position"] == 50
    sun = hass.states.get(_entity_id(hass, "switch", f"teletask_{CID}_6_1_sun_protection"))
    assert sun.state == "on"

    assert hass.states.get(_entity_id(hass, "switch", f"teletask_{CID}_3_8")).state == "off"
    assert hass.states.get(_entity_id(hass, "notify", f"teletask_{CID}_54_1000"))
    assert hass.states.get(_entity_id(hass, "event", f"teletask_{CID}_52_4_press"))
    assert hass.states.get(_entity_id(hass, "event", f"teletask_{CID}_202_1"))

    # Badge reports need the per-device subscription; display messages are never asked for.
    assert any(f[4] == 202 for f in central.frames(0x22))
    assert not any(f[4] == 54 for f in central.frames(0x06) + central.frames(0x09))


async def test_display_message(hass: HomeAssistant, central) -> None:
    await _setup(hass, _entry(central.port))
    notify_id = _entity_id(hass, "notify", f"teletask_{CID}_54_1000")

    await hass.services.async_call(
        "notify", "send_message",
        {"entity_id": notify_id, "message": "Someone is at the front door"}, blocking=True,
    )
    await asyncio.sleep(0.1)
    frame = central.frames(0x04)[-1]
    assert list(frame[3:8]) == [1, 1, 1, 13, 5]   # central, buses, addresses
    assert frame[8] == 1 and frame[9] == 1         # message, ascii (all text is ASCII)
    assert frame[10:26] == b"Someone is at   "
    assert frame[26:42] == b"the front door  "
    assert frame[42] == 2                          # default beeps from config.json

    await hass.services.async_call(
        DOMAIN, "send_display_message",
        {"entity_id": notify_id, "line1": "Café", "line2": "Open", "message_type": "alarm", "beeps": 5},
        blocking=True,
    )
    await asyncio.sleep(0.1)
    frame = central.frames(0x04)[-1]
    assert frame[8] == 0 and frame[9] == 0         # alarm, unicode (é)
    assert frame[10:26] == "Café    ".encode("utf-16-be")
    assert frame[42] == 5


async def test_climate_commands(hass: HomeAssistant, central) -> None:
    await _setup(hass, _entry(central.port))
    climate_id = _entity_id(hass, "climate", f"teletask_{CID}_20_2")

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": climate_id, "temperature": 21.5}, blocking=True,
    )
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": climate_id, "preset_mode": "night"}, blocking=True,
    )
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate_id, "hvac_mode": "cool"}, blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": _entity_id(hass, "number", f"teletask_{CID}_20_2_day_preset"), "value": 21},
        blocking=True,
    )
    await asyncio.sleep(0.1)
    sets = [list(f[4:-1]) for f in central.frames(0x07)]
    assert [20, 0, 2, 87, 0x0B, 0x81] in sets      # manual target 21.5 °C = 2945
    assert [20, 0, 2, 25] in sets                  # preset night
    assert [20, 0, 2, 96] in sets                  # mode cool
    assert [20, 0, 2, 29, 122] in sets             # day preset (21 + 40) × 2


async def test_push_button_events(hass: HomeAssistant, central) -> None:
    await _setup(hass, _entry(central.port))
    event_id = _entity_id(hass, "event", f"teletask_{CID}_52_4_press")
    assert hass.states.get(event_id).state == "unknown"  # the subscribe replay is not a press

    central.push(_event(52, 4, bytes([1])))
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    state = hass.states.get(event_id)
    assert state.attributes["event_type"] == "short_press"

    button = hass.states.get(_entity_id(hass, "binary_sensor", f"teletask_{CID}_52_4"))
    assert button.state == "on"


async def test_access_report(hass: HomeAssistant, central) -> None:
    await _setup(hass, _entry(central.port))
    payload = bytes([0x14, 0x00, 0, 0, 0, 7, 0, 0, 0x65, 0x5F, 0, 0, 3]) + b"Ann" + bytes([5]) + b"Front"
    central.push(_frame(payload))
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    state = hass.states.get(_entity_id(hass, "event", f"teletask_{CID}_202_1"))
    assert state.attributes["event_type"] == "denied"
    assert state.attributes["card_id"] == 7
    assert state.attributes["user"] == "Ann"


async def test_migration_renames_input_and_timed_function_ids(hass: HomeAssistant, central) -> None:
    entry = _entry(central.port, minor_version=1)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    old_timed = ent_reg.async_get_or_create("switch", DOMAIN, f"teletask_{CID}_52_5", config_entry=entry)
    old_button = ent_reg.async_get_or_create("binary_sensor", DOMAIN, f"teletask_{CID}_62_4", config_entry=entry)
    device = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{CID}_62_4")})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert ent_reg.async_get(old_timed.entity_id).unique_id == f"teletask_{CID}_5_5"
    assert ent_reg.async_get(old_button.entity_id).unique_id == f"teletask_{CID}_52_4"
    assert dev_reg.async_get(device.id).identifiers == {(DOMAIN, f"{CID}_52_4")}
