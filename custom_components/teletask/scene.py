"""Teletask scene platform — moods and timed functions configured as scenes."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN, SIGNAL_STATE_UPDATED, TELETASK_EVENT
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[Scene] = []

    for fn in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
        for comp in hub.get_components_by_function(fn):
            ha_type = comp.get("ha_type") or comp.get("type") or "switch"
            if ha_type == "scene":
                entities.append(TeletaskScene(hub, comp))

    for comp in hub.get_components_by_function(FunctionCode.TIMEDFNC):
        ha_type = comp.get("ha_type") or comp.get("type") or "switch"
        if ha_type == "scene":
            entities.append(TeletaskScene(hub, comp))

    async_add_entities(entities)


class TeletaskScene(Scene):
    """A Teletask mood or timed function exposed as a scene (activate only)."""

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        self._hub = hub
        self._component = component
        self._function = component["function"]
        self._number = component["number"]
        description = component["description"]
        central_id = hub.central_id

        self._attr_unique_id = f"teletask_{central_id}_{self._function}_{self._number}"
        self._attr_name = description
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{central_id}_{self._function}_{self._number}")},
            name=description,
            manufacturer="Teletask",
            model=component.get("function_name", "Component"),
        )
        if area := component.get("area"):
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    _FN_NAMES = {
        FunctionCode.LOCMOOD:   "LOCMOOD",
        FunctionCode.GENMOOD:   "GENMOOD",
        FunctionCode.TIMEDMOOD: "TIMEDMOOD",
        FunctionCode.TIMEDFNC:  "TIMEDFNC",
    }

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self._hub.central_id,
            function=self._function,
            number=self._number,
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_state_update)
        )
        self.async_write_ha_state()

    @callback
    def _handle_state_update(self, state: dict) -> None:
        new_state = state.get("state", "unknown")
        _LOGGER.debug(
            "SCENE EVENT  %s fn=%d num=%d  state=%s",
            self._attr_name, self._function, self._number, new_state,
        )
        if new_state == "ON":
            self._async_record_activation()
        self.async_write_ha_state()
        self.hass.bus.async_fire(TELETASK_EVENT, {
            "function": self._FN_NAMES.get(self._function, str(self._function)),
            "number": self._number,
            "description": self._attr_name,
            "state": new_state,
        })

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene (turn on the mood/timed function)."""
        fn = self._function
        if fn in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
            await self._hub.async_set_mood(fn, self._number, True)
        elif fn == FunctionCode.TIMEDFNC:
            await self._hub.async_set_timedfnc(self._number, True)
