"""Unit tests for entity event-listener behavior — no live HA or central required.

Tests verify that TeletaskScene and TeletaskMomentaryButton correctly update the
HA state machine (async_write_ha_state) and fire teletask_event bus events when
the TeleTask central pushes state changes.

Run with:
    pytest tests/test_entities.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock all homeassistant modules before loading entity modules.
# Entity modules use relative imports, so we also need to register the
# custom_components.teletask package in sys.modules.
# ---------------------------------------------------------------------------

TELETASK_PATH = Path(__file__).parent.parent / "custom_components" / "teletask"

# HA's @callback decorator is a passthrough in tests.
def _callback(f):
    return f

# Minimal Entity base so subclassing works without the full HA stack.
class _Entity:
    _attr_should_poll = False
    _attr_state = None
    _attr_unique_id = None
    _attr_name = None
    _attr_device_info = None

    def async_on_remove(self, func):
        pass

    def async_write_ha_state(self):
        pass


class _Scene(_Entity):
    @property
    def state(self):
        return "scening"

    def _async_record_activation(self):
        pass

    async def async_added_to_hass(self):
        pass


# Build module stubs.
_mod_core = types.ModuleType("homeassistant.core")
_mod_core.callback = _callback
_mod_core.HomeAssistant = MagicMock
_mod_core.CALLBACK_TYPE = object

_mod_const = types.ModuleType("homeassistant.const")
_mod_const.STATE_UNKNOWN = "unknown"
_mod_const.STATE_UNAVAILABLE = "unavailable"
_mod_const.EntityCategory = types.SimpleNamespace(DIAGNOSTIC="diagnostic")
_mod_const.LIGHT_LUX = "lx"
_mod_const.PERCENTAGE = "%"
_mod_const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
_mod_const.UnitOfTime = types.SimpleNamespace(SECONDS="s")

from datetime import datetime, timezone as _tz
_mod_util = types.ModuleType("homeassistant.util")
_mod_util.dt = types.ModuleType("homeassistant.util.dt")
_mod_util.dt.parse_datetime = MagicMock(return_value=None)
_mod_util.dt.utcnow = MagicMock(return_value=datetime(2026, 1, 1, tzinfo=_tz.utc))
_mod_util.dt.as_local = lambda value: value

_mod_entity = types.ModuleType("homeassistant.helpers.entity")
_mod_entity.Entity = _Entity
_mod_entity.DeviceInfo = dict  # DeviceInfo is dict-compatible in entity code

_mod_dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
_mod_dispatcher.async_dispatcher_connect = MagicMock(return_value=lambda: None)
_mod_dispatcher.async_dispatcher_send = MagicMock()

_mod_scene_pkg = types.ModuleType("homeassistant.components.scene")
_mod_scene_pkg.Scene = _Scene

_mod_switch_pkg = types.ModuleType("homeassistant.components.switch")
_mod_switch_pkg.SwitchEntity = _Entity

_mod_binary_sensor_pkg = types.ModuleType("homeassistant.components.binary_sensor")
_mod_binary_sensor_pkg.BinarySensorEntity = type("_BinarySensorEntity", (_Entity,), {})
_mod_binary_sensor_pkg.BinarySensorDeviceClass = MagicMock()

_mod_sensor_pkg = types.ModuleType("homeassistant.components.sensor")
_mod_sensor_pkg.SensorEntity = type("_SensorEntity", (_Entity,), {})
_mod_sensor_pkg.SensorDeviceClass = MagicMock()
_mod_sensor_pkg.SensorStateClass = MagicMock()

_mod_issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
_mod_issue_registry.async_create_issue = MagicMock()
_mod_issue_registry.async_delete_issue = MagicMock()
_mod_issue_registry.IssueSeverity = types.SimpleNamespace(ERROR="error")

_mod_event = types.ModuleType("homeassistant.helpers.event")
_mod_event.async_call_later = MagicMock()

_mod_config_entries = types.ModuleType("homeassistant.config_entries")
_mod_config_entries.ConfigEntry = MagicMock

_mod_entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
_mod_entity_platform.AddEntitiesCallback = MagicMock

_mod_device_registry = types.ModuleType("homeassistant.helpers.device_registry")
_mod_device_registry.CONNECTION_NETWORK_MAC = "mac"
_mod_device_registry.DeviceInfo = type("DeviceInfo", (dict,), {"__annotations__": {"via_device_id": str}})
_mod_device_registry.async_get = MagicMock()

_mod_aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
_mod_aiohttp_client.async_get_clientsession = MagicMock()

class _DataUpdateCoordinator:
    def __init__(self, *args, **kwargs):
        self.data = None

_mod_update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
_mod_update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
_mod_update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
class _CoordinatorEntity(_Entity):
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator

_mod_update_coordinator.CoordinatorEntity = _CoordinatorEntity

_mod_aiohttp = types.ModuleType("aiohttp")
_mod_aiohttp.ClientTimeout = MagicMock()
_mod_aiohttp.ClientError = type("ClientError", (Exception,), {})

_HA_MOCKS = {
    "aiohttp":                               _mod_aiohttp,
    "homeassistant.helpers.device_registry": _mod_device_registry,
    "homeassistant.helpers.aiohttp_client":  _mod_aiohttp_client,
    "homeassistant.helpers.update_coordinator": _mod_update_coordinator,
    "homeassistant":                         types.ModuleType("homeassistant"),
    "homeassistant.core":                    _mod_core,
    "homeassistant.const":                   _mod_const,
    "homeassistant.util":                    _mod_util,
    "homeassistant.util.dt":                 _mod_util.dt,
    "homeassistant.helpers":                 types.ModuleType("homeassistant.helpers"),
    "homeassistant.helpers.entity":          _mod_entity,
    "homeassistant.helpers.dispatcher":      _mod_dispatcher,
    "homeassistant.helpers.entity_platform": _mod_entity_platform,
    "homeassistant.components":              types.ModuleType("homeassistant.components"),
    "homeassistant.components.scene":        _mod_scene_pkg,
    "homeassistant.components.switch":       _mod_switch_pkg,
    "homeassistant.components.binary_sensor": _mod_binary_sensor_pkg,
    "homeassistant.components.sensor":       _mod_sensor_pkg,
    "homeassistant.helpers.event":           _mod_event,
    "homeassistant.helpers.issue_registry":  _mod_issue_registry,
    "homeassistant.config_entries":          _mod_config_entries,
}
for _name, _mod in _HA_MOCKS.items():
    sys.modules.setdefault(_name, _mod)

# Register the package so relative imports (from .client import …) work.
_pkg = types.ModuleType("custom_components")
_pkg_tt = types.ModuleType("custom_components.teletask")
sys.modules.setdefault("custom_components", _pkg)
sys.modules.setdefault("custom_components.teletask", _pkg_tt)


def _load_teletask_module(stem: str):
    """Load a module from the custom_components/teletask directory."""
    fqn = f"custom_components.teletask.{stem}"
    if fqn in sys.modules:
        return sys.modules[fqn]
    spec = importlib.util.spec_from_file_location(fqn, TELETASK_PATH / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "custom_components.teletask"
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)
    return mod


_client_mod = _load_teletask_module("client")
_const_mod  = _load_teletask_module("const")
_webinfo_mod = _load_teletask_module("webinfo")
_hub_mod    = _load_teletask_module("hub")
_entity_mod = _load_teletask_module("entity")
_scene_mod  = _load_teletask_module("scene")
_switch_mod = _load_teletask_module("switch")
_binary_sensor_mod = _load_teletask_module("binary_sensor")
_sensor_mod = _load_teletask_module("sensor")

TeletaskScene           = _scene_mod.TeletaskScene
TeletaskMomentaryButton = _switch_mod.TeletaskMomentaryButton
FunctionCode            = _client_mod.FunctionCode
TELETASK_EVENT          = _const_mod.TELETASK_EVENT
SIGNAL_STATE_UPDATED    = _const_mod.SIGNAL_STATE_UPDATED


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_hub(central_id: str = "1", cached_state: dict | None = None) -> MagicMock:
    hub = MagicMock()
    hub.central_id = central_id
    hub.get_state = MagicMock(return_value=cached_state if cached_state is not None else {})
    hub.async_request_state = AsyncMock()
    return hub


def _make_scene(
    fn=FunctionCode.GENMOOD,
    number: int = 2,
    description: str = "Bedtime",
    cached: dict | None = None,
) -> tuple[TeletaskScene, MagicMock]:
    hub = _make_hub(cached_state=cached)
    comp = {
        "function": fn,
        "number": number,
        "description": description,
        "ha_type": "scene",
        "function_name": fn.name,
        "config": {},
        "area": "Living Room",
    }
    entity = TeletaskScene(hub, comp)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    entity._async_record_activation = MagicMock()
    entity.async_get_last_state = AsyncMock(return_value=None)
    return entity, hub


def _make_button(number: int = 16, pulse_ms: int = 500) -> tuple[TeletaskMomentaryButton, MagicMock]:
    hub = _make_hub()
    comp = {
        "function": int(FunctionCode.RELAY),
        "number": number,
        "description": "Garage Door",
        "ha_type": "button",
        "function_name": "RELAY",
        "config": {"pulse_ms": pulse_ms},
        "area": "Garage",
    }
    entity = TeletaskMomentaryButton(hub, comp)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity, hub


# ---------------------------------------------------------------------------
# TeletaskScene — state tracking
# ---------------------------------------------------------------------------

class TestTeletaskSceneState:
    def test_handle_update_on_calls_record_activation(self):
        entity, _ = _make_scene()
        entity._handle_state_update({"state": "ON"})
        entity._async_record_activation.assert_called_once()

    def test_handle_update_off_does_not_call_record_activation(self):
        entity, _ = _make_scene()
        entity._handle_state_update({"state": "OFF"})
        entity._async_record_activation.assert_not_called()

    def test_handle_update_missing_key_does_not_call_record_activation(self):
        entity, _ = _make_scene()
        entity._handle_state_update({})
        entity._async_record_activation.assert_not_called()

    def test_handle_update_calls_write_ha_state(self):
        entity, _ = _make_scene()
        entity._handle_state_update({"state": "ON"})
        entity.async_write_ha_state.assert_called_once()

    def test_handle_update_write_ha_state_also_on_off(self):
        entity, _ = _make_scene()
        entity._handle_state_update({"state": "OFF"})
        entity.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# TeletaskScene — bus event
# ---------------------------------------------------------------------------

class TestTeletaskSceneBusEvent:
    def test_fires_teletask_event_on_on(self):
        entity, _ = _make_scene(fn=FunctionCode.GENMOOD, number=2, description="Bedtime")
        entity._handle_state_update({"state": "ON"})
        entity.hass.bus.async_fire.assert_called_once_with(
            TELETASK_EVENT,
            {"function": "GENMOOD", "number": 2, "description": "Bedtime", "state": "ON"},
        )

    def test_fires_teletask_event_on_off(self):
        entity, _ = _make_scene(fn=FunctionCode.LOCMOOD, number=4, description="Watch Tv")
        entity._handle_state_update({"state": "OFF"})
        entity.hass.bus.async_fire.assert_called_once_with(
            TELETASK_EVENT,
            {"function": "LOCMOOD", "number": 4, "description": "Watch Tv", "state": "OFF"},
        )

    def test_fires_event_for_timedmood(self):
        entity, _ = _make_scene(fn=FunctionCode.TIMEDMOOD, number=1, description="Evening")
        entity._handle_state_update({"state": "ON"})
        args = entity.hass.bus.async_fire.call_args[0]
        assert args[1]["function"] == "TIMEDMOOD"

    def test_fires_event_for_timedfnc(self):
        entity, _ = _make_scene(fn=FunctionCode.TIMEDFNC, number=3, description="Night Mode")
        entity._handle_state_update({"state": "ON"})
        args = entity.hass.bus.async_fire.call_args[0]
        assert args[1]["function"] == "TIMEDFNC"

    def test_event_always_fires_even_for_unknown_state(self):
        entity, _ = _make_scene()
        entity._handle_state_update({})
        entity.hass.bus.async_fire.assert_called_once()
        args = entity.hass.bus.async_fire.call_args[0]
        assert args[1]["state"] == "unknown"


# ---------------------------------------------------------------------------
# TeletaskScene — async_added_to_hass
# ---------------------------------------------------------------------------

class TestTeletaskSceneAddedToHass:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _fake_state(self, state_str, last_changed=None):
        from datetime import datetime, timezone
        s = MagicMock()
        s.state = state_str
        s.last_changed = last_changed or datetime(2026, 1, 1, tzinfo=timezone.utc)
        return s

    def test_calls_write_ha_state_on_added(self):
        entity, _ = _make_scene()
        self._run(entity.async_added_to_hass())
        entity.async_write_ha_state.assert_called()

    def test_registers_dispatcher_subscription(self):
        entity, hub = _make_scene()
        self._run(entity.async_added_to_hass())
        entity.async_on_remove.assert_called_once()

    def test_signal_format(self):
        """The dispatcher signal must encode central_id, function, and number."""
        entity, hub = _make_scene(fn=FunctionCode.GENMOOD, number=2)
        self._run(entity.async_added_to_hass())
        expected_signal = SIGNAL_STATE_UPDATED.format(
            central_id=hub.central_id,
            function=int(FunctionCode.GENMOOD),
            number=2,
        )
        connect_call = _mod_dispatcher.async_dispatcher_connect.call_args
        assert connect_call[0][1] == expected_signal

    # Since 1.5.5, HA's BaseScene restores the last activation itself. The
    # integration only records a fresh activation when the restored state is
    # not a valid timestamp (e.g. 'OFF' or 'unknown'), so the frontend never
    # gets a non-date value.

    def _with_state(self, monkeypatch, state, parsed):
        monkeypatch.setattr(TeletaskScene, "state", property(lambda self: state), raising=False)
        monkeypatch.setattr(_mod_util.dt, "parse_datetime", MagicMock(return_value=parsed))

    def test_valid_restored_timestamp_is_kept(self, monkeypatch):
        from datetime import datetime, timezone
        ts = "2026-05-01T12:00:00+00:00"
        self._with_state(monkeypatch, ts, datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))
        entity, _ = _make_scene()
        self._run(entity.async_added_to_hass())
        entity._async_record_activation.assert_not_called()
        entity.async_write_ha_state.assert_called()

    @pytest.mark.parametrize("restored", ["OFF", "unknown", ""])
    def test_invalid_restored_state_is_replaced(self, monkeypatch, restored):
        self._with_state(monkeypatch, restored, None)
        entity, _ = _make_scene()
        self._run(entity.async_added_to_hass())
        entity._async_record_activation.assert_called_once()
        entity.async_write_ha_state.assert_called()


# ---------------------------------------------------------------------------
# TeletaskMomentaryButton — state tracking
# ---------------------------------------------------------------------------

class TestTeletaskButtonState:
    def test_initial_state_dict_is_empty(self):
        entity, _ = _make_button()
        assert entity._state_dict == {}

    def test_initial_is_on_false(self):
        entity, _ = _make_button()
        assert entity.is_on is False

    def test_relay_on_sets_is_on_true(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        assert entity.is_on is True

    def test_relay_off_sets_is_on_false(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        entity._handle_state_update({"state": "OFF"})
        assert entity.is_on is False

    def test_relay_on_calls_write_ha_state(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        entity.async_write_ha_state.assert_called_once()

    def test_relay_off_also_calls_write_ha_state(self):
        """OFF transitions are written to HA state — same as any other RELAY."""
        entity, _ = _make_button()
        entity._handle_state_update({"state": "OFF"})
        entity.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# TeletaskMomentaryButton — bus event
# ---------------------------------------------------------------------------

class TestTeletaskButtonBusEvent:
    def test_relay_on_fires_teletask_event(self):
        entity, _ = _make_button(number=16)
        entity._handle_state_update({"state": "ON"})
        entity.hass.bus.async_fire.assert_called_once_with(
            TELETASK_EVENT,
            {"function": "RELAY", "number": 16, "description": "Garage Door", "state": "ON"},
        )

    def test_relay_off_does_not_fire_bus_event(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "OFF"})
        entity.hass.bus.async_fire.assert_not_called()

    def test_multiple_on_events_fire_each_time(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        entity._handle_state_update({"state": "ON"})
        assert entity.hass.bus.async_fire.call_count == 2

    def test_on_off_on_fires_twice_not_three_times(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        entity._handle_state_update({"state": "OFF"})
        entity._handle_state_update({"state": "ON"})
        assert entity.hass.bus.async_fire.call_count == 2


# ---------------------------------------------------------------------------
# TeletaskMomentaryButton — construction
# ---------------------------------------------------------------------------

class TestTeletaskButtonInit:
    def test_default_pulse_ms(self):
        hub = _make_hub()
        comp = {
            "function": int(FunctionCode.RELAY),
            "number": 16,
            "description": "Test",
            "ha_type": "button",
            "function_name": "RELAY",
            "config": {},
            "area": None,
        }
        entity = TeletaskMomentaryButton(hub, comp)
        assert entity._pulse_ms == 500

    def test_custom_pulse_ms(self):
        hub = _make_hub()
        comp = {
            "function": int(FunctionCode.RELAY),
            "number": 16,
            "description": "Test",
            "ha_type": "button",
            "function_name": "RELAY",
            "config": {"pulse_ms": 1000},
            "area": None,
        }
        entity = TeletaskMomentaryButton(hub, comp)
        assert entity._pulse_ms == 1000

    def test_unique_id_format(self):
        entity, hub = _make_button(number=16)
        assert entity._attr_unique_id == f"teletask_{hub.central_id}_{int(FunctionCode.RELAY)}_16"


# ---------------------------------------------------------------------------
# TeletaskMomentaryButton — async_added_to_hass
# ---------------------------------------------------------------------------

class TestTeletaskButtonAddedToHass:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_registers_dispatcher_subscription(self):
        entity, _ = _make_button()
        self._run(entity.async_added_to_hass())
        entity.async_on_remove.assert_called_once()

    def test_signal_format(self):
        entity, hub = _make_button(number=16)
        self._run(entity.async_added_to_hass())
        expected_signal = SIGNAL_STATE_UPDATED.format(
            central_id=hub.central_id,
            function=int(FunctionCode.RELAY),
            number=16,
        )
        connect_call = _mod_dispatcher.async_dispatcher_connect.call_args
        assert connect_call[0][1] == expected_signal

    def test_seeds_state_from_hub_cache(self):
        hub = _make_hub(cached_state={"state": "OFF"})
        comp = {
            "function": int(FunctionCode.RELAY),
            "number": 16,
            "description": "Garage Door",
            "ha_type": "button",
            "function_name": "RELAY",
            "config": {},
            "area": "Garage",
        }
        entity = TeletaskMomentaryButton(hub, comp)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        entity.async_on_remove = MagicMock()
        self._run(entity.async_added_to_hass())
        assert entity._state_dict == {"state": "OFF"}

    def test_calls_write_ha_state_on_init(self):
        entity, _ = _make_button()
        self._run(entity.async_added_to_hass())
        entity.async_write_ha_state.assert_called()


# ---------------------------------------------------------------------------
# Central status: hub connection tracking, Connection and Last event entities
# ---------------------------------------------------------------------------

TeletaskHub = _hub_mod.TeletaskHub
TeletaskCentralConnectionSensor = _binary_sensor_mod.TeletaskCentralConnectionSensor
TeletaskCentralLastEventSensor = _sensor_mod.TeletaskCentralLastEventSensor


def _make_real_hub() -> TeletaskHub:
    return TeletaskHub(MagicMock(), "192.168.11.73", 55957, "home", {"componentsTypes": {}})


class TestHubStatus:
    def setup_method(self):
        _mod_dispatcher.async_dispatcher_send.reset_mock()

    def test_starts_disconnected_without_events(self):
        hub = _make_real_hub()
        assert hub.connected is False
        assert hub.last_event is None
        assert hub.status_signal == "teletask_home_hub_status"

    def test_connection_change_signals_once(self):
        hub = _make_real_hub()
        hub._set_connected(True)
        hub._set_connected(True)          # no change → no second signal
        assert hub.connected is True
        assert _mod_dispatcher.async_dispatcher_send.call_count == 1
        hub._set_connected(False)
        assert hub.connected is False
        assert _mod_dispatcher.async_dispatcher_send.call_count == 2

    def test_disconnect_callback_marks_disconnected(self):
        hub = _make_real_hub()
        hub._set_connected(True)
        hub._schedule_reconnect = MagicMock()
        hub._on_disconnect()
        assert hub.connected is False
        hub._schedule_reconnect.assert_called_once()

    def test_event_records_time_and_signals_status(self):
        hub = _make_real_hub()
        event = _client_mod.TeletaskEvent(function=1, number=22, state={"state": "ON"})
        hub._on_event(event)
        assert hub.last_event == _mod_util.dt.utcnow.return_value
        signals = [c.args[1] for c in _mod_dispatcher.async_dispatcher_send.call_args_list]
        assert "teletask_home_hub_status" in signals
        assert "teletask_home_1_22_state" in signals


def _status_entity(cls, hub):
    entity = cls(hub)
    entity.hass = MagicMock()
    entity.hass.loop.time = MagicMock(return_value=1000.0)
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity


class TestConnectionSensor:
    def test_identity_and_state(self):
        hub = _make_real_hub()
        sensor = _status_entity(TeletaskCentralConnectionSensor, hub)
        assert sensor._attr_unique_id == "teletask_home_central_connection"
        assert sensor._attr_device_info == {"identifiers": {("teletask", "home")}}
        assert sensor._attr_entity_category == "diagnostic"
        assert sensor.is_on is False
        hub.connected = True
        assert sensor.is_on is True
        assert sensor.extra_state_attributes == {"host": "192.168.11.73", "port": 55957}

    async def test_writes_only_on_change(self):
        hub = _make_real_hub()
        sensor = _status_entity(TeletaskCentralConnectionSensor, hub)
        await sensor.async_added_to_hass()
        sensor._handle_status()                       # event, still disconnected
        sensor.async_write_ha_state.assert_not_called()
        hub.connected = True
        sensor._handle_status()
        sensor._handle_status()                       # more events while connected
        assert sensor.async_write_ha_state.call_count == 1


class TestLastEventSensor:
    def setup_method(self):
        _mod_event.async_call_later.reset_mock()
        self.cancel = MagicMock()
        _mod_event.async_call_later.return_value = self.cancel

    async def _added(self):
        hub = _make_real_hub()
        sensor = _status_entity(TeletaskCentralLastEventSensor, hub)
        await sensor.async_added_to_hass()
        return hub, sensor

    async def test_value_is_hub_last_event(self):
        hub, sensor = await self._added()
        assert sensor.native_value is None
        assert sensor._attr_unique_id == "teletask_home_central_last_event"
        hub.last_event = datetime(2026, 11, 7, 12, 0, tzinfo=_tz.utc)
        assert sensor.native_value == hub.last_event

    async def test_burst_is_throttled_with_trailing_write(self):
        hub, sensor = await self._added()               # initial write at t=1000
        sensor.hass.loop.time.return_value = 1010.0
        for _ in range(300):                            # resubscribe burst
            sensor._handle_status()
        sensor.async_write_ha_state.assert_not_called()
        _mod_event.async_call_later.assert_called_once()
        delay = _mod_event.async_call_later.call_args.args[1]
        assert delay == 50.0                            # 60 s since last write

        callback = _mod_event.async_call_later.call_args.args[2]
        sensor.hass.loop.time.return_value = 1060.0
        callback(None)
        sensor.async_write_ha_state.assert_called_once()

    async def test_first_event_after_start_is_written_immediately(self):
        hub, sensor = await self._added()               # added with no event yet
        sensor.hass.loop.time.return_value = 1001.0
        hub.last_event = datetime(2026, 11, 7, 12, 0, tzinfo=_tz.utc)
        sensor._handle_status()                         # first event of the burst
        sensor.async_write_ha_state.assert_called_once()
        _mod_event.async_call_later.assert_not_called()
        hub.last_event = datetime(2026, 11, 7, 12, 0, 1, tzinfo=_tz.utc)
        sensor.hass.loop.time.return_value = 1002.0
        sensor._handle_status()                         # rest of the burst: throttled
        sensor.async_write_ha_state.assert_called_once()
        _mod_event.async_call_later.assert_called_once()

    async def test_writes_immediately_after_quiet_period(self):
        hub, sensor = await self._added()
        sensor.hass.loop.time.return_value = 1100.0     # >60 s since last write
        sensor._handle_status()
        sensor.async_write_ha_state.assert_called_once()
        _mod_event.async_call_later.assert_not_called()

    async def test_pending_write_cancelled_on_remove(self):
        hub, sensor = await self._added()
        remove_cb = sensor.async_on_remove.call_args_list[-1].args[0]
        sensor.hass.loop.time.return_value = 1001.0
        sensor._handle_status()
        remove_cb()
        self.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# Outages: Repairs entry and log noise
# ---------------------------------------------------------------------------

from datetime import timedelta as _td
import logging as _logging

T0 = datetime(2026, 11, 7, 14, 2, tzinfo=_tz.utc)


class TestOutageRepairs:
    def setup_method(self):
        _mod_event.async_call_later.reset_mock()
        _mod_issue_registry.async_create_issue.reset_mock()
        _mod_issue_registry.async_delete_issue.reset_mock()
        self.cancel = MagicMock()
        _mod_event.async_call_later.return_value = self.cancel
        _mod_util.dt.utcnow.return_value = T0
        self.hub = _make_real_hub()
        self.hub._client = MagicMock()
        self.hub._client.last_error = "[Errno 113] No route to host"

    def teardown_method(self):
        _mod_util.dt.utcnow.return_value = datetime(2026, 1, 1, tzinfo=_tz.utc)

    def _fire_issue_timer(self):
        _mod_event.async_call_later.call_args.args[2](None)

    def test_disconnect_schedules_issue_after_delay(self):
        self.hub._set_connected(False)
        assert self.hub.outage_since == T0
        args = _mod_event.async_call_later.call_args.args
        assert args[1] == _td(minutes=5)
        _mod_issue_registry.async_create_issue.assert_not_called()

    def test_issue_created_when_still_down(self):
        self.hub._set_connected(False)
        self._fire_issue_timer()
        call = _mod_issue_registry.async_create_issue.call_args
        assert call.args[1:] == ("teletask", "central_unreachable_home")
        assert call.kwargs["translation_key"] == "central_unreachable"
        assert call.kwargs["is_fixable"] is False
        assert call.kwargs["translation_placeholders"] == {
            "central_id": "home",
            "host": "192.168.11.73",
            "port": "55957",
            "since": "2026-11-07 14:02",
            "error": "[Errno 113] No route to host",
        }

    def test_quick_blip_never_creates_issue(self):
        self.hub._set_connected(True)
        self.hub._set_connected(False)
        _mod_util.dt.utcnow.return_value = T0 + _td(seconds=40)
        self.hub._set_connected(True)
        self.cancel.assert_called_once()                       # timer cancelled
        _mod_issue_registry.async_create_issue.assert_not_called()
        assert self.hub.outage_since is None

    def test_reconnect_clears_issue_and_logs_duration(self, caplog):
        self.hub._set_connected(False)
        self.hub._reconnect_attempts = 24
        self._fire_issue_timer()
        _mod_util.dt.utcnow.return_value = T0 + _td(minutes=12, seconds=5)
        with caplog.at_level(_logging.WARNING):
            self.hub._set_connected(True)
        _mod_issue_registry.async_delete_issue.assert_called_with(
            self.hub.hass, "teletask", "central_unreachable_home"
        )
        assert "after 12m 5s (24 reconnect attempts)" in caplog.text

    def test_repeated_disconnects_keep_original_start(self):
        self.hub._set_connected(False)
        _mod_util.dt.utcnow.return_value = T0 + _td(minutes=3)
        self.hub._set_connected(False)
        assert self.hub.outage_since == T0
        assert _mod_event.async_call_later.call_count == 1

    def test_timer_after_recovery_does_nothing(self):
        self.hub._set_connected(False)
        callback = _mod_event.async_call_later.call_args.args[2]
        self.hub._set_connected(True)
        callback(None)                                         # late timer fire
        _mod_issue_registry.async_create_issue.assert_not_called()

    async def test_stop_removes_issue_and_timer(self):
        self.hub._client.disconnect = AsyncMock()
        self.hub._set_connected(False)
        await self.hub.async_stop()
        self.cancel.assert_called_once()
        _mod_issue_registry.async_delete_issue.assert_called_with(
            self.hub.hass, "teletask", "central_unreachable_home"
        )

    async def test_failed_initial_connect_starts_outage(self, caplog):
        self.hub._client.connect = AsyncMock(return_value=False)
        self.hub.web_coordinator.async_refresh = AsyncMock()
        self.hub.web_coordinator.async_add_listener = MagicMock()
        self.hub._schedule_reconnect = MagicMock()
        with caplog.at_level(_logging.WARNING):
            await self.hub.async_setup()
        assert self.hub.outage_since == T0
        assert "No route to host" in caplog.text
        self.hub._schedule_reconnect.assert_called_once()

    async def test_retries_log_at_debug_only(self, caplog, monkeypatch):
        monkeypatch.setattr(_hub_mod, "RECONNECT_INTERVAL", 0)
        self.hub._set_connected(False)
        self.hub._client.connected = False
        self.hub._client.connect = AsyncMock(side_effect=[False, False, True])
        self.hub._subscribe_all = AsyncMock()
        with caplog.at_level(_logging.DEBUG, logger=_hub_mod._LOGGER.name):
            await self.hub._reconnect_loop()
        warnings = [r for r in caplog.records if r.levelno >= _logging.WARNING]
        debugs = [r.getMessage() for r in caplog.records if r.levelno == _logging.DEBUG]
        assert len(warnings) == 1 and "Reconnected" in warnings[0].getMessage()
        assert "3 reconnect attempts" in warnings[0].getMessage()
        assert sum("Reconnect attempt" in m for m in debugs) == 2
        assert self.hub.connected is True
        self.hub._subscribe_all.assert_awaited_once()


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (45, "45s"), (725, "12m 5s"), (3 * 3600 + 20 * 60 + 9, "3h 20m"), (-5, "0s")],
)
def test_format_duration(seconds, text):
    assert _hub_mod._format_duration(_td(seconds=seconds)) == text


class TestCentralLink:
    """Every component device, scenes included, is "Connected via" the central."""

    def test_scene_device_links_to_central(self):
        hub = _make_hub(central_id="home")
        hub.central_device_id = "central-device-id"
        comp = {"function": FunctionCode.LOCMOOD, "number": 5, "description": "Leaving house",
                "function_name": "LOCMOOD", "config": {}}
        scene = TeletaskScene(hub, comp)
        assert scene._attr_device_info["via_device_id"] == "central-device-id"
        assert "via_device" not in scene._attr_device_info

    def test_falls_back_to_via_device_without_device_id(self):
        hub = _make_hub(central_id="home")
        hub.central_device_id = None
        assert _entity_mod.central_link(hub) == {"via_device": ("teletask", "home")}

    def test_regular_entity_and_scene_use_same_link(self):
        hub = _make_hub(central_id="home")
        hub.central_device_id = "central-device-id"
        relay = {"function": 1, "number": 1, "description": "Garage", "function_name": "RELAY", "config": {}}
        entity = _entity_mod.TeletaskEntity(hub, relay)
        assert entity._attr_device_info["via_device_id"] == "central-device-id"
