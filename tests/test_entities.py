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
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

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


class _ButtonEntity(_Entity):
    pass


# Fixed timestamp for deterministic button tests.
_FIXED_DT = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)

# Build module stubs.
_mod_core = types.ModuleType("homeassistant.core")
_mod_core.callback = _callback
_mod_core.HomeAssistant = MagicMock

_mod_dt = types.ModuleType("homeassistant.util.dt")
_mod_dt.utcnow = staticmethod(lambda: _FIXED_DT)

_mod_util = types.ModuleType("homeassistant.util")
_mod_util.dt = _mod_dt

_mod_entity = types.ModuleType("homeassistant.helpers.entity")
_mod_entity.Entity = _Entity
_mod_entity.DeviceInfo = dict  # DeviceInfo is dict-compatible in entity code

_mod_dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
_mod_dispatcher.async_dispatcher_connect = MagicMock(return_value=lambda: None)
_mod_dispatcher.async_dispatcher_send = MagicMock()

_mod_scene_pkg = types.ModuleType("homeassistant.components.scene")
_mod_scene_pkg.Scene = _Scene

_mod_button_pkg = types.ModuleType("homeassistant.components.button")
_mod_button_pkg.ButtonEntity = _ButtonEntity

_mod_config_entries = types.ModuleType("homeassistant.config_entries")
_mod_config_entries.ConfigEntry = MagicMock

_mod_entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
_mod_entity_platform.AddEntitiesCallback = MagicMock

_HA_MOCKS = {
    "homeassistant":                         types.ModuleType("homeassistant"),
    "homeassistant.core":                    _mod_core,
    "homeassistant.util":                    _mod_util,
    "homeassistant.util.dt":                 _mod_dt,
    "homeassistant.helpers":                 types.ModuleType("homeassistant.helpers"),
    "homeassistant.helpers.entity":          _mod_entity,
    "homeassistant.helpers.dispatcher":      _mod_dispatcher,
    "homeassistant.helpers.entity_platform": _mod_entity_platform,
    "homeassistant.components":              types.ModuleType("homeassistant.components"),
    "homeassistant.components.scene":        _mod_scene_pkg,
    "homeassistant.components.button":       _mod_button_pkg,
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
_hub_mod    = _load_teletask_module("hub")
_scene_mod  = _load_teletask_module("scene")
_button_mod = _load_teletask_module("button")

TeletaskScene          = _scene_mod.TeletaskScene
TeletaskMomentaryButton = _button_mod.TeletaskMomentaryButton
FunctionCode           = _client_mod.FunctionCode
TELETASK_EVENT         = _const_mod.TELETASK_EVENT
SIGNAL_STATE_UPDATED   = _const_mod.SIGNAL_STATE_UPDATED


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_hub(central_id: str = "1", cached_state: dict | None = None) -> MagicMock:
    hub = MagicMock()
    hub.central_id = central_id
    hub.get_state = MagicMock(return_value=cached_state if cached_state is not None else {})
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
    def test_initial_mood_state_is_unknown(self):
        entity, _ = _make_scene()
        assert entity._mood_state == "unknown"

    def test_state_property_returns_mood_state(self):
        entity, _ = _make_scene()
        entity._mood_state = "ON"
        assert entity.state == "ON"

    def test_handle_update_on_sets_mood_state(self):
        entity, _ = _make_scene()
        entity._handle_state_update({"state": "ON"})
        assert entity._mood_state == "ON"

    def test_handle_update_off_sets_mood_state(self):
        entity, _ = _make_scene()
        entity._mood_state = "ON"
        entity._handle_state_update({"state": "OFF"})
        assert entity._mood_state == "OFF"

    def test_handle_update_missing_key_defaults_to_unknown(self):
        entity, _ = _make_scene()
        entity._handle_state_update({})
        assert entity._mood_state == "unknown"

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

    def test_seeds_mood_state_from_cache_on(self):
        entity, _ = _make_scene(cached={"state": "ON"})
        self._run(entity.async_added_to_hass())
        assert entity._mood_state == "ON"

    def test_seeds_mood_state_from_cache_off(self):
        entity, _ = _make_scene(cached={"state": "OFF"})
        self._run(entity.async_added_to_hass())
        assert entity._mood_state == "OFF"

    def test_empty_cache_leaves_unknown(self):
        entity, _ = _make_scene(cached={})
        self._run(entity.async_added_to_hass())
        assert entity._mood_state == "unknown"

    def test_none_cache_leaves_unknown(self):
        entity, _ = _make_scene(cached=None)
        self._run(entity.async_added_to_hass())
        assert entity._mood_state == "unknown"

    def test_calls_write_ha_state_after_seeding(self):
        entity, _ = _make_scene(cached={"state": "ON"})
        self._run(entity.async_added_to_hass())
        entity.async_write_ha_state.assert_called()

    def test_registers_dispatcher_subscription(self):
        entity, hub = _make_scene()
        self._run(entity.async_added_to_hass())
        # async_on_remove must be called with the unsubscribe callable from dispatcher
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


# ---------------------------------------------------------------------------
# TeletaskMomentaryButton — state tracking
# ---------------------------------------------------------------------------

class TestTeletaskButtonState:
    def test_initial_attr_state_is_none(self):
        entity, _ = _make_button()
        assert entity._attr_state is None

    def test_relay_on_sets_attr_state_to_timestamp(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        assert entity._attr_state == _FIXED_DT.isoformat()

    def test_relay_off_does_not_change_attr_state(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "OFF"})
        assert entity._attr_state is None

    def test_relay_on_calls_write_ha_state(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "ON"})
        entity.async_write_ha_state.assert_called_once()

    def test_relay_off_does_not_call_write_ha_state(self):
        entity, _ = _make_button()
        entity._handle_state_update({"state": "OFF"})
        entity.async_write_ha_state.assert_not_called()


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
